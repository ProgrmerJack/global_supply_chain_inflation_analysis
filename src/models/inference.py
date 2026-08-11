"""
Inference for the three headline results (referee-critical):
 1. LA dwell vs GSCPI correlation with autocorrelation-robust significance
    (moving-block bootstrap + Newey-West effective sample size).
 2. Local-projection goods/services IRF at h=8 WITH confidence bands (already estimated).
 3. Reform DiD with randomization inference: in-space placebos (each port as treated) and
    an in-time placebo (fake reform date), since n=5 units makes asymptotic SEs invalid.
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(0)


def block_bootstrap_corr(x, y, block=12, n=5000):
    x = np.asarray(x); y = np.asarray(y); T = len(x)
    r0 = np.corrcoef(x, y)[0, 1]
    nb = int(np.ceil(T / block))
    rs = []
    starts_all = T - block
    for _ in range(n):
        idx = np.concatenate([np.arange(s, s + block) for s in rng.integers(0, starts_all, nb)])[:T]
        rs.append(np.corrcoef(x[idx], y[idx])[0, 1])
    lo, hi = np.percentile(rs, [2.5, 97.5])
    p = 2 * min((np.array(rs) <= 0).mean(), (np.array(rs) >= 0).mean())
    return r0, lo, hi, p


def newey_west_eff_n(x, y):
    # effective sample size from AR(1) of each series: n_eff = n*(1-rx*ry)/(1+rx*ry)
    def ar1(z):
        z = np.asarray(z); return np.corrcoef(z[:-1], z[1:])[0, 1]
    rx, ry = ar1(x), ar1(y); n = len(x)
    return n * (1 - rx * ry) / (1 + rx * ry)


def corr_test():
    d = pd.read_csv("data/processed/analysis_dataset_dwell.csv").dropna(subset=["dwell_la_detrended", "gscpi"])
    x, y = d["dwell_la_detrended"].values, d["gscpi"].values
    r, lo, hi, p = block_bootstrap_corr(x, y)
    neff = newey_west_eff_n(x, y)
    # naive vs eff-df t
    from scipy import stats
    t_eff = r * np.sqrt((neff - 2) / (1 - r ** 2))
    p_eff = 2 * (1 - stats.t.cdf(abs(t_eff), df=neff - 2))
    print("=== 1. LA dwell vs GSCPI correlation (autocorrelation-robust) ===")
    print(f"  r = {r:.3f}  (n={len(x)});  block-bootstrap 95% CI [{lo:.3f}, {hi:.3f}]  p={p:.4f}")
    print(f"  Newey-West effective n = {neff:.0f};  eff-df p = {p_eff:.4f}")


def detrend_robustness():
    """Concentration r must not be an artifact of one detrending choice. Report r under linear detrend,
    HP-cycle, raw levels, and first differences. HP surviving => not a shared linear trend; first-diff
    vanishing => the comovement is a low-frequency/cycle relationship (both are persistent supply-stress
    states), which we DISCLOSE rather than hide."""
    import statsmodels.api as sm
    d = pd.read_csv("data/processed/analysis_dataset_dwell.csv").dropna(subset=["dwell_la_raw", "gscpi"])
    raw, g = d.dwell_la_raw.values, d.gscpi.values
    t = np.arange(len(raw))
    lin = raw - np.polyval(np.polyfit(t, raw, 1), t)
    cyc, _ = sm.tsa.filters.hpfilter(raw, lamb=129600)
    R = lambda x, y: np.corrcoef(x, y)[0, 1]
    print("\n=== 1b. Concentration r robustness to detrending (LA dwell vs GSCPI) ===")
    print(f"  raw levels        r={R(raw, g):+.3f}   linear-detrend r={R(lin, g):+.3f}   "
          f"HP-cycle r={R(cyc, g):+.3f}")
    print(f"  first-difference  r={R(np.diff(raw), np.diff(g)):+.3f}  "
          f"-> comovement is low-frequency/cycle, not high-frequency (disclosed)")
    # The original bar -- BOTH linear detrending and the HP cycle must clear 0.30 -- is in force.
    # Linear detrending tests "not a shared linear trend"; the HP cycle tests that the co-movement
    # survives at business-cycle frequency rather than living entirely in the trend.
    #
    # History (2026-08-05): this bar was briefly re-scoped to linear-only, because on the then-current
    # panel the HP cycle read 0.291. That panel's GSCPI was misaligned by one month -- the workbook is
    # month-end dated and was normalised with MonthBegin(0), which rolls forward (see
    # src/index/build_macro_panel.py). On the correctly aligned series linear is 0.499 and the HP cycle
    # is 0.350, so the original two-sided bar passes on its own terms and has been RESTORED. The lesson
    # is worth keeping: when a guard suddenly needs its scope narrowed, suspect the data before the bar.
    assert min(R(lin, g), R(cyc, g)) > 0.30, (
        f"concentration collapses under detrending -> was a shared trend "
        f"(linear {R(lin, g):+.3f}, HP-cycle {R(cyc, g):+.3f}; bar 0.30 on both)")
    assert R(cyc, g) > 0, (f"HP-cycle correlation changed sign ({R(cyc, g):+.3f}) -> the co-movement is "
                           "not merely attenuated at cycle frequency, it is absent or inverted")


def segmentation_crosscheck():
    """Port-call-segmentation robustness for the concentration result. Monthly dwell is first-to-last
    within a port-month and can lump multiple port calls; the mode-census anchor ship-days are
    interval-summed (gap-capped), so replacing dwell with anchor ship-days is a segmentation-robust
    alternative. If the GSCPI co-movement survives the swap, the concentration is not an artifact of the
    first-to-last dwell definition. Both series sourced from the deposit."""
    def _mode(k):
        a = pd.read_csv(f"data/processed/ais_dwell_census_mode/{k}.csv")
        b = pd.read_csv(f"data/processed/ais_dwell_census_mode_2009_2014/{k}_2009_2014.csv")
        return pd.concat([a, b], ignore_index=True)
    m = _mode("monthly_mode_time"); m = m[m.Port == "LA_Long_Beach"]
    anc = m.groupby("YearMonth").anchor_hours.sum().div(24).rename("anchor_sd").reset_index()
    anc["date"] = pd.to_datetime(anc.YearMonth + "-01")
    d = pd.read_csv("data/processed/analysis_dataset_dwell.csv", parse_dates=["date"])
    g = d[["date", "gscpi", "dwell_la_detrended"]].merge(anc[["date", "anchor_sd"]], on="date", how="inner") \
         .dropna(subset=["gscpi", "anchor_sd", "dwell_la_detrended"])
    detr = lambda x: x - np.polyval(np.polyfit(np.arange(len(x)), x, 1), np.arange(len(x)))
    r_dwell = np.corrcoef(g.dwell_la_detrended, g.gscpi)[0, 1]
    r_anchor = np.corrcoef(detr(g.anchor_sd.values), g.gscpi.values)[0, 1]
    print("\n=== 1c. Port-call-segmentation robustness (concentration) ===")
    print(f"  r(dwell, GSCPI) = {r_dwell:+.3f}   r(anchor ship-days, GSCPI) = {r_anchor:+.3f}  (n={len(g)})")
    print("  -> anchor-time (segmentation-robust) co-moves with GSCPI too; not a dwell-definition artifact")
    assert r_anchor > 0.3, "concentration collapses under the anchor-time (segmentation-robust) measure"


def concentration_difference():
    """Is LA/LB's GSCPI co-movement STATISTICALLY DIFFERENT from the other four ports'?

    The paper's word is "concentration": LA/LB co-moves and the others do not. Reporting
    r(LA) alongside four near-zero r's does not establish that — it shows one estimate clears
    significance and four do not, which is a different (and much weaker) statement. This
    function tests the difference itself.

    The five correlations all share the GSCPI, so they are DEPENDENT; an independent-samples
    Fisher z would be wrong here. Two tests are reported:

      * primary   -- a moving-block bootstrap (12-month blocks) on the DIFFERENCE r_LA - r_port,
                     resampling the same block indices across every series at once. This keeps
                     the cross-port dependence intact and, being a block bootstrap, is honest
                     about the heavy autocorrelation in both dwell and the GSCPI.
      * secondary -- Williams' test for two dependent correlations sharing one variable,
                     evaluated at the Newey-West EFFECTIVE n rather than the nominal n. At the
                     nominal n=201 the test would treat 201 highly autocorrelated months as 201
                     independent observations and overstate significance.
    """
    from scipy import stats

    ports = ["LA_Long_Beach", "NY_NJ", "Houston", "Savannah", "Seattle"]
    a = pd.read_csv("data/processed/ais_dwell_census/monthly_dwell.csv")
    b = pd.read_csv("data/processed/ais_dwell_census/monthly_dwell_2009_2014.csv")
    cen = pd.concat([a, b], ignore_index=True)
    wide = cen.pivot_table(index="YearMonth", columns="Port", values="MeanDwellDays")
    wide.index = pd.to_datetime(wide.index + "-01")

    panel = pd.read_csv("data/processed/analysis_dataset_dwell.csv", parse_dates=["date"])
    d = wide.join(panel.set_index("date")["gscpi"], how="inner").dropna(subset=["gscpi"] + ports)

    t = np.arange(len(d))
    detr = lambda v: v - np.polyval(np.polyfit(t, v, 1), t)
    X = {p: detr(d[p].values) for p in ports}
    g = d["gscpi"].values
    n = len(d)
    R = lambda x, y: np.corrcoef(x, y)[0, 1]
    r = {p: R(X[p], g) for p in ports}

    # joint moving-block bootstrap: one index draw applied to every series
    block, nboot = 12, 5000
    nb = int(np.ceil(n / block))
    diffs = {p: [] for p in ports[1:]}
    for _ in range(nboot):
        idx = np.concatenate([np.arange(s, s + block) for s in rng.integers(0, n - block, nb)])[:n]
        gb = g[idx]
        rla = R(X["LA_Long_Beach"][idx], gb)
        for p in ports[1:]:
            diffs[p].append(rla - R(X[p][idx], gb))

    neff = newey_west_eff_n(X["LA_Long_Beach"], g)
    print("\n=== 1d. Is the concentration DIFFERENCE significant? (LA/LB vs each other port) ===")
    print(f"  r(LA/LB) = {r['LA_Long_Beach']:+.3f}   n = {n}   Newey-West effective n = {neff:.0f}")
    worst_p = 0.0
    rows = []
    for p in ports[1:]:
        dd = np.array(diffs[p])
        lo, hi = np.percentile(dd, [2.5, 97.5])
        p_boot = 2 * min((dd <= 0).mean(), (dd >= 0).mean())
        # Williams' test at effective n
        r1, r2, r12 = r["LA_Long_Beach"], r[p], R(X["LA_Long_Beach"], X[p])
        ne = neff
        det = 1 - r1 ** 2 - r2 ** 2 - r12 ** 2 + 2 * r1 * r2 * r12
        rbar = (r1 + r2) / 2
        denom = 2 * ((ne - 1) / (ne - 3)) * det + rbar ** 2 * (1 - r12) ** 3
        tw = (r1 - r2) * np.sqrt(((ne - 1) * (1 + r12)) / denom)
        p_w = 2 * (1 - stats.t.cdf(abs(tw), df=ne - 3))
        worst_p = max(worst_p, p_boot)
        rows.append(dict(port=p, r_la=round(r1, 6), r_port=round(r2, 6), diff=round(r1 - r2, 6),
                         ci_lo=round(lo, 6), ci_hi=round(hi, 6), p_bootstrap=round(p_boot, 6),
                         p_williams_neff=round(p_w, 6), n=n, n_eff=round(ne, 2)))
        print(f"  vs {p:14s} r={r2:+.3f}  diff={r1 - r2:+.3f}  "
              f"bootstrap 95% CI [{lo:+.3f}, {hi:+.3f}] p={p_boot:.4f}  |  Williams p(n_eff)={p_w:.4f}")
    pd.DataFrame(rows).to_csv("outputs/concentration_difference.csv", index=False)

    # RESULT (2026-08-05): the strong form of this test FAILS, and Paper A was reworded rather
    # than the bar moved. Under the conservative block bootstrap LA/LB separates from Houston
    # (p=0.007) and Seattle (p=0.042) but NOT from NY/NJ (p=0.065) or Savannah (p=0.089).
    # Williams' test at effective n separates all four at or near 5%, but it is parametric and
    # the bootstrap is the honest primary here. With ~38 effective observations the differences
    # are large (+0.36 to +0.58) yet imprecisely estimated.
    #
    # So the guard asserts the proposition the paper now makes, which is weaker and true:
    #   (i)  every other port's correlation is small and not distinguishable from zero, and
    #   (ii) every pairwise difference is positive, and
    #   (iii) the largest contrast is individually significant.
    # It deliberately does NOT assert that all four differences are significant. If a future
    # revision wants the word "concentrates" back, this assertion is what must pass first.
    others = {p: r[p] for p in ports[1:]}
    assert max(abs(v) for v in others.values()) < 0.20, (
        f"a non-LA port now shows a non-trivial GSCPI correlation ({others}) — the "
        "'only LA/LB responds' framing no longer holds.")
    assert all(r["LA_Long_Beach"] - v > 0 for v in others.values()), (
        f"a non-LA port now out-correlates LA/LB ({others}).")
    best_p = min(2 * min((np.array(diffs[p]) <= 0).mean(), (np.array(diffs[p]) >= 0).mean())
                 for p in ports[1:])
    assert best_p < 0.05, (
        f"not even the strongest port contrast is significant (best bootstrap p = {best_p:.3f}); "
        "Paper A cannot claim a gateway-specific co-movement at all.")
    print(f"  -> supported: LA/LB is the only port with a non-trivial co-movement (others "
          f"|r| < 0.20) and every difference is positive; but only {sum(1 for p in ports[1:] if 2*min((np.array(diffs[p])<=0).mean(),(np.array(diffs[p])>=0).mean())<0.05)}/4 "
          f"contrasts are individually significant under the block bootstrap (largest p = {worst_p:.3f}).")
    print("     Paper A therefore says 'only LA/LB reaches significance', NOT 'the co-movement "
          "concentrates' — the difference test does not license the stronger word.")


def lp_bands():
    print("\n=== 2. Local-projection IRFs at h=8 (with 95% bands) ===")
    for name in ["goods", "services", "headline"]:
        r = pd.read_csv(f"outputs/irf_results_dwell_{name}.csv")
        row = r[r.h == 8].iloc[0]
        sig = "" if (row.lower <= 0 <= row.upper) else "  (excludes 0)"
        print(f"  {name:9s} h=8: {row.irf*100:+.2f}%  [{row.lower*100:+.2f}, {row.upper*100:+.2f}]{sig}")


def reform_did_inference():
    # DiD is on log ANCHORAGE ACTIVITY (anchor ship-days); emission intensity is a constant scalar that
    # cancels in a difference-in-differences, so we source directly from the deposited mode census
    # (not the superseded bottom-up emissions CSV) -> reproducible from the Zenodo deposit alone.
    def _mode(kind):
        a = pd.read_csv(f"data/processed/ais_dwell_census_mode/{kind}.csv")
        b = pd.read_csv(f"data/processed/ais_dwell_census_mode_2009_2014/{kind}_2009_2014.csv")
        return pd.concat([a, b], ignore_index=True)
    m = _mode("monthly_mode_time")
    em = m.groupby(["Port", "YearMonth"]).anchor_hours.sum().div(24).reset_index(name="ship_days")
    em["t"] = pd.to_datetime(em.YearMonth + "-01")
    em["logCO2"] = np.log(em["ship_days"].clip(lower=1))   # log anchorage activity (name kept for below)
    ports = ["LA_Long_Beach", "NY_NJ", "Houston", "Savannah", "Seattle"]

    def did(treated, ref):
        ref = pd.Timestamp(ref)
        win = em[(em.t >= ref - pd.DateOffset(months=12)) & (em.t < ref + pd.DateOffset(months=13))].copy()
        win["post"] = (win.t >= ref).astype(int)
        win["treat"] = (win.Port == treated).astype(int)
        g = win.groupby(["treat", "post"])["logCO2"].mean()
        return (g.loc[(1, 1)] - g.loc[(1, 0)]) - (g.loc[(0, 1)] - g.loc[(0, 0)])

    print("\n=== 3. Reform DiD randomization inference (n=5) ===")
    real = did("LA_Long_Beach", "2021-11")
    placebo_space = {p: did(p, "2021-11") for p in ports}
    order = sorted(placebo_space.items(), key=lambda kv: kv[1])
    rank = [p for p, _ in order].index("LA_Long_Beach") + 1
    print(f"  LA DiD = {real:+.3f} log ({(np.exp(real)-1)*100:+.0f}%)")
    print("  in-space placebo DiDs:", {p: round(v, 2) for p, v in placebo_space.items()})
    print(f"  LA rank among 5 ports = {rank}/5  -> randomization p = {rank/5:.2f} (n=5 floor is 0.20)")
    # in-time placebo: fake reform 2 yrs earlier at LA
    fake = did("LA_Long_Beach", "2019-11")
    print(f"  in-time placebo (fake reform 2019-11 at LA): DiD = {fake:+.3f} log ({(np.exp(fake)-1)*100:+.0f}%)")


if __name__ == "__main__":
    corr_test(); detrend_robustness(); segmentation_crosscheck(); concentration_difference()
    lp_bands(); reform_did_inference()
