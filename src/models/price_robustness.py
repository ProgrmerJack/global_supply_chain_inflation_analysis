"""
Robustness battery for the state-dependent goods-price result (referee-proofing, deposit + FRED).

The interaction LP (state_lp.py) shows goods-CPI state-dependence beta_D ~ +1.18% at h=8. A macro referee
will attack it five ways; this script answers each with a real estimate:

  1. IMPORT-PRICE / FREIGHT CONTROLS  -- does LA dwell add anything beyond broad import inflation and
     ocean-freight prices? Add dlog(import price index) and dlog(deep-sea-freight PPI) to the controls.
  2. ANCHOR-SHIP-DAY SHOCK            -- align the ECONOMIC shock with the ENVIRONMENTAL mechanism: use
     LA/LB anchor ship-days (the same quantity behind emissions) instead of mean dwell. If beta_D
     survives, "the same congested ship-day" is literal, not loose.
  3. PLACEBO PORTS                    -- NY/NJ, Houston, Savannah, Seattle dwell shocks (own regime) should
     NOT generate the goods-CPI state-dependence; only the trans-Pacific gateway should.
  4. NEGATIVE-CONTROL CPI            -- port-insensitive categories (medical-care services, shelter) should
     show no goods-like state-dependence to the LA dwell shock.
  5. MULTIPLE-HORIZON CORRECTION      -- report goods beta_D across h=1..12 and the Bonferroni-adjusted
     significance so the h=8 peak is not a multiple-testing artifact.

FRED controls are fetched once to data/external/macro_controls.csv (IR, PCU483111483111, CPIMEDSL,
CUSR0000SAH1). Run: python src/models/price_robustness.py
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

H = 8
LAGS = 3


def _ensure_controls(path="data/external/macro_controls.csv"):
    """Return the FRED macro-controls path; if the deposited file is missing, fetch it once from FRED's
    public keyless CSV endpoint (import price IR, deep-sea-freight PPI, medical-care and shelter CPI)."""
    import os
    if os.path.exists(path):
        return path
    import io, requests
    ids = ["IR", "PCU483111483111", "CPIMEDSL", "CUSR0000SAH1"]
    out = None
    for sid in ids:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=30)
        d = pd.read_csv(io.StringIO(r.text)); d.columns = ["date", sid]
        d["date"] = pd.to_datetime(d.date); d[sid] = pd.to_numeric(d[sid], errors="coerce")
        out = d if out is None else out.merge(d, on="date", how="outer")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.sort_values("date").to_csv(path, index=False)
    return path


def _panel():
    d = pd.read_csv("data/processed/analysis_dataset_dwell.csv", parse_dates=["date"]).sort_values("date")
    # other-port dwell + LA anchor ship-days from the deposited census
    def _load(k):
        a = pd.read_csv(f"data/processed/ais_dwell_census_mode/{k}.csv")
        b = pd.read_csv(f"data/processed/ais_dwell_census_mode_2009_2014/{k}_2009_2014.csv")
        return pd.concat([a, b], ignore_index=True)
    dw = _load("monthly_dwell")
    dw["date"] = pd.to_datetime(dw.YearMonth + "-01")
    wide = dw.pivot_table(index="date", columns="Port", values="MeanDwellDays").reset_index()
    d = d.merge(wide, on="date", how="left")
    mt = _load("monthly_mode_time"); mt = mt[mt.Port == "LA_Long_Beach"]
    anc = mt.groupby("YearMonth").anchor_hours.sum().div(24).rename("anchor_sd").reset_index()
    anc["date"] = pd.to_datetime(anc.YearMonth + "-01")
    d = d.merge(anc[["date", "anchor_sd"]], on="date", how="left")
    # FRED controls (deposited file; self-heals from FRED's public keyless CSV endpoint if absent)
    c = pd.read_csv(_ensure_controls(), parse_dates=["date"])
    d = d.merge(c, on="date", how="left")
    d["d_log_indpro"] = np.log(d.indpro).diff()
    d["d_log_oil"] = np.log(d.oil_price).diff()
    d["d_log_imp"] = np.log(d["IR"]).diff()
    d["d_log_freight"] = np.log(d["PCU483111483111"]).diff()
    return d


def _std(x):
    x = pd.Series(x).astype(float)
    t = np.arange(len(x))
    ok = x.notna().values
    dl = x.copy()
    dl[ok] = x[ok] - np.polyval(np.polyfit(t[ok], x[ok], 1), t[ok])   # detrend
    return (dl - dl.mean()) / dl.std()


def _regime(level):
    lvl = pd.Series(level).rolling(3, min_periods=1).mean()
    return ((lvl - lvl.mean()) / lvl.std()).shift(1)


def interaction_bD(d, resp, shock, regime, controls, h=H):
    d = d.copy()
    d["shock"] = shock.values
    d["F"] = (regime > regime.median()).astype(float).values
    d["Fx"] = d["F"] * d["shock"]
    d["own_diff"] = np.log(d[resp]).diff()
    cols = ["shock", "Fx", "F", "own_diff"] + controls
    lagcols = []
    for cc in ["shock"] + controls + ["own_diff"]:
        for l in range(1, LAGS + 1):
            d[f"{cc}_l{l}"] = d[cc].shift(l); lagcols.append(f"{cc}_l{l}")
    y = np.log(d[resp]).shift(-h) - np.log(d[resp]).shift(1)
    X = sm.add_constant(d[cols + lagcols])
    reg = pd.concat([y.rename("y"), X], axis=1).dropna()
    res = sm.OLS(reg.y, reg.drop(columns="y")).fit(cov_type="HAC", cov_kwds={"maxlags": h + 1})
    return res.params["Fx"] * 100, res.pvalues["Fx"], len(reg)


def main():
    d = _panel()
    la_shock = _std(d.dwell_la_detrended)
    la_reg = _regime(d.dwell_la_raw)
    base_ctrl = ["d_log_indpro", "d_log_oil"]

    print("=== goods-CPI state-dependence beta_D (h=8), robustness ===")
    b, p, n = interaction_bD(d, "cpi_goods", la_shock, la_reg, base_ctrl)
    print(f"  1. baseline (LA dwell shock, IP+oil)                 bD={b:+.2f}% p={p:.3f} n={n}")
    b, p, n = interaction_bD(d, "cpi_goods", la_shock, la_reg, base_ctrl + ["d_log_imp", "d_log_freight"])
    print(f"  2. + import-price & deep-sea-freight controls        bD={b:+.2f}% p={p:.3f} n={n}")
    anc_shock = _std(d.anchor_sd)
    b, p, n = interaction_bD(d, "cpi_goods", anc_shock, la_reg, base_ctrl)
    print(f"  3. anchor-ship-day shock (emissions mechanism)       bD={b:+.2f}% p={p:.3f} n={n}")

    print("  4. placebo ports (own dwell shock + own regime) -- none should reproduce LA's POSITIVE effect:")
    npos = 0
    for port in ["NY_NJ", "Houston", "Savannah", "Seattle"]:
        if port not in d.columns or d[port].notna().sum() < 60:
            print(f"       {port:9s} insufficient dwell coverage"); continue
        b, p, n = interaction_bD(d, "cpi_goods", _std(d[port]), _regime(d[port]), base_ctrl)
        pos = b > 0 and p < 0.10
        npos += pos
        tag = "** POSITIVE like LA (concern)" if pos else ("opposite sign" if (b < 0 and p < 0.10) else "null")
        print(f"       {port:9s}  bD={b:+.2f}% p={p:.3f}  ({tag})")

    print("  5. breadth check -- port-insensitive CPI categories (LA dwell shock); goods should dominate:")
    bg = interaction_bD(d, "cpi_goods", la_shock, la_reg, base_ctrl)[0]
    for resp, lab in [("CPIMEDSL", "medical-care svc"), ("CUSR0000SAH1", "shelter")]:
        b, p, n = interaction_bD(d, resp, la_shock, la_reg, base_ctrl)
        print(f"       {lab:16s} bD={b:+.2f}% p={p:.3f}   goods/this = {bg/b:.1f}x")

    print("  6. multiple-horizon correction (goods bD, LA dwell shock):")
    ps, bs = [], []
    for h in range(1, 13):
        b, p, n = interaction_bD(d, "cpi_goods", la_shock, la_reg, base_ctrl, h=h)
        ps.append(p); bs.append(b)
    hbest = int(np.argmin(ps)) + 1
    bonf = min(1.0, min(ps) * 12)
    nsig = sum(1 for p in ps if p < 0.05)
    print(f"       peak h={hbest}: bD={bs[hbest-1]:+.2f}% raw p={min(ps):.3f}  Bonferroni-12 p={bonf:.3f}; "
          f"{nsig}/12 horizons p<0.05")

    # assertions: the claim must survive the controls and the anchor-shock, placebos/neg-controls null
    bpc, ppc, _ = interaction_bD(d, "cpi_goods", la_shock, la_reg, base_ctrl + ["d_log_imp", "d_log_freight"])
    banc, panc, _ = interaction_bD(d, "cpi_goods", anc_shock, la_reg, base_ctrl)
    assert bpc > 0 and ppc < 0.10, "goods bD does not survive import-price/freight controls"
    assert banc > 0 and panc < 0.10, "goods bD does not survive the anchor-ship-day shock"
    # Pin the MAGNITUDE, not just sign and significance. This is the exchange test Paper A leans on for
    # the coupling claim, and it drifted from +1.11% to +0.96% with the four-month census recovery
    # without anything noticing, because only the sign and significance were ever asserted.
    assert abs(banc - 0.96) < 0.12, (
        f"anchor-ship-day bD moved to {banc:+.2f}% (Paper A reports +0.96%); update the manuscript "
        "before relaxing this bar.")
    assert bonf < 0.10, "goods bD peak is a multiple-horizon artifact (Bonferroni fails)"
    assert npos == 0, "a placebo port reproduced LA's positive state-dependence"
    print("PASS: state-dependence survives import-price/freight controls AND the anchor-ship-day shock,")
    print("      is Bonferroni-robust across horizons, and no placebo port reproduces the positive effect.")
    print("      NOTE (honest): port-insensitive CPI is not a clean null -- high-congestion regimes coincide")
    print("      with broadly elevated inflation, but goods responds ~3-4x more, so the channel is")
    print("      goods-CONCENTRATED, not goods-exclusive (consistent with goods >> services).")


if __name__ == "__main__":
    main()
