"""
Extraction layer: raw Marine Cadastre daily AIS file -> port-filtered observations.

This reproduces EXACTLY the filtering used to build the verified 2022 data
(src/analysis/analyze_ais_2022_comprehensive.py): same 5 port bounding boxes, same
cargo+tanker (VesselType 70-89) filter, same output schema. The only differences:

  * vectorized port assignment (boolean masks) instead of a row-wise .apply, so it
    scales to the ~7M rows/day of national AIS files;
  * schema-tolerant column handling so CamelCase (2015-2024) and snake_case (2025)
    files, compressed or not, all map to one canonical schema.

Output columns (matches ais_2022_raw_port_observations.parquet):
    MMSI, BaseDateTime, Date, LAT, LON, SOG, VesselName, VesselType,
    VesselCategory, Port, Length, Width, Draft, Cargo

Feed the output to src/process_ais/compute_dwell_metrics.py.
"""

from __future__ import annotations

import argparse
import os

import geopandas as gpd
import numpy as np
import pandas as pd

# Port bounding boxes — identical to the verified 2022 build.
PORT_DEFINITIONS = {
    "LA_Long_Beach": {"lat_min": 33.65, "lat_max": 33.85, "lon_min": -118.30, "lon_max": -118.10},
    "NY_NJ":         {"lat_min": 40.60, "lat_max": 40.75, "lon_min": -74.10,  "lon_max": -73.95},
    "Houston":       {"lat_min": 29.65, "lat_max": 29.85, "lon_min": -95.05,  "lon_max": -94.85},
    "Savannah":      {"lat_min": 31.95, "lat_max": 32.15, "lon_min": -81.15,  "lon_max": -80.95},
    "Seattle":       {"lat_min": 47.50, "lat_max": 47.70, "lon_min": -122.45, "lon_max": -122.25},
}

# Cargo (70-79) + Tanker (80-89).
VESSEL_TYPE_MIN, VESSEL_TYPE_MAX = 70, 89

OUT_COLS = [
    "MMSI", "BaseDateTime", "Date", "LAT", "LON", "SOG",
    "VesselName", "VesselType", "VesselCategory", "Port",
    "Length", "Width", "Draft", "Cargo",
]

CANONICAL_PING_COLUMNS = [
    "mmsi",
    "timestamp",
    "lon",
    "lat",
    "sog",
    "cog",
    "vessel_type",
    "length",     # AIS static: vessel dimensions (emissions size-binning + G1 size-composition validation)
    "width",
    "draft",
    "imo",        # stable vessel identity for external-registry joins (MMSI can change; IMO does not)
    "status",     # AIS navigation status (independent state-validation label; at-berth / shore-power inference)
    "source_file",
    "port_complex_id",
]
REJECTION_COLUMNS = ["row_number", "reason", "source_file", "port_complex_id"]
# dedup identity = position/speed/type at a time & place; NOT the near-constant vessel-static fields
PING_IDENTITY_COLUMNS = ["mmsi", "timestamp", "lon", "lat", "sog", "cog", "vessel_type", "port_complex_id"]

