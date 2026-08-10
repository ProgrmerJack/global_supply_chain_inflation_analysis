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
STATE_NAMES = (
    "transit",
    "offshore_wait",
    "approach_channel",
    "official_anchorage",
    "uncharted_near_port_wait",
    "manoeuvre",
    "berth",
    "departure",
)


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


def assign_state_labels(
    obs: pd.DataFrame,
    zones: gpd.GeoDataFrame,
    *,
    zone_priority: tuple[str, ...],
    hoteling_knots: float = HOTELING_SOG_KN,
    transit_knots: float = MANOEUVRE_SOG_KN,
) -> pd.DataFrame:
    """Assign one state per ping from canonical or retained pilot field names.

    Anchorage, berth and offshore-wait zones apply only to stationary pings;
    approach-channel geometry applies at any speed.  This avoids treating a
    vessel transiting a berth polygon as berthed while retaining the explicit
    0.5/3-knot default outside frozen state geometry.
    """
    canonical_columns = {"port_complex_id", "lat", "lon", "sog"}
    pilot_columns = {"Port", "LAT", "LON", "SOG"}
    if canonical_columns <= set(obs.columns):
        port_column, lat_column, lon_column, speed_column = "port_complex_id", "lat", "lon", "sog"
    elif pilot_columns <= set(obs.columns):
        port_column, lat_column, lon_column, speed_column = "Port", "LAT", "LON", "SOG"
    else:
        raise ValueError("state observations require canonical or retained pilot port/coordinate/speed columns")
    if not zone_priority or len(set(zone_priority)) != len(zone_priority):
        raise ValueError("zone_priority must contain unique state names")
    unknown_priority = sorted(set(zone_priority) - set(STATE_NAMES))
    if unknown_priority:
        raise ValueError(f"state zone priority has unsupported states: {unknown_priority}")
    if not 0 <= hoteling_knots < transit_knots:
        raise ValueError("state speed thresholds must satisfy 0 <= hoteling < transit")

    if {"port_complex_id", "state", "geometry"} <= set(zones.columns):
        state_zones = zones[["port_complex_id", "state", "geometry"]].rename(
            columns={"port_complex_id": "_zone_port", "state": "zone_type"}
        )
    elif {"Port", "zone_type", "geometry"} <= set(zones.columns):
        state_zones = zones[["Port", "zone_type", "geometry"]].rename(columns={"Port": "_zone_port"})
    else:
        raise ValueError("state zone file requires canonical or retained pilot port/state/geometry columns")
    state_zones["zone_type"] = state_zones["zone_type"].astype(str).str.lower()
    unknown_zones = sorted(set(state_zones["zone_type"]) - set(STATE_NAMES))
    if unknown_zones:
        raise ValueError(f"state zone file has unsupported states: {unknown_zones}")

    df = obs.copy()
    df["_state_sog"] = pd.to_numeric(df[speed_column], errors="coerce")
    df["_state_lat"] = pd.to_numeric(df[lat_column], errors="coerce")
    df["_state_lon"] = pd.to_numeric(df[lon_column], errors="coerce")
    df["state"] = "uncharted_near_port_wait"
    df.loc[df["_state_sog"].ge(hoteling_knots) & df["_state_sog"].lt(transit_knots), "state"] = "manoeuvre"
    df.loc[df["_state_sog"].ge(transit_knots), "state"] = "transit"

    valid_coordinates = df["_state_lat"].notna() & df["_state_lon"].notna()
    if valid_coordinates.any() and len(state_zones):
        df["_state_row_id"] = range(len(df))
        points = gpd.GeoDataFrame(
            df.loc[valid_coordinates].copy(),
            geometry=gpd.points_from_xy(df.loc[valid_coordinates, "_state_lon"], df.loc[valid_coordinates, "_state_lat"]),
            crs="EPSG:4326",
        ).rename(columns={port_column: "_ping_port"})
        matched = gpd.sjoin(
            points,
            state_zones.to_crs("EPSG:4326"),
            how="left",
            predicate="within",
        )
        matched = matched.loc[matched["_ping_port"].eq(matched["_zone_port"])]
        priority = {state: rank for rank, state in enumerate(zone_priority)}
        matched["_priority"] = matched["zone_type"].map(priority)
        stationary_zone_states = {"official_anchorage", "berth", "offshore_wait"}
        low_speed = matched["_state_sog"].lt(hoteling_knots) | matched["_state_sog"].isna()
        matched = matched.loc[
            matched["_priority"].notna()
            & (~matched["zone_type"].isin(stationary_zone_states) | low_speed)
        ].sort_values(["_state_row_id", "_priority"], kind="stable")
        selected = matched.drop_duplicates("_state_row_id", keep="first")
        df.iloc[selected["_state_row_id"].to_numpy(), df.columns.get_loc("state")] = selected["zone_type"].to_numpy()
        df = df.drop(columns="_state_row_id")

    return df.drop(columns=["geometry", "_state_sog", "_state_lat", "_state_lon"], errors="ignore")


