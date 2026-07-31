"""Paper A display items 1 and 2, built from the deposited five-port dwell/mode census.

Figures 3 and 4 and Supplementary Figure S1 are byproducts of the analyses that verify them and live
with that code (``process_ais/port_map.py``, ``models/state_lp.py``, ``emissions/reform_event_study.py``).

Run: python src/emissions/paper_a_figures.py
"""
import os
import sys

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from figsave import save_figure  # noqa: E402

OUT = "manuscript/paper_A_CEE/figures"
PORTS = ["LA_Long_Beach", "NY_NJ", "Houston", "Savannah", "Seattle"]


def load(kind):
    a = pd.read_csv(f"data/processed/ais_dwell_census_mode/{kind}.csv")
    b = pd.read_csv(f"data/processed/ais_dwell_census_mode_2009_2014/{kind}_2009_2014.csv")
    return pd.concat([a, b], ignore_index=True)


def fig_census():
    """Figure 1. Left: the 5-port dwell census (the two-crises internal-validity check). Right: LA/LB
    dwell against the NY Fed GSCPI, the concentration Paper A leads on. Deliberately distinct from the
    Paper B descriptor panels so the two submissions share no identical display item."""
    d = load("monthly_dwell"); d["t"] = pd.to_datetime(d.YearMonth + "-01")
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 4.6))
    for p in PORTS:
        s = d[d.Port == p].sort_values("t")
        axL.plot(s.t, s.MeanDwellDays, lw=1.6 if p == "LA_Long_Beach" else 0.9,
                 alpha=1 if p == "LA_Long_Beach" else 0.55, label=p.replace("_", "/"))
    for x, lab in [("2015-02", "2014–15 ILWU"), ("2021-10", "2021–22 surge")]:
        axL.axvspan(pd.Timestamp(x) - pd.DateOffset(months=2), pd.Timestamp(x) + pd.DateOffset(months=2),
                    color="grey", alpha=0.15)
        axL.annotate(lab, (pd.Timestamp(x), 0.3), ha="center", va="bottom", fontsize=8)
    axL.set_ylabel("mean vessel dwell (days)"); axL.legend(fontsize=8, ncol=2, loc="upper left")
    axL.set_title("a  17-year dwell census: two independent crises")

    m = pd.read_csv("data/processed/analysis_dataset_dwell.csv", parse_dates=["date"]).sort_values("date")
    axR.plot(m.date, m.dwell_la_raw, color="#d62728", lw=1.6, label="LA/LB dwell (days)")
    axR.set_ylabel("LA/LB mean dwell (days)", color="#d62728"); axR.tick_params(axis="y", colors="#d62728")
    ax2 = axR.twinx()
    ax2.plot(m.date, m.gscpi, color="#1f77b4", lw=1.2, alpha=0.8, label="NY Fed GSCPI")
    ax2.set_ylabel("GSCPI (SD)", color="#1f77b4"); ax2.tick_params(axis="y", colors="#1f77b4")
    # r is computed from the panel, never hardcoded: a stale literal in a figure title is exactly how a
    # superseded number outlives the data it came from.
    ov = m.dropna(subset=["dwell_la_detrended", "gscpi"])
    r = ov.dwell_la_detrended.corr(ov.gscpi)
    axR.set_title(f"b  Gateway co-movement: LA/LB dwell vs GSCPI (r = {r:.2f})")
    fig.tight_layout()
    save_figure(fig, f"{OUT}/paperA_census.png")


def fig_emissions():
    """Figure 2. LEFT (primary): anchorage CO2 as relative change vs the 2016-2019 baseline — intensity
    cancels, two crises visible. RIGHT (secondary, method-exposed): absolute annual CO2 with the
    method-dependent band; the CARB central intensity (54) and the Vukic & Lai empirical point (24) both
    sit inside the [24,69] band (the reefer spread)."""
    e = pd.read_csv("outputs/emissions_carb_calibrated_LALB_anchor.csv")
    a = e.groupby("yr").agg(lo=("anchor_CO2_t_lo", "sum"), mid=("anchor_CO2_t_mid", "sum"),
                            hi=("anchor_CO2_t_hi", "sum"))
    base = a.loc[2016:2019, "mid"].mean()   # pre-pandemic non-crisis baseline (excludes 2014-15 ILWU)
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 4.8))

    axL.plot(a.index, a.mid / base, marker="o", ms=4, color="#d62728", lw=2)
    axL.axhline(1.0, color="grey", lw=0.8, ls=":")
    for x, lab in [(2015, "2014–15 ILWU"), (2021, "2021–22 surge")]:
        axL.axvspan(x - 0.4, x + 0.4, color="grey", alpha=0.15)
    axL.annotate(f"{a.loc[2021,'mid']/base:.1f}×", (2021, a.loc[2021, "mid"] / base),
                 textcoords="offset points", xytext=(6, -2), fontsize=10, weight="bold")
    axL.set_ylabel("anchorage CO₂ ÷ 2016–19 baseline (×)")
    axL.set_title("Primary: relative change (intensity cancels — robust)")

    axR.fill_between(a.index, a.lo / 1e3, a.hi / 1e3, color="#1f77b4", alpha=0.2, label="method band [24–69 t/ship-day]")
    axR.plot(a.index, a.mid / 1e3, marker="o", ms=3, color="#1f77b4", lw=1.6, label="CARB-central (54)")
    axR.plot(a.index, a.mid / 1e3 * 24 / 54.3, color="#1f77b4", lw=1.0, ls="--", label="Vukić & Lai intensity (24)")
    axR.set_ylabel("absolute anchorage CO₂ (kt/yr)")
    axR.set_title("Secondary: absolute tonnage (method-dependent — report as banded)")
    axR.legend(fontsize=7.5, loc="upper left")
    for ax in (axL, axR):
        ax.set_xlim(2008.5, 2025.5)
    fig.tight_layout()
    save_figure(fig, f"{OUT}/paperA_emissions.png")


if __name__ == "__main__":
    fig_census(); fig_emissions()
    print(f"wrote {OUT}/paperA_census.png and {OUT}/paperA_emissions.png (+ vector PDFs)")
