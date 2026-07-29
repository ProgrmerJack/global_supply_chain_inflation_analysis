"""
Build the LA-headline port-congestion index from the DWELL-time census, merge onto the
macro panel, and compute the real correlation with the NY Fed GSCPI.

Congestion metric = monthly mean vessel dwell time (days in port, entry->exit) at the
port, from the full daily census (build_dwell_census*.py). This is the wait-time measure
the manuscript describes — unlike the occupancy proxy. Reads both the 2015-2025 CSV-era
census and, if present, the 2009-2014 FGDB-era census, into one 2009-2025 series.

Per port we regress dwell on a linear trend + month dummies (deseasonalize; the trend is
near-flat for dwell) and standardize the residual. Headline shock = LA/Long Beach (the
only port that tracks GSCPI); a cross-port composite and per-port series are kept for the
heterogeneity/robustness panel.

Inputs
    data/processed/ais_dwell_census/monthly_dwell.csv            (2015-2025)
    data/processed/ais_dwell_census/monthly_dwell_2009_2014.csv  (optional, 2009-2014)
    data/processed/analysis_dataset.csv                          (FRED macro + gscpi)

Outputs
    data/processed/analysis_dataset_dwell.csv
    outputs/figures/dwell_vs_gscpi.png
    outputs/dwell_validation.json
"""

from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

CENSUS_DIR = "data/processed/ais_dwell_census"
MONTHLY = os.path.join(CENSUS_DIR, "monthly_dwell.csv")
MONTHLY_FGDB = os.path.join(CENSUS_DIR, "monthly_dwell_2009_2014.csv")
MACRO = "data/processed/analysis_dataset.csv"
OUT_CSV = "data/processed/analysis_dataset_dwell.csv"
OUT_FIG = "outputs/figures/dwell_vs_gscpi.png"
OUT_JSON = "outputs/dwell_validation.json"
PORTS = ["LA_Long_Beach", "NY_NJ", "Houston", "Savannah", "Seattle"]
REF_PORT = "LA_Long_Beach"
METRIC = "MeanDwellDays"
MIN_MONTHS = 24


def _z(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd and sd > 0 else s * 0.0


def _detrend_z(g: pd.DataFrame) -> pd.Series:
    g = g.sort_values("date").reset_index(drop=True)
    y = g[METRIC].astype(float)
    t = pd.Series(np.arange(len(g)), name="t")
    month = pd.Categorical(g["date"].dt.month, categories=range(1, 13))
    dummies = pd.get_dummies(month, prefix="m", drop_first=True).astype(float)
    X = sm.add_constant(pd.concat([t, dummies], axis=1)).values.astype(float)
    resid = sm.OLS(y.values, X).fit().resid
    z = _z(pd.Series(resid))
    z.index = g["date"].values
    return z


def _load_census() -> pd.DataFrame:
    if not os.path.exists(MONTHLY):
        raise FileNotFoundError(f"{MONTHLY} not found — run build_dwell_census.py first.")
    frames = [pd.read_csv(MONTHLY)]
    # the FGDB census creates this file empty at startup and fills it as months finish;
    # include it only once it has data so an in-progress run doesn't break the build.
    if os.path.exists(MONTHLY_FGDB) and os.path.getsize(MONTHLY_FGDB) > 0:
        frames.append(pd.read_csv(MONTHLY_FGDB))
    m = pd.concat(frames, ignore_index=True)
    m["date"] = pd.to_datetime(m["YearMonth"], format="%Y-%m")
    # if a month appears in both eras (shouldn't), prefer the CSV-era row (first)
    m = m.drop_duplicates(subset=["Port", "YearMonth"], keep="first")
    return m


def build() -> dict:
    m = _load_census()
    per_port = {}
    for p in PORTS:
        g = m[m["Port"] == p]
        if len(g) >= MIN_MONTHS:
            per_port[p] = _detrend_z(g)
    if not per_port:
        raise ValueError("no port has enough months")
    wide = pd.DataFrame(per_port).sort_index()
    composite = _z(wide.mean(axis=1, skipna=True))

    ref = m[m["Port"] == REF_PORT].sort_values("date")
    idx = pd.DataFrame({"date": composite.index, "dwell_composite": composite.values})
    idx = idx.merge(ref[["date", METRIC, "UniqueVessels"]].rename(
        columns={METRIC: "dwell_la_raw", "UniqueVessels": "la_unique_vessels"}),
        on="date", how="left")
    if REF_PORT in wide.columns:
        idx = idx.merge(wide[REF_PORT].rename("dwell_la_detrended").reset_index()
                        .rename(columns={"index": "date"}), on="date", how="left")

    macro = pd.read_csv(MACRO, parse_dates=["date"])
    merged = macro.merge(idx, on="date", how="left")
    merged.to_csv(OUT_CSV, index=False)
    print(f"wrote {OUT_CSV}  (dwell months: {idx['date'].nunique()}, "
          f"{idx['date'].min():%Y-%m}..{idx['date'].max():%Y-%m}, ports: {list(wide.columns)})")

    ov = merged.dropna(subset=["dwell_la_raw", "gscpi"])
    res: dict = {"metric": METRIC, "ports_used": list(wide.columns),
                 "n_overlap_months": int(len(ov)),
                 "overlap": f"{ov['date'].min():%Y-%m}..{ov['date'].max():%Y-%m}" if len(ov) else None}
    if len(ov) >= 3:
        for col, key in [("dwell_la_raw", "la_raw"), ("dwell_la_detrended", "la_detrended"),
                         ("dwell_composite", "composite")]:
            if col in ov and ov[col].notna().sum() >= 3:
                sub = ov.dropna(subset=[col])
                r, p = stats.pearsonr(sub[col], sub["gscpi"])
                res[f"pearson_r_{key}_vs_gscpi"] = round(float(r), 4)
                res[f"pearson_p_{key}_vs_gscpi"] = round(float(p), 4)
        print(f"REAL corr vs GSCPI (n={len(ov)}): LA dwell r={res.get('pearson_r_la_raw_vs_gscpi')}, "
              f"LA detrended r={res.get('pearson_r_la_detrended_vs_gscpi')}, "
              f"composite r={res.get('pearson_r_composite_vs_gscpi')}")
    return {"merged": merged, "overlap": ov, "res": res}


def figure(ov: pd.DataFrame) -> None:
    if ov.empty:
        return
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(ov["date"], ov["dwell_la_raw"], color="C3", lw=1.6, label="LA/LB mean dwell (days)")
    ax1.set_ylabel("mean dwell (days)", color="C3"); ax1.tick_params(axis="y", labelcolor="C3")
    ax2 = ax1.twinx()
    ax2.plot(ov["date"], ov["gscpi"], color="C0", lw=1.2, ls="--", label="NY Fed GSCPI")
    ax2.set_ylabel("GSCPI (SD)", color="C0"); ax2.tick_params(axis="y", labelcolor="C0")
    plt.title("AIS port dwell-time congestion (LA/LB) vs NY Fed GSCPI")
    fig.tight_layout(); os.makedirs(os.path.dirname(OUT_FIG), exist_ok=True)
    fig.savefig(OUT_FIG, dpi=150); print(f"wrote {OUT_FIG}")


def main() -> None:
    b = build()
    figure(b["overlap"])
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as fh:
        json.dump(b["res"], fh, indent=2)
    print(f"wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
