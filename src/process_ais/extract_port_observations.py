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

# canonical -> accepted source names (lowercased match)
_ALIASES = {
    "MMSI": ["mmsi"],
    "BaseDateTime": ["basedatetime", "base_datetime", "base_date_time", "datetime", "timestamp"],
    "LAT": ["lat", "latitude", "y"],
    "LON": ["lon", "lng", "longitude", "x"],
    "SOG": ["sog", "speed", "speedoverground"],
    "VesselName": ["vesselname", "vessel_name", "name"],
    "VesselType": ["vesseltype", "vessel_type", "shiptype"],
    "Length": ["length", "len"],
    "Width": ["width", "beam"],
    "Draft": ["draft", "draught"],
    "Cargo": ["cargo", "cargotype"],
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
    for opt in ["SOG", "VesselName", "Length", "Width", "Draft", "Cargo"]:
        if opt not in df.columns:
            df[opt] = np.nan
    return df


def classify_vessel(vt: pd.Series) -> pd.Series:
    cat = pd.Series("Other", index=vt.index, dtype=object)
    cat[(vt >= 70) & (vt <= 79)] = "Cargo"
    cat[(vt >= 80) & (vt <= 89)] = "Tanker"
    return cat


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

    vt = pd.to_numeric(df["VesselType"], errors="coerce")
    cargo = pd.to_numeric(df["Cargo"], errors="coerce")
    # 2015-2017: VesselType holds 4-digit AVIS service codes (e.g. 1004), not the
    # 2-digit NMEA ship type; the raw 2-digit code lives in the Cargo field (per NOAA
    # Marine Cadastre AIS FAQ). Use VesselType when it is a valid NMEA code (<=99),
    # else fall back to Cargo. For 2018+ vt is already 0-99 so this is a no-op there
    # (keeps the verified 2022 build unchanged).
    eff = vt.where(vt.le(99), cargo)
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
