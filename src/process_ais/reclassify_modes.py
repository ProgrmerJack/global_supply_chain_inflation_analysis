"""
Re-classify operational modes locally from the retained pings — no re-download.

Reads data/processed/ais_dwell_census_mode/port_pings (2015-2025), applies a given
zone file via the validated mode_time functions, and rewrites monthly_mode_time.
Processing is per (year, month) to match the original within-month interval logic.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.compute as pc

sys.path.insert(0, os.path.dirname(__file__))
from mode_time import assign_mode_labels, compute_mode_intervals, aggregate_monthly_mode_time, load_mode_zones  # noqa: E402

PINGS = "data/processed/ais_dwell_census_mode/port_pings"
COLS = ["MMSI", "BaseDateTime", "LAT", "LON", "SOG", "VesselCategory", "VesselType", "Length", "Width", "Port"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zones", default="config/geometry/port_mode_zones_v2.geojson")
    # Writes beside the canonical product rather than over it: promoting a rebuild is a deliberate
    # copy, not a side effect of running this tool. (The old default was `monthly_mode_time_v2.csv`,
    # which read as a data version rather than a scratch rebuild and was byte-identical to canonical.)
    ap.add_argument("--out", default="data/processed/ais_dwell_census_mode/monthly_mode_time.rebuild.csv")
    ap.add_argument("--pings", default=PINGS)
    args = ap.parse_args()

    zones = load_mode_zones(args.zones)
    dset = ds.dataset(args.pings, format="parquet", partitioning="hive")
    years = sorted({int(str(f).split("=")[1]) for f in os.listdir(args.pings) if f.startswith("year=")})
    parts = []
    for y in years:
        for m in range(1, 13):
            t = dset.to_table(columns=COLS, filter=(pc.field("year") == y) & (pc.field("month") == m)).to_pandas()
            if not len(t):
                continue
            classified = assign_mode_labels(t, zones)
            mode_monthly = aggregate_monthly_mode_time(compute_mode_intervals(classified))
            parts.append(mode_monthly)
        done = sum(len(p) for p in parts)
        print(f"  {y}: cumulative vessel-months={done}", flush=True)
    out = pd.concat(parts, ignore_index=True)
    out.to_csv(args.out, index=False)
    print(f"wrote {args.out}  rows={len(out)}")


if __name__ == "__main__":
    main()