def compute_mode_intervals(obs: pd.DataFrame, gap_cap_hours: float = 2.0) -> pd.DataFrame:
    """Convert successive pings to interval-hours assigned to the starting ping's mode."""
    required = {"MMSI", "Port", "BaseDateTime", "mode"}
    missing = required - set(obs.columns)
    if missing:
        raise ValueError(f"mode observations missing columns: {sorted(missing)}")

    df = obs.copy()
    df["BaseDateTime"] = pd.to_datetime(df["BaseDateTime"], errors="coerce")
    df = df.dropna(subset=["MMSI", "Port", "BaseDateTime"]).sort_values(["MMSI", "Port", "BaseDateTime"])
    group_columns = ["MMSI", "Port"] + (["call_id"] if "call_id" in df.columns else [])
    group = df.groupby(group_columns, sort=False, dropna=False)
    df["next_time"] = group["BaseDateTime"].shift(-1)
    capped_end = df["BaseDateTime"] + pd.to_timedelta(gap_cap_hours, unit="h")
    df["interval_end"] = df["next_time"].where(
        df["next_time"].isna() | df["next_time"].le(capped_end), capped_end
    )
    df = df.loc[df["interval_end"].gt(df["BaseDateTime"])].copy()

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
    start_month = df["BaseDateTime"].dt.strftime("%Y-%m")
    same_month = start_month.eq(df["interval_end"].dt.strftime("%Y-%m"))
    direct = df.loc[same_month].copy()
    direct["YearMonth"] = start_month.loc[same_month]
    direct["interval_hours"] = (
        direct["interval_end"] - direct["BaseDateTime"]
    ).dt.total_seconds() / 3600.0

    split_rows = []
    for row in df.loc[~same_month].itertuples(index=False):
        start, end = row.BaseDateTime, row.interval_end
        while start < end:
            month_end = start.normalize().replace(day=1) + pd.offsets.MonthBegin(1)
            segment_end = min(end, month_end)
            split_rows.append(
                {
                    "MMSI": row.MMSI,
                    "Port": row.Port,
                    "YearMonth": start.strftime("%Y-%m"),
                    "mode": row.mode,
                    "interval_hours": (segment_end - start).total_seconds() / 3600.0,
                    "VesselCategory": row.VesselCategory,
                    "VesselType": row.VesselType,
                    "Length": row.Length,
                    "Width": row.Width,
                }
            )
            start = segment_end

    split = pd.DataFrame(split_rows, columns=cols)
    if split.empty:
        return direct.reindex(columns=cols).reset_index(drop=True)
    if direct.empty:
        return split.reset_index(drop=True)
    return pd.concat([direct.reindex(columns=cols), split], ignore_index=True)


def compute_state_intervals(pings: pd.DataFrame, gap_cap_hours: float = 2.0) -> pd.DataFrame:
    """Apply the tested interval engine to canonical state-labelled pings."""
    required = {"mmsi", "timestamp", "port_complex_id", "state"}
    if missing := required - set(pings.columns):
        raise ValueError(f"state pings missing columns: {sorted(missing)}")
    unknown = sorted(set(pings["state"].dropna()) - set(STATE_NAMES))
    if unknown:
        raise ValueError(f"state pings have unsupported states: {unknown}")

    legacy = pings.rename(
        columns={"mmsi": "MMSI", "timestamp": "BaseDateTime", "port_complex_id": "Port", "state": "mode"}
    )
    intervals = compute_mode_intervals(legacy, gap_cap_hours=gap_cap_hours)
    return intervals.rename(
        columns={"MMSI": "mmsi", "Port": "port_complex_id", "YearMonth": "year_month", "mode": "state"}
    ).reindex(columns=["mmsi", "port_complex_id", "year_month", "state", "interval_hours"])


def aggregate_state_month(intervals: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    """Aggregate covered canonical intervals to a port-state-month panel."""
    keys = ["port_complex_id", "year_month"]
    required_intervals = {"mmsi", *keys, "state", "interval_hours"}
    required_coverage = {*keys, "coverage_ok"}
    if missing := required_intervals - set(intervals.columns):
        raise ValueError(f"state intervals missing columns: {sorted(missing)}")
    if missing := required_coverage - set(coverage.columns):
        raise ValueError(f"state coverage missing columns: {sorted(missing)}")
    if coverage.duplicated(keys).any():
        raise ValueError("state coverage contains duplicate port-month records")

    covered = coverage.loc[coverage["coverage_ok"].eq(True)].copy()
    merged = intervals.merge(covered, on=keys, how="inner", validate="many_to_one")
    if merged.empty:
        metadata = [column for column in coverage.columns if column not in keys]
        return pd.DataFrame(
            columns=[*keys, "unique_vessels", *[f"{state}_hours" for state in STATE_NAMES], "total_interval_hours", *metadata]
        )

    hours = merged.groupby([*keys, "state"], sort=True)["interval_hours"].sum().unstack("state", fill_value=0.0)
    for state in STATE_NAMES:
        if state not in hours:
            hours[state] = 0.0
    hours = hours.loc[:, list(STATE_NAMES)].rename(columns=lambda state: f"{state}_hours").reset_index()
    vessels = merged.groupby(keys, sort=True)["mmsi"].nunique().rename("unique_vessels").reset_index()
    panel = vessels.merge(hours, on=keys, validate="one_to_one").merge(covered, on=keys, validate="one_to_one")
    hour_columns = [f"{state}_hours" for state in STATE_NAMES]
    panel["total_interval_hours"] = panel[hour_columns].sum(axis=1)
    return panel.reindex(columns=[*keys, "unique_vessels", *hour_columns, "total_interval_hours", *[column for column in coverage.columns if column not in keys]])


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
