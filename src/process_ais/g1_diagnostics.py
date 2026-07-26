"""G1 development diagnostics (critique §1, §7): predict what the full daily census will and will not change.

These analyses run on the current development panel + retained pings without touching any confirmatory holdout:

  1. correlation_decomposition  — per-year, leave-one-year-out, drop-pandemic, deseasonalized and
     year-over-year-change correlations. Tests whether the 0.67 median is pandemic-shock-driven (§1).
  2. metric_matching            — median correlation of each AIS measure (unique vessels / cargo vessels /
     ship-days) vs the official series, to see which physical quantity matches (§7).
  3. split_half_reliability     — split each port-month's sampled days into two halves and correlate the two
     activity estimates; low reliability => full daily coverage should raise correlations, high reliability =>
     the ceiling is the comparator/construct, not sampling (§7).

Run from repo root:
  python src/process_ais/g1_diagnostics.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PHASE0 = ROOT
DEFAULT_PANEL = PHASE0 / "data/processed/national_activity_month.csv"
DEFAULT_OFFICIAL = PHASE0 / "data/processed/official_port_activity.csv"
DEFAULT_PINGS = PHASE0 / "data/interim/national_pings"
MIN_MONTHS = 6


def _median_corr(merged: pd.DataFrame, xcol: str, ycol: str, min_months: int = MIN_MONTHS) -> tuple[float, int]:
    rs = []
    for _, g in merged.groupby("port_complex_id"):
        g = g.dropna(subset=[xcol, ycol])
        if len(g) >= min_months and g[xcol].std(ddof=0) > 0 and g[ycol].std(ddof=0) > 0:
            rs.append(np.corrcoef(g[xcol], g[ycol])[0, 1])
    return (float(np.median(rs)) if rs else float("nan")), len(rs)


def correlation_decomposition(ais: pd.DataFrame, official: pd.DataFrame, activity_col: str = "ais_activity") -> dict:
    """Median per-port correlation under period subsets and transforms (tests pandemic-shock dependence)."""
    m = ais.rename(columns={activity_col: "ais"}).merge(
        official.rename(columns={"official_activity": "off"}), on=["port_complex_id", "year_month"])
    m["year"] = m["year_month"].str[:4]
    m["moy"] = m["year_month"].str[5:7]
    years = sorted(m["year"].unique())

    out = {"full": _median_corr(m, "ais", "off")}
    for yr in years:
        out[f"year_{yr}"] = _median_corr(m[m.year == yr], "ais", "off", min_months=6)
    for yr in years:
        out[f"drop_{yr}"] = _median_corr(m[m.year != yr], "ais", "off")
    out["drop_2020_2021"] = _median_corr(m[~m.year.isin(["2020", "2021"])], "ais", "off")

    # deseasonalized: subtract each port's month-of-year mean from both series
    des = m.copy()
    for col in ("ais", "off"):
        des[col] = des[col] - des.groupby(["port_complex_id", "moy"])[col].transform("mean")
    out["deseasonalized"] = _median_corr(des, "ais", "off")

    # year-over-year change (12-month difference) removes slow common trends
    yoy = m.sort_values(["port_complex_id", "year_month"]).copy()
    for col in ("ais", "off"):
        yoy[col] = yoy.groupby("port_complex_id")[col].diff(12)
    out["yoy_change"] = _median_corr(yoy, "ais", "off")
    return out


def metric_matching(panel: pd.DataFrame, official: pd.DataFrame) -> dict:
    """Median correlation of each available AIS measure vs the official series (which physical unit matches)."""
    out = {}
    for measure in (
        "unique_vessels",
        "unique_cargo_vessels",
        "port_calls",
        "cargo_port_calls",
        "freight_port_calls",
        "ship_days",
    ):
        if measure not in panel.columns:
            continue
        ais = panel[["port_complex_id", "year_month", measure]].rename(columns={measure: "ais_activity"})
        m = ais.merge(official, on=["port_complex_id", "year_month"])
        out[measure] = _median_corr(m, "ais_activity", "official_activity")
    return out


def split_half_reliability(pings_dir: Path = DEFAULT_PINGS, reps: int = 30, seed: int = 0) -> dict:
    """Split each port-month's sampled days into two halves; correlate the two cargo-vessel-count estimates.

    Returns the mean split-half correlation and the Spearman-Brown full reliability. Low => sampling noise is
    large and full daily coverage should materially raise correlations; high => the ceiling is the comparator.
    """
    files = sorted(str(p) for p in Path(pings_dir).glob("year=*/month=*/*.parquet"))
    if not files:
        return {"split_half_r": float("nan"), "spearman_brown": float("nan"), "n_port_months": 0}
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'")
    con.execute("SET threads=4")
    # Reduce the census to roughly 60k daily cells before materialising in pandas.
    daily = con.execute(
        """
        SELECT port_complex_id,
               strftime(timestamp AT TIME ZONE 'UTC', '%Y-%m') AS ym,
               strftime(timestamp AT TIME ZONE 'UTC', '%Y-%m-%d') AS day,
               count(DISTINCT mmsi) AS v
        FROM read_parquet(?, union_by_name=true, hive_partitioning=false)
        WHERE vessel_type BETWEEN 70 AND 79.999 AND timestamp IS NOT NULL AND mmsi IS NOT NULL
        GROUP BY 1, 2, 3
        """,
        [str(Path(pings_dir) / "year=*" / "month=*" / "*.parquet")],
    ).fetchdf()
    con.close()
    rng = np.random.default_rng(seed)
    corrs = []
    for _ in range(reps):
        a_vals, b_vals = [], []
        for (_, _), g in daily.groupby(["port_complex_id", "ym"]):
            days = g["day"].tolist()
            if len(days) < 4:
                continue
            rng.shuffle(days)
            half = len(days) // 2
            a = g[g.day.isin(days[:half])]["v"].mean()
            b = g[g.day.isin(days[half:])]["v"].mean()
            a_vals.append(a); b_vals.append(b)
        if len(a_vals) >= 10 and np.std(a_vals) > 0 and np.std(b_vals) > 0:
            corrs.append(np.corrcoef(a_vals, b_vals)[0, 1])
    r = float(np.mean(corrs)) if corrs else float("nan")
    sb = (2 * r / (1 + r)) if (corrs and r < 1) else float("nan")   # Spearman-Brown full reliability
    return {"split_half_r": r, "spearman_brown": sb, "n_port_months": len(a_vals) if corrs else 0}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="optional JSON receipt for the split-half result")
    args = parser.parse_args()
    panel = pd.read_csv(DEFAULT_PANEL)
    official = pd.read_csv(DEFAULT_OFFICIAL)
    ais = panel[["port_complex_id", "year_month", "unique_cargo_vessels"]].rename(
        columns={"unique_cargo_vessels": "ais_activity"})

    print("=== 1. correlation decomposition (median per-port r; cargo vessels vs official value) ===")
    for k, (r, n) in correlation_decomposition(ais, official).items():
        print(f"  {k:18s} median r={r:+.3f}  (n_ports={n})")
    print("\n=== 2. metric matching (median r by AIS measure) ===")
    for k, (r, n) in metric_matching(panel, official).items():
        print(f"  {k:22s} median r={r:+.3f}  (n_ports={n})")
    print("\n=== 3. split-half reliability of the sampled-day activity ===")
    rel = split_half_reliability()
    print(f"  split-half r={rel['split_half_r']:.3f}  Spearman-Brown reliability={rel['spearman_brown']:.3f}  "
          f"(n_port_months={rel['n_port_months']})")
    print("  interpretation: high reliability => low sampling noise => full daily coverage will NOT")
    print("                  materially raise the correlation; the ceiling is the comparator/construct.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rel, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
