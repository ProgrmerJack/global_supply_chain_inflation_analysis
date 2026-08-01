"""Withdrawn exploratory offshore-emissions calculation, retained for audit only.

The former closure was circular and used a published all-source freight total as if it were OGV-only. The two
historical calculations below are incomplete-coverage diagnostics, not bounds or validation:
  (A) GFW loitering events for MERCHANT ('other') vessels x a near-port hoteling rate;
  (B) presence-based estimate: GFW all-vessel offshore presence-hours (rings, cached) x cargo-fraction RANGE x
      the near-port anchor hoteling rate (my model). The cargo fraction is the key uncertainty -> reported as a
      range 10-30%.
The former comparison with ~2,001 t CO2/day is not a like-boundary mass balance.

Run: python src/analysis/offshore_emissions.py
"""
from __future__ import annotations

import datetime as dt
import argparse
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/deep_case_SPB"
sys.path.insert(0, str(ROOT / "src/acquire"))
from env_util import load_env
REGION = {"type": "Polygon", "coordinates": [[[-121.5, 32.0], [-117.3, 32.0], [-117.3, 34.2],
                                              [-121.5, 34.2], [-121.5, 32.0]]]}


def _events(start: str, end: str) -> pd.DataFrame:
    tok = load_env().get("GFW_API_TOKEN", "")
    H = {"Authorization": f"Bearer {tok}", "User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    body = json.dumps({"datasets": ["public-global-loitering-events:latest"],
                       "startDate": start, "endDate": end, "geometry": REGION}).encode()
    rows, offset = [], 0
    while True:
        u = f"https://gateway.api.globalfishingwatch.org/v3/events?limit=200&offset={offset}"
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H, method="POST", data=body),
                                              timeout=90).read())
        for e in d.get("entries", []):
            s = dt.datetime.fromisoformat(e["start"].replace("Z", "+00:00"))
            en = dt.datetime.fromisoformat(e["end"].replace("Z", "+00:00"))
            rows.append({"hours": (en - s).total_seconds() / 3600, "vtype": e.get("vessel", {}).get("type"),
                         "month": s.strftime("%Y-%m"), "dist_port_km": e.get("distances", {}).get("startDistanceFromPortKm")})
        offset += 200
        if offset >= d.get("total", 0):
            break
    return pd.DataFrame(rows)


def _nearport_rate_t_per_vhr() -> float:
    """CO2 tonnes per anchor vessel-hour from my 2021 near-port model."""
    mt = pd.read_csv(ROOT / "data/processed/ais_dwell_census_mode/monthly_mode_time.csv")
    anchor_vhr_2021 = mt[(mt.Port == "LA_Long_Beach") & (mt.YearMonth.str.startswith("2021"))]["anchor_hours"].sum()
    anchor_co2_2021 = 126303.0                       # from emissions_result.md (anchor-mode CO2 2021)
    return anchor_co2_2021 / anchor_vhr_2021


def analyse() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rate = _nearport_rate_t_per_vhr()
    print(f"near-port anchor hoteling rate: {rate:.4f} t CO2 / vessel-hour")

    # (A) incomplete merchant-loitering coverage, Oct-2021
    ev = _events("2021-10-01", "2021-10-31")
    by = ev.groupby("vtype")["hours"].agg(["count", "sum"])
    print("\nOct-2021 SPB-offshore loitering events by vessel type:")
    print(by.to_string())
    merch_vhr = ev.loc[ev.vtype == "other", "hours"].sum()
    merch_co2_day = merch_vhr * rate / 31
    print(f"(A) merchant loitering: {merch_vhr:.0f} vessel-hrs -> {merch_co2_day:.0f} t CO2/day (INCOMPLETE COVERAGE)")

    # (B) presence-based anchored-queue estimate, Oct-2021
    rings = pd.read_csv(ROOT / "data/external/gfw/spb_rings_by_month.csv")
    off_vhr_month = rings[(rings.date == "2021-10") & (rings.ring != "0-50nm")]["hours"].sum()
    off_vhr_day = off_vhr_month / 31
    print(f"\n(B) offshore (50-300nm) all-vessel presence Oct-2021: {off_vhr_day:.0f} vessel-hrs/day")
    for frac in (0.10, 0.20, 0.30):
        est = off_vhr_day * frac * rate
        print(f"    cargo fraction {frac:.0%} -> {est:.0f} t CO2/day offshore")

    # mass balance
    nearport_day = 569                                # my Oct-2021 near-port excess (emissions_heldout_validation)
    published = 2001
    print(f"\nMASS BALANCE (Oct-2021 excess, t CO2/day):")
    print(f"  near-port (my model): {nearport_day}")
    print(f"  + offshore (B, 20% cargo): {off_vhr_day*0.20*rate:.0f}")
    total20 = nearport_day + off_vhr_day * 0.20 * rate
    print(f"  = system total ~{total20:.0f}  vs published {published}  "
          f"({'closes toward' if total20 > nearport_day*1.3 else 'still short of'} the gap)")
    pd.DataFrame([{"component": "near_port", "t_co2_day": nearport_day},
                  {"component": "offshore_merchant_lowerbound", "t_co2_day": round(merch_co2_day)},
                  {"component": "offshore_presence_20pct_cargo", "t_co2_day": round(off_vhr_day * 0.20 * rate)},
                  {"component": "published_excess", "t_co2_day": published}]).to_csv(
        OUT / "offshore_emissions_massbalance.csv", index=False, lineterminator="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reproduce-withdrawn", action="store_true")
    args = parser.parse_args()
    if not args.reproduce_withdrawn:
        raise SystemExit("withdrawn calculation; pass --reproduce-withdrawn only for audit reproduction")
    analyse()
