"""
Nov-2021 LA/LB vessel-queuing reform: DiD + event study on anchorage emissions.

Treated = LA_Long_Beach; controls = the other 4 ports. Outcome = monthly anchor CO2
(and anchor ship-days), log-scaled. We estimate:
  (1) DiD: (LA post-pre) - (controls post-pre) around Nov-2021, windows +/-12 months.
  (2) Event study: LA minus mean(control), indexed to Oct-2021, by month.
HONEST CAVEAT: the reform instructed some vessels to remain offshore, but the registered aggregate
measurement gate did not validate a contemporaneous operational relocation series. A decline here measures
reduced NEAR-PORT anchoring only; it cannot separate clearance, offshore change or network diversion and is
confounded with the 2022 demand-surge unwinding.
"""
import os
import numpy as np
import pandas as pd
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from figsave import save_figure  # noqa: E402

REFORM = "2021-11"
CONTROLS = ["NY_NJ", "Houston", "Savannah", "Seattle"]


def _anchor_shipdays():
    # deposited mode census -> per-port monthly anchor ship-days (DiD is on log activity; intensity
    # cancels, so this is the correct deposit-native source, NOT the superseded bottom-up emissions CSV).
    def m(k):
        a = pd.read_csv(f"data/processed/ais_dwell_census_mode/{k}.csv")
        b = pd.read_csv(f"data/processed/ais_dwell_census_mode_2009_2014/{k}_2009_2014.csv")
        return pd.concat([a, b], ignore_index=True)
    g = m("monthly_mode_time").groupby(["Port", "YearMonth"]).anchor_hours.sum().div(24)
    return g.reset_index(name="anchor_CO2")   # name kept; it is anchor ship-days (∝ emissions)


def main():
    df = _anchor_shipdays()
    df["t"] = pd.to_datetime(df.YearMonth + "-01")
    df["logCO2"] = np.log(df["anchor_CO2"].clip(lower=1))
    ref = pd.Timestamp(REFORM + "-01")

    # --- DiD, +/-12 months ---
    win = df[(df.t >= ref - pd.DateOffset(months=12)) & (df.t < ref + pd.DateOffset(months=13))].copy()
    win["post"] = (win.t >= ref).astype(int)
    win["treat"] = (win.Port == "LA_Long_Beach").astype(int)
    g = win.groupby(["treat", "post"])["logCO2"].mean()
    did = (g.loc[(1, 1)] - g.loc[(1, 0)]) - (g.loc[(0, 1)] - g.loc[(0, 0)])
    print("=== DiD on log anchor CO2 (+/-12 mo around Nov-2021) ===")
    print(f"  LA change:      {g.loc[(1,1)]-g.loc[(1,0)]:+.3f} log ({(np.exp(g.loc[(1,1)]-g.loc[(1,0)])-1)*100:+.0f}%)")
    print(f"  control change: {g.loc[(0,1)]-g.loc[(0,0)]:+.3f} log ({(np.exp(g.loc[(0,1)]-g.loc[(0,0)])-1)*100:+.0f}%)")
    print(f"  DiD:            {did:+.3f} log  ({(np.exp(did)-1)*100:+.0f}% LA vs controls)")

    # --- event study: LA minus mean(control) log, indexed to Oct-2021 ---
    la = df[df.Port == "LA_Long_Beach"].set_index("YearMonth")["logCO2"]
    ctl = df[df.Port.isin(CONTROLS)].groupby("YearMonth")["logCO2"].mean()
    rel = (la - ctl).dropna()
    base = rel.get("2021-10", rel.mean())
    rel = rel - base
    months = pd.date_range("2020-06-01", "2022-12-01", freq="MS").strftime("%Y-%m")
    es = rel.reindex(months).dropna()
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(pd.to_datetime(es.index + "-01"), (np.exp(es) - 1) * 100, marker="o", lw=1.5)
    ax.axvline(ref, color="r", ls="--", label="Nov-2021 queuing reform")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_ylabel("LA anchor CO2 vs controls (%, rel. Oct-2021)")
    ax.set_title("Near-port anchorage emissions around the LA/LB queuing reform (DiD-style)")
    ax.legend(); fig.tight_layout()
    out = "manuscript/paper_A_CEE/figures/paperA_reform_event_study.png"
    save_figure(fig, out, close=False)
    print(f"\nwrote {out}")
    print("post-reform near-port anchorage (LA vs controls) by month, % vs Oct-2021:")
    for ym in ["2021-10", "2021-12", "2022-02", "2022-04", "2022-06", "2022-09"]:
        if ym in rel.index:
            print(f"  {ym}: {(np.exp(rel[ym])-1)*100:+.0f}%")


if __name__ == "__main__":
    main()