# canonical -> accepted source names (lowercased match)
_ALIASES = {
    "MMSI": ["mmsi"],
    "BaseDateTime": ["basedatetime", "base_datetime", "base_date_time", "datetime", "timestamp"],
    "LAT": ["lat", "latitude", "y"],
    "LON": ["lon", "lng", "longitude", "x"],
    "SOG": ["sog", "speed", "speedoverground"],
    "COG": ["cog", "courseoverground"],
    "VesselName": ["vesselname", "vessel_name", "name"],
    "VesselType": ["vesseltype", "vessel_type", "shiptype"],
    "Length": ["length", "len"],
    "Width": ["width", "beam"],
    "Draft": ["draft", "draught"],
    "Cargo": ["cargo", "cargotype"],
    "IMO": ["imo", "imonumber", "imo_number"],
    "Status": ["status", "navigationalstatus", "navigation_status", "navstatus"],
}
REQUIRED_SOURCE = ["MMSI", "BaseDateTime", "LAT", "LON", "VesselType"]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename source columns to the canonical schema (case/format tolerant)."""
    lower = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for canon, alts in _ALIASES.items():
        for a in alts:
            if a in lower:
                rename[lower[a]] = canon
                break
    df = df.rename(columns=rename)
    missing = [c for c in REQUIRED_SOURCE if c not in df.columns]
    if missing:
        raise ValueError(f"file missing required columns {missing}; saw {list(df.columns)[:20]}")
    for opt in ["SOG", "COG", "VesselName", "Length", "Width", "Draft", "Cargo", "IMO", "Status"]:
        if opt not in df.columns:
            df[opt] = np.nan
    return df


def classify_vessel(vt: pd.Series) -> pd.Series:
    cat = pd.Series("Other", index=vt.index, dtype=object)
    cat[(vt >= 70) & (vt <= 79)] = "Cargo"
    cat[(vt >= 80) & (vt <= 89)] = "Tanker"
    return cat


def effective_vessel_type(vessel_type: pd.Series, cargo: pd.Series) -> pd.Series:
    """Return the NMEA vessel type, correcting early AIS service codes from Cargo."""
    vessel_type = pd.to_numeric(vessel_type, errors="coerce")
    cargo = pd.to_numeric(cargo, errors="coerce")
    # 2015-2017: VesselType holds 4-digit AVIS service codes (e.g. 1004), not the
    # 2-digit NMEA ship type; the raw 2-digit code lives in the Cargo field (per NOAA
    # Marine Cadastre AIS FAQ). Use VesselType when it is a valid NMEA code (<=99),
    # else fall back to Cargo. For 2018+ VesselType is already 0-99.
    return vessel_type.where(vessel_type.le(99), cargo)


def normalise_pings(
    raw: pd.DataFrame,
    *,
    source_file: str,
    port_complex_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return canonical AIS pings and an auditable ledger for rejected source rows."""
    frame = normalize_columns(raw.copy())
    effective_type = effective_vessel_type(frame["VesselType"], frame["Cargo"])
    mmsi = pd.to_numeric(frame["MMSI"], errors="coerce")
    timestamp = pd.to_datetime(frame["BaseDateTime"], errors="coerce", utc=True)
    lon = pd.to_numeric(frame["LON"], errors="coerce")
    lat = pd.to_numeric(frame["LAT"], errors="coerce")

    valid_mmsi = mmsi.notna() & mmsi.between(100_000_000, 799_999_999) & mmsi.eq(mmsi.round())
    valid_timestamp = timestamp.notna()
    valid_coordinate = lat.between(-90, 90) & lon.between(-180, 180)
    valid_vessel_type = effective_type.between(VESSEL_TYPE_MIN, VESSEL_TYPE_MAX)
    accepted_mask = valid_mmsi & valid_timestamp & valid_coordinate & valid_vessel_type

    reason = pd.Series(pd.NA, index=frame.index, dtype="string")
    for invalid, label in (
        (~valid_mmsi, "invalid_mmsi"),
        (~valid_timestamp, "invalid_timestamp"),
        (~valid_coordinate, "coordinate_out_of_range"),
        (~valid_vessel_type, "unsupported_vessel_type"),
    ):
        reason.loc[reason.isna() & invalid] = label

    canonical = pd.DataFrame(
        {
            "mmsi": mmsi.astype("Int64"),
            "timestamp": timestamp,
            "lon": lon,
            "lat": lat,
            "sog": pd.to_numeric(frame["SOG"], errors="coerce"),
            "cog": pd.to_numeric(frame.get("COG", np.nan), errors="coerce"),
            "vessel_type": effective_type,
            "length": pd.to_numeric(frame["Length"], errors="coerce"),
            "width": pd.to_numeric(frame["Width"], errors="coerce"),
            "draft": pd.to_numeric(frame["Draft"], errors="coerce"),
            "imo": pd.to_numeric(frame["IMO"], errors="coerce").astype("Int64"),
            "status": pd.to_numeric(frame["Status"], errors="coerce").astype("Int64"),
            "source_file": source_file,
            "port_complex_id": port_complex_id,
        }
    )
    rejected = pd.DataFrame(
        {
            "row_number": frame.index,
            "reason": reason,
            "source_file": source_file,
            "port_complex_id": port_complex_id,
        },
        index=frame.index,
    ).loc[~accepted_mask]
    return (
        canonical.loc[accepted_mask].reset_index(drop=True).reindex(columns=CANONICAL_PING_COLUMNS),
        rejected.reset_index(drop=True).reindex(columns=REJECTION_COLUMNS),
    )


def deduplicate_pings(pings: pd.DataFrame) -> pd.DataFrame:
    """Keep one deterministic provenance record for each exact canonical ping."""
    required = set(PING_IDENTITY_COLUMNS) | {"source_file"}
    if missing := required - set(pings.columns):
        raise ValueError(f"canonical pings missing columns: {sorted(missing)}")
    return (
        pings.sort_values([*PING_IDENTITY_COLUMNS, "source_file"], kind="stable")
        .drop_duplicates(subset=PING_IDENTITY_COLUMNS, keep="first")
        .reset_index(drop=True)
    )


