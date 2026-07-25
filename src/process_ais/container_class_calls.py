"""Container-class AIS call reconstruction + resolution-matched coverage grid (G1-v2 development evidence).

Reproduces the 2026-07-16 recovery finding (`results/development/g1v2_gate_feasibility.md`): restricting AIS
cargo calls (type 70-79) to a deep-sea size class recovers ANNUAL official container-vessel-call coverage for
most gateways, while the MONTHLY call-vs-TEU anomaly does not recover (call-counts vs throughput are
non-equivalent constructs).

IMPORTANT — the length cut here is a DEVELOPMENT sensitivity axis, NOT the frozen container-vessel definition.
The confirmatory classifier (see prereg amendment 1) must prefer external vessel type/subtype, container
capacity, and container-terminal trajectory intersection, with `length_min` retained only as one sensitivity.

Run: python src/process_ais/container_class_calls.py   # regenerates results/development/container_class_coverage_grid.csv
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CENSUS = str(ROOT / "data/interim/national_pings/**/*.parquet").replace("\\", "/")
VC = ROOT / "data/processed/vessel_characteristics.csv"
OFFICIAL_ANNUAL = ROOT / "data/external/g1v2_official_annual"
OFFICIAL_MONTHLY = ROOT / "data/external/g1v2_official"
LENGTH_GRID = (0, 150, 200, 250)          # development sensitivity axis (NOT the frozen definition)

# gateways whose annual/monthly numbers were INSPECTED in development (=> not blind; see amendment holdout note)
DEV_INSPECTED = ("san_pedro_bay", "new_york_new_jersey", "savannah_ga", "norfolk_newport_news_va",
                 "houston_tx", "baltimore_md", "charleston_sc", "jacksonville_fl", "miami_fl",
                 "philadelphia_pa", "port_everglades_fl")


def _con(threads: int = 2, memory: str = "6GB"):
    import duckdb
    tmp = ROOT / "data/interim/duck_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory}'; SET threads={threads}; "
                f"SET temp_directory='{str(tmp).replace(chr(92), '/')}'; SET preserve_insertion_order=false;")
    con.register("vc", pd.read_csv(VC)[["mmsi", "length_m"]])
    return con


def reconstruct_calls(con, complex_id: str, length_min: float, y0: int, y1: int, freq: str = "year") -> pd.Series:
    """Reconstructed container-class port calls per period (freq='year' or 'month'), 24h-gap segmentation."""
    period = "CAST(p.year AS INT)" if freq == "year" else "strftime(p.timestamp, '%Y-%m')"
    q = f"""WITH cargo AS (
        SELECT p.mmsi, p.timestamp ts, {period} per
        FROM read_parquet('{CENSUS}', hive_partitioning=1) p JOIN vc ON p.mmsi = vc.mmsi
        WHERE p.port_complex_id = '{complex_id}' AND p.vessel_type >= 70 AND p.vessel_type < 80
              AND vc.length_m >= {length_min} AND p.year BETWEEN {y0} AND {y1}),
      g AS (SELECT per, CASE WHEN lag(ts) OVER w IS NULL OR epoch(ts) - epoch(lag(ts) OVER w) > 86400
                            THEN 1 ELSE 0 END nc
            FROM cargo WINDOW w AS (PARTITION BY mmsi ORDER BY ts))
      SELECT per, SUM(nc) calls FROM g GROUP BY 1 ORDER BY 1"""
    d = con.execute(q).df()
    return d.set_index("per")["calls"] if len(d) else pd.Series(dtype=float)


def annual_coverage_grid() -> pd.DataFrame:
    con = _con()
    rows = []
    for f in sorted(glob.glob(str(OFFICIAL_ANNUAL / "*__container_vessel_calls__annual.csv"))):
        cid = os.path.basename(f).replace("__container_vessel_calls__annual.csv", "")
        off = pd.read_csv(f).set_index("year")["value"]
        rec = {"complex_id": cid}
        for L in LENGTH_GRID:
            calls = reconstruct_calls(con, cid, L, int(off.index.min()), int(off.index.max()), "year")
            ratios = [calls[y] / off[y] for y in off.index if y in calls.index]
            rec[f"ratio_L{L}"] = round(float(np.mean(ratios)), 3) if ratios else np.nan
        rec["within20pct_L200"] = bool(0.8 <= rec["ratio_L200"] <= 1.2) if pd.notna(rec["ratio_L200"]) else False
        rows.append(rec)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    grid = annual_coverage_grid()
    out = ROOT / "results/development/container_class_coverage_grid.csv"
    grid.to_csv(out, index=False, lineterminator="\n")
    n_ok = int(grid["within20pct_L200"].sum())
    print(grid.to_string(index=False))
    print(f"\nL>=200m annual coverage within +-20%: {n_ok}/{len(grid)} gateways -> {out}")
