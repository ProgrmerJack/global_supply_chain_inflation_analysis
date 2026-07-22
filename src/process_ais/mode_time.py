"""
Mode-resolved AIS time aggregation.

This module classifies already-curated in-port AIS pings into operational modes
and converts successive pings into interval-weighted vessel-time. It is deliberately
pure/local: no downloads, no raw-file parsing, and no dwell metric changes.
"""

from __future__ import annotations

import pandas as pd
import geopandas as gpd

HOTELING_SOG_KN = 0.5
MANOEUVRE_SOG_KN = 3.0
MODE_COLUMNS = [
    "anchor_hours",
    "berth_hours",
    "manoeuvre_hours",
    "transit_hours",
    "unknown_hoteling_hours",
]


def load_mode_zones(path: str) -> gpd.GeoDataFrame:
    """Load anchor/berth polygons used for hoteling-mode classification."""
    zones = gpd.read_file(path)
    required = {"Port", "zone_type", "geometry"}
    missing = required - set(zones.columns)
    if missing:
        raise ValueError(f"mode zone file missing columns: {sorted(missing)}")
    zones = zones.to_crs("EPSG:4326")
    zones["zone_type"] = zones["zone_type"].astype(str).str.lower()
    allowed = {"anchor", "berth"}
    bad = sorted(set(zones["zone_type"]) - allowed)
    if bad:
        raise ValueError(f"mode zone file has unsupported zone_type values: {bad}")
    return zones


def assign_mode_labels(obs: pd.DataFrame, zones: gpd.GeoDataFrame) -> pd.DataFrame:
    """Assign each in-port ping to anchor/berth/manoeuvre/transit/unknown_hoteling.

    Speed has precedence for moving modes. Anchor/berth polygons are only used for
    hoteling pings (SOG < 0.5 kn, or missing SOG).
    """
    df = obs.copy()
    df["SOG"] = pd.to_numeric(df["SOG"], errors="coerce")
    df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"] = pd.to_numeric(df["LON"], errors="coerce")

    df["mode"] = "unknown_hoteling"
    df.loc[df["SOG"].ge(HOTELING_SOG_KN) & df["SOG"].lt(MANOEUVRE_SOG_KN), "mode"] = "manoeuvre"
    df.loc[df["SOG"].ge(MANOEUVRE_SOG_KN), "mode"] = "transit"

    hotel = (df["SOG"].lt(HOTELING_SOG_KN) | df["SOG"].isna()) & df["LAT"].notna() & df["LON"].notna()
    if hotel.any() and len(zones):
        pts = gpd.GeoDataFrame(
            df.loc[hotel].copy(),
            geometry=gpd.points_from_xy(df.loc[hotel, "LON"], df.loc[hotel, "LAT"]),
            crs="EPSG:4326",
        )
        joined = gpd.sjoin(
            pts,
            zones[["Port", "zone_type", "geometry"]],
            how="left",
            predicate="within",
            lsuffix="obs",
            rsuffix="zone",
        )
        zone_type = joined.groupby(joined.index)["zone_type"].first()
        df.loc[zone_type[zone_type.eq("anchor")].index, "mode"] = "anchor"
        df.loc[zone_type[zone_type.eq("berth")].index, "mode"] = "berth"

    return df.drop(columns=["geometry"], errors="ignore")


def compute_mode_intervals(obs: pd.DataFrame, gap_cap_hours: float = 2.0) -> pd.DataFrame:
    """Convert successive pings to interval-hours assigned to the starting ping's mode."""
    required = {"MMSI", "Port", "BaseDateTime", "mode"}
    missing = required - set(obs.columns)
    if missing:
        raise ValueError(f"mode observations missing columns: {sorted(missing)}")

    df = obs.copy()
    df["BaseDateTime"] = pd.to_datetime(df["BaseDateTime"], errors="coerce")
    df = df.dropna(subset=["MMSI", "Port", "BaseDateTime"]).sort_values(["MMSI", "Port", "BaseDateTime"])
    group = df.groupby(["MMSI", "Port"], sort=False)
    df["next_time"] = group["BaseDateTime"].shift(-1)
    df["YearMonth"] = df["BaseDateTime"].dt.to_period("M").astype(str)
    df["next_month"] = df["next_time"].dt.to_period("M").astype(str)

    hours = (df["next_time"] - df["BaseDateTime"]).dt.total_seconds() / 3600.0
    df["interval_hours"] = hours.clip(lower=0, upper=gap_cap_hours)
    df.loc[df["next_time"].isna() | (df["next_month"] != df["YearMonth"]), "interval_hours"] = 0.0

    for col in ["VesselCategory", "VesselType", "Length", "Width"]:
        if col not in df.columns:
            df[col] = pd.NA

    cols = [
        "MMSI",
        "Port",
        "YearMonth",
        "mode",
        "interval_hours",
        "VesselCategory",
        "VesselType",
        "Length",
        "Width",
    ]
    return df.loc[df["interval_hours"].gt(0), cols].copy()


def aggregate_monthly_mode_time(intervals: pd.DataFrame) -> pd.DataFrame:
    """Aggregate interval-mode time to one row per vessel, port, and month."""
    if intervals.empty:
        return pd.DataFrame(columns=["MMSI", "Port", "YearMonth", *MODE_COLUMNS, "total_mode_hours"])

    g = intervals.groupby(["MMSI", "Port", "YearMonth", "mode"], sort=True)["interval_hours"].sum()
    wide = g.unstack("mode", fill_value=0.0).reset_index()
    wide = wide.rename(
        columns={
            "anchor": "anchor_hours",
            "berth": "berth_hours",
            "manoeuvre": "manoeuvre_hours",
            "transit": "transit_hours",
            "unknown_hoteling": "unknown_hoteling_hours",
        }
    )
    for col in MODE_COLUMNS:
        if col not in wide.columns:
            wide[col] = 0.0
    wide["total_mode_hours"] = wide[MODE_COLUMNS].sum(axis=1)
    return wide[["MMSI", "Port", "YearMonth", *MODE_COLUMNS, "total_mode_hours"]]
