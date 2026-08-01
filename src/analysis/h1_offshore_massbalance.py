"""Legacy all-vessel H1 accounting, preserved only for audit.

Governed by `prereg/studies/deep_case_spb/deep_case_SPB_preregistration.md` (FROZEN 2026-07-16): frozen rings 0-50/50-150/150-300 nm,
event date 2021-11-16 and placebo dates 2019/2020/2022-11.

Near-port waiting = LA/LB anchor-hours (monthly_mode_time.csv). Offshore presence = GFW 4wings presence per
ring. GFW presence is all vessels and cannot be treated as waiting or a bound on relocation. The current
registered decision is `results/deep_case_SPB/NS_G1_direct_measurement_report.md`.

Run: python src/analysis/h1_offshore_massbalance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/acquire"))
from gfw import fetch_presence

OUT = ROOT / "results/deep_case_SPB"
CACHE = ROOT / "data/external/gfw/spb_rings_by_month.csv"
CENTER = (33.72, -118.20)                     # SPB breakwater
BOX = [-124.5, -112.0, 28.7, 38.7]            # covers 0-300 nm; binned to rings by distance
EVENT = "2021-11"
PLACEBOS = ["2019-11", "2020-11", "2022-11"]


def _nm(lat, lon):
    R = 6371.0
    p1, p2 = np.radians(lat), np.radians(CENTER[0])
    dphi, dl = np.radians(CENTER[0] - lat), np.radians(CENTER[1] - lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a)) / 1.852


def rings_by_month(years=range(2019, 2024)) -> pd.DataFrame:
    if CACHE.exists():
        return pd.read_csv(CACHE)
    frames = []
    for yr in years:
        d = fetch_presence(BOX, f"{yr}-01-01,{yr}-12-31")
        d["hours"] = pd.to_numeric(d["hours"], errors="coerce")
        d["lat"], d["lon"] = pd.to_numeric(d["lat"]), pd.to_numeric(d["lon"])
        nm = _nm(d["lat"].values, d["lon"].values)
        d["ring"] = np.where(nm <= 50, "0-50nm", np.where(nm <= 150, "50-150nm",
                             np.where(nm <= 300, "150-300nm", "beyond")))
        frames.append(d[d.ring != "beyond"].groupby(["date", "ring"])["hours"].sum().reset_index())
        print(f"  fetched {yr}")
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(CACHE, index=False, lineterminator="\n")
    return out


def near_port_waiting() -> pd.Series:
    d = pd.read_csv(ROOT / "data/processed/ais_dwell_census_mode/monthly_mode_time.csv")
    return d[d.Port == "LA_Long_Beach"].groupby("YearMonth")["anchor_hours"].sum()


def _prepost(series: pd.Series, event: str, win: int = 12) -> tuple[float, float]:
    idx = sorted(series.dropna().index)
    ev = [i for i in idx if i >= event]
    if not ev:
        return np.nan, np.nan
    e0 = idx.index(ev[0])
    pre = series.iloc[max(0, e0 - win):e0].mean()
    post = series.iloc[e0:e0 + win].mean()
    return pre, post


def analyse() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    rings = rings_by_month().pivot(index="date", columns="ring", values="hours")
    rings["total_0_300"] = rings[["0-50nm", "50-150nm", "150-300nm"]].sum(axis=1)
    wait = near_port_waiting()

    rows = []
    for label, ev in [("EVENT 2021-11", EVENT)] + [(f"placebo {p}", p) for p in PLACEBOS]:
        wpre, wpost = _prepost(wait, ev)
        rec = {"window": label, "nearport_pre": round(wpre), "nearport_post": round(wpost),
               "nearport_pct": round(100 * (wpost - wpre) / wpre, 1)}
        for r in ["0-50nm", "50-150nm", "150-300nm", "total_0_300"]:
            pre, post = _prepost(rings[r], ev)
            rec[f"{r}_pct"] = round(100 * (post - pre) / pre, 1)
        rows.append(rec)
    tab = pd.DataFrame(rows)

    ev_row = tab.iloc[0]
    tab.to_csv(OUT / "H1_offshore_massbalance.csv", index=False, lineterminator="\n")
    print(tab.to_string(index=False))
    print(f"\nNear-port waiting change at reform: {ev_row['nearport_pct']}%")
    print(f"Total 0-300 nm presence change: {ev_row['total_0_300_pct']}%")
    print("No relocation verdict: populations and constructs differ; this calculation is superseded by OSF 5sc3v.")
    return tab


if __name__ == "__main__":
    analyse()
