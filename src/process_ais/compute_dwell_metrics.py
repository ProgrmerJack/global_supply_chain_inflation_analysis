"""
Generalized, vectorized AIS dwell-time -> monthly congestion metrics.

This is the reusable core of Route A. It reproduces the *verified* 2022 dwell
methodology so that, once additional years of raw AIS are re-downloaded and
filtered to the port bounding boxes, a long monthly congestion series can be built
with identical logic across years.

It deliberately replaces the legacy toy in src/process_ais/process_ais_data.py,
which (a) used a row-wise .apply over every record, (b) processed only the first 5
files, and (c) approximated dwell as observation_count * 0.5h rather than an actual
entry->exit episode.

PIPELINE
    port_observations (one row per AIS ping inside a port box)
        -> compute_vessel_dwell   : per (MMSI, Port, YearMonth) episode dwell
        -> aggregate_monthly       : per (Port, YearMonth) congestion metrics

DWELL DEFINITION (matches ais_2022_vessel_dwell_times.parquet)
    DwellDays = (LastObserved - FirstObserved) within a port-month, in days.
    Monthly MeanDwellDays / MedianDwellDays are taken over vessels.

Required port-observation columns:
    MMSI, BaseDateTime, Port, VesselCategory, Length, Width
(BaseDateTime parseable to datetime.)

VALIDATION
    Run with --validate-2022 to rebuild 2022 monthly metrics from the surviving
    port-observation parquet and assert they match the stored, known-good file:
        .venv/Scripts/python.exe src/process_ais/compute_dwell_metrics.py --validate-2022
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

RAW_OBS_2022 = "data/processed/ais_2022_analysis/ais_2022_raw_port_observations.parquet"
MONTHLY_2022 = "data/processed/ais_2022_analysis/ais_2022_monthly_port_metrics.parquet"

REQUIRED_COLS = ["MMSI", "BaseDateTime", "Port", "VesselCategory", "Length", "Width"]


def compute_vessel_dwell(obs: pd.DataFrame) -> pd.DataFrame:
    """Per (MMSI, Port, YearMonth) dwell episode from port-filtered observations.

    Vectorized groupby aggregation (no row-wise apply).
    """
    missing = [c for c in REQUIRED_COLS if c not in obs.columns]
    if missing:
        raise ValueError(f"port observations missing columns: {missing}")

    df = obs[REQUIRED_COLS].copy()
    df["BaseDateTime"] = pd.to_datetime(df["BaseDateTime"], errors="coerce")
    df = df.dropna(subset=["BaseDateTime", "MMSI", "Port"])
    df["YearMonth"] = df["BaseDateTime"].dt.to_period("M").astype(str)

    g = df.groupby(["MMSI", "Port", "YearMonth"], sort=False)
    dwell = g.agg(
        FirstObserved=("BaseDateTime", "min"),
        LastObserved=("BaseDateTime", "max"),
        ObservationCount=("BaseDateTime", "size"),
        VesselCategory=("VesselCategory", "first"),
        Length=("Length", "first"),
        Width=("Width", "first"),
    ).reset_index()

    dwell["DwellDays"] = (
        dwell["LastObserved"] - dwell["FirstObserved"]
    ).dt.total_seconds() / 86400.0
    return dwell


def aggregate_monthly(dwell: pd.DataFrame) -> pd.DataFrame:
    """Per (Port, YearMonth) monthly congestion metrics from vessel dwell episodes."""
    g = dwell.groupby(["Port", "YearMonth"], sort=True)
    monthly = g.agg(
        UniqueVessels=("MMSI", "nunique"),
        MeanDwellDays=("DwellDays", "mean"),
        MedianDwellDays=("DwellDays", "median"),
        StdDwellDays=("DwellDays", "std"),
        MinDwellDays=("DwellDays", "min"),
        MaxDwellDays=("DwellDays", "max"),
        TotalObservations=("ObservationCount", "sum"),
        AvgVesselLength=("Length", "mean"),
    ).reset_index()
    monthly["PortName"] = monthly["Port"]
    return monthly


def process_port_observations(obs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Full pipeline: observations -> (vessel dwell episodes, monthly metrics)."""
    dwell = compute_vessel_dwell(obs)
    monthly = aggregate_monthly(dwell)
    return dwell, monthly


def validate_2022() -> int:
    """Rebuild 2022 monthly metrics from raw obs; compare to known-good file."""
    print(f"Loading port observations: {RAW_OBS_2022}")
    obs = pd.read_parquet(RAW_OBS_2022)
    print(f"  {len(obs):,} observations")

    _, rebuilt = process_port_observations(obs)
    gold = pd.read_parquet(MONTHLY_2022)

    keys = ["Port", "YearMonth"]
    rebuilt["YearMonth"] = rebuilt["YearMonth"].astype(str)
    gold["YearMonth"] = gold["YearMonth"].astype(str)

    merged = gold.merge(rebuilt, on=keys, suffixes=("_gold", "_new"), how="outer", indicator=True)
    only = merged[merged["_merge"] != "both"]
    if len(only):
        print(f"  [FAIL] {len(only)} port-month rows not matched 1:1")
        print(only[keys + ["_merge"]].to_string(index=False))
        return 1

    checks = {
        "UniqueVessels": 0,            # exact integer match expected
        "MeanDwellDays": 1e-6,
        "MedianDwellDays": 1e-6,
        "TotalObservations": 0,
    }
    ok = True
    print(f"\n  Comparing {len(merged)} port-month rows on {list(checks)}:")
    for col, tol in checks.items():
        diff = (merged[f"{col}_gold"] - merged[f"{col}_new"]).abs()
        maxd = float(diff.max())
        passed = maxd <= tol
        ok = ok and passed
        print(f"    {col:18s} max abs diff = {maxd:.3e}  tol={tol:.0e}  {'OK' if passed else 'MISMATCH'}")

    if ok:
        print("\n  [PASS] Generalized dwell pipeline reproduces the verified 2022 metrics.")
        return 0
    print("\n  [FAIL] Dwell pipeline does not reproduce 2022 metrics.")
    return 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--validate-2022",
        action="store_true",
        help="reproduce 2022 monthly metrics from surviving raw obs and compare",
    )
    args = ap.parse_args()
    if args.validate_2022:
        sys.exit(validate_2022())
    ap.print_help()


if __name__ == "__main__":
    main()