def assign_pings_to_safe_port_areas(
    pings: pd.DataFrame,
    port_areas: gpd.GeoDataFrame,
    assignment_coverage: pd.DataFrame,
) -> pd.DataFrame:
    """Assign canonical pings only to port areas approved for unambiguous spatial use."""
    if missing := set(CANONICAL_PING_COLUMNS) - set(pings.columns):
        raise ValueError(f"canonical pings missing columns: {sorted(missing)}")
    if missing := {"port_complex_id", "geometry"} - set(port_areas.columns):
        raise ValueError(f"port areas missing columns: {sorted(missing)}")
    if missing := {"port_complex_id", "spatial_assignment_status"} - set(assignment_coverage.columns):
        raise ValueError(f"port-area assignment coverage missing columns: {sorted(missing)}")
    if port_areas.port_complex_id.duplicated().any() or assignment_coverage.port_complex_id.duplicated().any():
        raise ValueError("port-area assignment inputs require unique port_complex_id values")

    safe_ids = assignment_coverage.loc[
        assignment_coverage.spatial_assignment_status.eq("assignable"), "port_complex_id"
    ]
    missing_areas = sorted(set(safe_ids) - set(port_areas.port_complex_id))
    if missing_areas:
        raise ValueError(f"assignment coverage references missing port areas: {', '.join(missing_areas)}")
    if not len(safe_ids):
        return pings.iloc[0:0].reindex(columns=CANONICAL_PING_COLUMNS).copy()

    points = gpd.GeoDataFrame(
        pings.reindex(columns=CANONICAL_PING_COLUMNS).copy(),
        geometry=gpd.points_from_xy(pings.lon, pings.lat),
        crs="EPSG:4326",
    )
    points["_source_row"] = range(len(points))
    safe_areas = port_areas.loc[port_areas.port_complex_id.isin(safe_ids), ["port_complex_id", "geometry"]].rename(
        columns={"port_complex_id": "_assigned_port_complex_id"}
    )
    joined = gpd.sjoin(points, safe_areas.to_crs("EPSG:4326"), how="inner", predicate="within")
    if joined["_source_row"].duplicated().any():
        raise ValueError("assignment-approved port areas overlap; refusing ambiguous ping assignment")
    joined = joined.sort_values("_source_row", kind="stable")
    joined["port_complex_id"] = joined["_assigned_port_complex_id"]
    return pd.DataFrame(joined.reindex(columns=CANONICAL_PING_COLUMNS)).reset_index(drop=True)


def _assign_port(lat: pd.Series, lon: pd.Series) -> pd.Series:
    """Vectorized first-match-wins port assignment over the disjoint boxes."""
    port = pd.Series(pd.NA, index=lat.index, dtype=object)
    for code, b in PORT_DEFINITIONS.items():
        m = (
            port.isna()
            & lat.between(b["lat_min"], b["lat_max"])
            & lon.between(b["lon_min"], b["lon_max"])
        )
        port[m] = code
    return port


def extract_from_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Filter one (chunk of a) daily AIS frame to in-port cargo/tanker observations."""
    df = normalize_columns(df)

    eff = effective_vessel_type(df["VesselType"], df["Cargo"])
    keep = eff.between(VESSEL_TYPE_MIN, VESSEL_TYPE_MAX)
    df = df[keep].copy()
    if df.empty:
        return pd.DataFrame(columns=OUT_COLS)
    df["VesselType"] = eff[keep].values

    df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"] = pd.to_numeric(df["LON"], errors="coerce")
    df["Port"] = _assign_port(df["LAT"], df["LON"])
    df = df[df["Port"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=OUT_COLS)

    df["VesselType"] = pd.to_numeric(df["VesselType"], errors="coerce")
    df["VesselCategory"] = classify_vessel(df["VesselType"])
    dt = pd.to_datetime(df["BaseDateTime"], errors="coerce")
    df["Date"] = dt.dt.strftime("%Y_%m_%d")
    return df.reindex(columns=OUT_COLS)


def _read_chunks(path: str, chunksize: int):
    """Yield DataFrame chunks, handling .csv / .csv.zst / .gz / .zip transparently."""
    compression = "infer"
    if path.endswith(".zst"):
        compression = "zstd"  # pandas>=2 + `zstandard` installed
    try:
        yield from pd.read_csv(path, chunksize=chunksize, compression=compression, low_memory=False)
    except (ValueError, ImportError) as e:
        if "zstd" in str(e).lower() or "zstandard" in str(e).lower():
            raise RuntimeError(
                f"{path} is zstd-compressed; `pip install zstandard` to read it."
            ) from e
        raise


def extract_file(path: str, chunksize: int = 1_000_000) -> pd.DataFrame:
    """Extract in-port cargo/tanker observations from one daily AIS file."""
    parts = [extract_from_dataframe(ch) for ch in _read_chunks(path, chunksize)]
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=OUT_COLS)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract port observations from one AIS file.")
    ap.add_argument("path", help="daily AIS file (.csv/.csv.zst/.gz)")
    ap.add_argument("--out", help="optional parquet output path")
    ap.add_argument("--chunksize", type=int, default=1_000_000)
    args = ap.parse_args()

    obs = extract_file(args.path, args.chunksize)
    print(f"{os.path.basename(args.path)}: {len(obs):,} in-port cargo/tanker observations")
    if len(obs):
        print(obs["Port"].value_counts().to_string())
    if args.out:
        obs.to_parquet(args.out, index=False)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
