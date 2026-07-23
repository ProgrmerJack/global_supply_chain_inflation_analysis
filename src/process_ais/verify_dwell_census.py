"""Gate before the full dwell census: run the census on one or more 2022 months and
require the monthly dwell metrics to match the verified 2022 ground-truth parquet.

This exercises the FULL census path (download -> extract -> dwell), unlike
compute_dwell_metrics --validate-2022 which only re-runs the dwell math on stored obs.

Usage:
    .venv/Scripts/python.exe src/process_ais/verify_dwell_census.py --months 3,6
"""
from __future__ import annotations

import argparse
import calendar
import sys
import os

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from build_dwell_census import process_month  # noqa: E402
from compute_dwell_metrics import MONTHLY_2022, RAW_OBS_2022  # noqa: E402


def gold_day_coverage() -> dict[str, int]:
    """Distinct calendar days present per month in the 2022 ground-truth raw obs.
    The surviving 2022 file is day-incomplete (221/365 days), so dwell metrics for
    partially-covered months are biased low — only assert on fully-covered months."""
    obs = pd.read_parquet(RAW_OBS_2022, columns=["BaseDateTime"])
    d = pd.to_datetime(obs["BaseDateTime"], errors="coerce")
    days = pd.DataFrame({"ym": d.dt.to_period("M").astype(str), "day": d.dt.normalize()})
    return days.groupby("ym")["day"].nunique().to_dict()

# Census dwell defines UniqueVessels/Mean/Median identically; ground truth is per
# (Port, YearMonth). A full-month census should match closely. Tolerances are loose on
# dwell means (sampling/rounding of BaseDateTime) but UniqueVessels should be very close.
TOL = {"UniqueVessels": 0.02, "MeanDwellDays": 0.05, "MedianDwellDays": 0.05}  # relative


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="3", help="comma list of 2022 months, e.g. 3,6")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    gold = pd.read_parquet(MONTHLY_2022)
    gold["YearMonth"] = gold["YearMonth"].astype(str)
    cover = gold_day_coverage()

    ok_all = True
    asserted = 0
    for m in [int(x) for x in args.months.split(",")]:
        ym = f"2022-{m:02d}"
        cal_days = calendar.monthrange(2022, m)[1]
        gold_days = cover.get(ym, 0)
        complete = gold_days >= cal_days
        print(f"\n=== census {ym} === (gold has {gold_days}/{cal_days} days; "
              f"{'COMPLETE -> assert' if complete else 'INCOMPLETE -> report only'})")
        monthly, cov = process_month(2022, m, args.workers)
        print(f"  census coverage: days_ok={cov['days_ok']}/{cov['days_total']} err={cov.get('days_error',0)}")
        if monthly is None or not len(monthly):
            print("  [FAIL] no data"); ok_all = False; continue
        g = gold[gold["YearMonth"] == ym]
        cmp = g.merge(monthly, on=["Port", "YearMonth"], suffixes=("_gold", "_new"))
        for _, r in cmp.iterrows():
            line = [r["Port"]]
            for col, tol in TOL.items():
                a, b = r[f"{col}_gold"], r[f"{col}_new"]
                rel = abs(a - b) / max(abs(a), 1e-9)
                flag = "OK" if rel <= tol else ("MISMATCH" if complete else "diff(gold-incomplete)")
                if flag == "MISMATCH":
                    ok_all = False
                line.append(f"{col}: gold={a:.3g} new={b:.3g} ({flag})")
            print("   " + " | ".join(map(str, line)))
        if complete:
            asserted += 1
    if asserted == 0:
        print("\n[WARN] no gold-complete month asserted — pick months from Jan/Feb/Mar")
    print("\n[PASS] census reproduces 2022 ground truth on all complete months" if ok_all
          else "\n[FAIL] census diverges on a gold-complete month — inspect before full run")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
