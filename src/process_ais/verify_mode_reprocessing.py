"""Verify mode-resolved reprocessing preserves validated dwell metrics."""

from __future__ import annotations

import argparse

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="baseline monthly dwell CSV")
    ap.add_argument("--new", required=True, help="mode-reprocessed monthly dwell CSV")
    ap.add_argument("--mode", required=True, help="mode-time CSV produced by the reprocess")
    args = ap.parse_args()

    old = pd.read_csv(args.old)
    new = pd.read_csv(args.new)
    keys = ["Port", "YearMonth"]
    check_cols = ["UniqueVessels", "MeanDwellDays", "MedianDwellDays", "TotalObservations"]

    new_keys = new[keys].drop_duplicates()
    old_subset = old.merge(new_keys, on=keys, how="inner")
    merged = old_subset[keys + check_cols].merge(new[keys + check_cols], on=keys, suffixes=("_old", "_new"))
    if len(merged) != len(new):
        raise SystemExit(f"row mismatch: old_matched={len(merged)} new={len(new)}")

    for col in check_cols:
        tol = 0 if col in {"UniqueVessels", "TotalObservations"} else 1e-9
        diff = (merged[f"{col}_old"] - merged[f"{col}_new"]).abs().max()
        if diff > tol:
            raise SystemExit(f"{col} changed: max diff={diff}")

    mode = pd.read_csv(args.mode)
    required = {"anchor_hours", "berth_hours", "manoeuvre_hours", "transit_hours", "total_mode_hours"}
    missing = required - set(mode.columns)
    if missing:
        raise SystemExit(f"mode file missing columns: {sorted(missing)}")
    if mode.empty:
        raise SystemExit("mode file has no rows")
    if mode["total_mode_hours"].le(0).all():
        raise SystemExit("all mode hours are zero")

    print("PASS: dwell unchanged and mode-time output sane")


if __name__ == "__main__":
    main()
