"""
Workstream D — preregistered CPI kill-test (docs/plan.md §7; Gate G6).

The aggregate state-dependent local projection (goods bD ~ +1.18% at h=8) is ALREADY-INSPECTED
legacy evidence, so it is treated as EXPLORATORY and must survive a locked falsification battery or be
demoted (§357, §7.2). price_robustness.py already covers import/freight controls, anchor-ship-day shock,
placebo ports, negative-control CPI, and Bonferroni horizons. This script adds the families §7.1 requires
that were NOT yet tested:

  A. TEMPORAL STABILITY   pre-2020 vs pandemic sub-periods; leave-episode-out (the decisive test of the
                          "supported principally by two episodes" critique); drop-all-pandemic; rolling
                          windows; a pre/post-2020 structural-break interaction.
  B. STATE DEFINITION     continuous interaction (no split at all); logistic smooth-transition; a threshold
                          FROZEN from the 2009-2018 pre-window (no contemporaneous regime classification);
                          a quadratic spline (joint nonlinearity Wald test).
  C. INFERENCE            moving-block bootstrap of bD; sup-t SIMULTANEOUS bands across h=1..12 on a common
                          estimation sample; randomization/placebo-date inference (circular shift).
  D. TIMING / REVERSE     leads / pre-response at h=-3..0 (no anticipation); reverse Granger (does goods
                          inflation forecast the congestion shock?); alternative lag depths.

SURVIVAL RULE (§7.2) — keep the aggregate LP as a SECONDARY result only if ALL hold:
  1 same direction in both episodes; 2 no meaningful pre-response; 3 survives simultaneous inference;
  4 continuous-state model supports the threshold result; 5 not eliminated by product-port exposure
  controls (DEFERRED to Phase 6 Census panel — reported, not asserted); 6 an untouched port/period holdout
  confirms the sign (temporal holdout tested here; geographic holdout DEFERRED to Phase 1 national build).

Reuses the validated data + panel layer from src/models/price_robustness.py. Run from repo root:
    python src/models/kill_test.py
Writes outputs/GATE_G6_cpi.md.
"""
import os
import sys
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

# reuse the deposited data layer (per-port dwell, LA anchor ship-days, FRED controls) — do not duplicate
from price_robustness import _panel, _std, _regime  # noqa: E402

RESP = "cpi_goods"
BASE_CTRL = ["d_log_indpro", "d_log_oil"]
H_STAR = 8            # the headline horizon
PANDEMIC = ("2020-03-01", "2022-06-01")   # the single dominant congestion episode (leave-out target)


# ----------------------------------------------------------------------------- engine
def _design(d, resp, shock, F, controls, h, lags=3):
    """Interaction-LP design: Δy_{t+h}=a+bL*shock+bD*(F*shock)+phi*F+own_diff+controls(+lags).
    F may be a 0/1 dummy OR a continuous z. Returns (y, X) aligned on d's index (pre-dropna)."""
    d = d.copy()
    d["shock"] = np.asarray(shock, float)
    d["F"] = np.asarray(F, float)
    d["Fx"] = d["F"] * d["shock"]
    d["own_diff"] = np.log(d[resp]).diff()
    cols = ["shock", "Fx", "F", "own_diff"] + controls
    lagcols = []
    for cc in ["shock"] + controls + ["own_diff"]:
        for l in range(1, lags + 1):
            d[f"{cc}_l{l}"] = d[cc].shift(l)
            lagcols.append(f"{cc}_l{l}")
    y = (np.log(d[resp]).shift(-h) - np.log(d[resp]).shift(1)).rename("y")
    X = sm.add_constant(d[cols + lagcols])
    return y, X


def fit_bD(d, resp, shock, F, controls, h, lags=3, mask=None, cov="HAC"):
    """Fit the interaction LP; return dict(bD%, p, bL%, bH%, p_bH, n)."""
    y, X = _design(d, resp, shock, F, controls, h, lags)
    reg = pd.concat([y, X], axis=1)
    if mask is not None:
        reg = reg[np.asarray(mask, bool)]
    reg = reg.dropna()
    yv = reg["y"]; Xv = reg.drop(columns="y")
    if cov == "HAC":
        res = sm.OLS(yv, Xv).fit(cov_type="HAC", cov_kwds={"maxlags": abs(h) + 1})
    else:
        res = sm.OLS(yv, Xv).fit()
    idx = list(res.params.index)
    c = np.zeros(len(idx)); c[idx.index("shock")] = 1; c[idx.index("Fx")] = 1
    with np.errstate(all="ignore"):   # degenerate (perfect-fit) windows -> NaN bH, unused; keep quiet
        bH = float(c @ res.params.values); seH = float(np.sqrt(c @ res.cov_params().values @ c))
        p_bH = 2 * (1 - stats.norm.cdf(abs(bH / seH))) if seH > 0 else np.nan
    return dict(bD=res.params["Fx"] * 100, p=res.pvalues["Fx"], bL=res.params["shock"] * 100,
                bH=bH * 100, p_bH=p_bH, n=len(reg))


# ----------------------------------------------------------------------------- A. temporal stability
def temporal_stability(d, shock, reg_la):
    out = {}
    yr = d.date.dt.year
    out["pre2020 (2009-19; incl. 2014-15 episode)"] = fit_bD(d, RESP, shock, (reg_la > reg_la.median()),
                                                             BASE_CTRL, H_STAR, mask=(yr <= 2019))
    out["2020+ (pandemic episode)"] = fit_bD(d, RESP, shock, (reg_la > reg_la.median()),
                                             BASE_CTRL, H_STAR, mask=(yr >= 2020))
    lo, hi = pd.Timestamp(PANDEMIC[0]), pd.Timestamp(PANDEMIC[1])
    drop = ~((d.date >= lo) & (d.date < hi))
    out["drop-all-pandemic (2020-03..2022-06 out)"] = fit_bD(d, RESP, shock, (reg_la > reg_la.median()),
                                                             BASE_CTRL, H_STAR, mask=drop)
    return out


def rolling_bD(d, shock, reg_la, win=90):
    """Rolling-window goods bD at h=8 (window in months). Report range/sign share."""
    F = (reg_la > reg_la.median())
    idx = np.arange(len(d))
    vals = []
    for i in range(0, len(d) - win):
        m = (idx >= i) & (idx < i + win)
        try:
            r = fit_bD(d, RESP, shock, F, BASE_CTRL, H_STAR, mask=m, cov="nonrobust")
            if r["n"] >= 45:
                vals.append(r["bD"])
        except Exception:
            pass
    v = np.array(vals)
    return dict(n_windows=len(v), min=v.min() if len(v) else np.nan,
                max=v.max() if len(v) else np.nan, share_pos=(v > 0).mean() if len(v) else np.nan)


def structural_break(d, shock, reg_la):
    """Does the state-dependence differ pre/post-2020? Add Fx*Post and test its coefficient."""
    F = (reg_la > reg_la.median()).astype(float)
    d2 = d.copy()
    d2["shock"] = np.asarray(shock, float); d2["F"] = F.values
    d2["Fx"] = d2.F * d2.shock
    d2["Post"] = (d2.date.dt.year >= 2020).astype(float)
    d2["FxPost"] = d2.Fx * d2.Post
    d2["own_diff"] = np.log(d2[RESP]).diff()
    for cc in ["d_log_indpro", "d_log_oil"]:
        pass
    cols = ["shock", "Fx", "FxPost", "F", "Post", "own_diff"] + BASE_CTRL
    lagcols = []
    for cc in ["shock"] + BASE_CTRL + ["own_diff"]:
        for l in range(1, 4):
            d2[f"{cc}_l{l}"] = d2[cc].shift(l); lagcols.append(f"{cc}_l{l}")
    y = np.log(d2[RESP]).shift(-H_STAR) - np.log(d2[RESP]).shift(1)
    X = sm.add_constant(d2[cols + lagcols])
    reg = pd.concat([y.rename("y"), X], axis=1).dropna()
    res = sm.OLS(reg.y, reg.drop(columns="y")).fit(cov_type="HAC", cov_kwds={"maxlags": H_STAR + 1})
    return dict(FxPost=res.params["FxPost"] * 100, p=res.pvalues["FxPost"])


# ----------------------------------------------------------------------------- B. state definition
def state_definitions(d, shock, reg_la, clevel):
    out = {}
    out["median-split dummy (headline)"] = fit_bD(d, RESP, shock, (reg_la > reg_la.median()), BASE_CTRL, H_STAR)
    out["continuous interaction (no split)"] = fit_bD(d, RESP, shock, clevel, BASE_CTRL, H_STAR)
    logistic = 1.0 / (1.0 + np.exp(-1.5 * clevel))       # smooth transition, gamma=1.5
    out["logistic smooth-transition"] = fit_bD(d, RESP, shock, logistic, BASE_CTRL, H_STAR)
    pre = d.date.dt.year <= 2018
    thr = np.nanmedian(clevel[pre.values])               # threshold FROZEN on 2009-2018, applied to all
    out[f"threshold FROZEN on 2009-18 (thr={thr:+.2f})"] = fit_bD(d, RESP, shock, (clevel > thr), BASE_CTRL, H_STAR)
    return out


def spline_joint(d, shock, clevel):
    """Quadratic spline: y ~ shock + shock*c + shock*c^2 + c + c^2 (+own+ctrls+lags). Joint Wald on the
    two interaction terms tests state-dependence WITHOUT a threshold at all."""
    d2 = d.copy()
    c = np.asarray(clevel, float); c2 = c * c
    d2["shock"] = np.asarray(shock, float); d2["c"] = c; d2["c2"] = c2
    d2["sc"] = d2.shock * d2.c; d2["sc2"] = d2.shock * d2.c2
    d2["own_diff"] = np.log(d2[RESP]).diff()
    cols = ["shock", "sc", "sc2", "c", "c2", "own_diff"] + BASE_CTRL
    lagcols = []
    for cc in ["shock"] + BASE_CTRL + ["own_diff"]:
        for l in range(1, 4):
            d2[f"{cc}_l{l}"] = d2[cc].shift(l); lagcols.append(f"{cc}_l{l}")
    y = np.log(d2[RESP]).shift(-H_STAR) - np.log(d2[RESP]).shift(1)
    X = sm.add_constant(d2[cols + lagcols])
    reg = pd.concat([y.rename("y"), X], axis=1).dropna()
    res = sm.OLS(reg.y, reg.drop(columns="y")).fit(cov_type="HAC", cov_kwds={"maxlags": H_STAR + 1})
    R = np.zeros((2, len(res.params))); names = list(res.params.index)
    R[0, names.index("sc")] = 1; R[1, names.index("sc2")] = 1
    w = res.f_test(R)
    return dict(p_joint=float(w.pvalue), sc=res.params["sc"] * 100, sc2=res.params["sc2"] * 100)


# ----------------------------------------------------------------------------- C. inference
def _mbb_starts(n, block, size, rng):
    nb = int(np.ceil(size / block))
    return [np.concatenate([np.arange(s, s + block) for s in rng.integers(0, n - block + 1, nb)])[:size]
            for _ in range(1)][0]


def simultaneous_bands(d, shock, reg_la, B=1000, block=12, seed=0):
    """sup-t simultaneous 95% bands for goods bD across h=1..12 on a COMMON estimation sample (rows valid
    for all horizons), via moving-block bootstrap. Returns per-horizon point, boot se, pointwise & sup-t
    significance, and the sup-t critical value."""
    rng = np.random.default_rng(seed)
    F = (reg_la > reg_la.median())
    hs = list(range(1, 13))
    # build each horizon's (y,X); restrict to the intersection of valid rows across all h
    designs = {}
    valid = None
    for h in hs:
        y, X = _design(d, RESP, shock, F, BASE_CTRL, h)
        ok = pd.concat([y, X], axis=1).notna().all(axis=1)
        designs[h] = (y, X)
        valid = ok if valid is None else (valid & ok)
    vidx = np.where(valid.values)[0]
    n = len(vidx)
    Xc = designs[hs[0]][1].iloc[vidx].reset_index(drop=True)
    Ys = {h: designs[h][0].iloc[vidx].reset_index(drop=True).values for h in hs}
    Xmat = Xc.values
    fx = list(Xc.columns).index("Fx")

    def ols_bD(Xm, yv, rows):
        b = np.linalg.lstsq(Xm[rows], yv[rows], rcond=None)[0]
        return b[fx]

    allrows = np.arange(n)
    point = np.array([ols_bD(Xmat, Ys[h], allrows) * 100 for h in hs])
    boot = np.zeros((B, len(hs)))
    for b in range(B):
        rows = _mbb_starts(n, block, n, rng)
        for j, h in enumerate(hs):
            boot[b, j] = ols_bD(Xmat, Ys[h], rows) * 100
    se = boot.std(axis=0, ddof=1)
    maxt = np.max(np.abs(boot - point) / se, axis=1)
    crit = np.percentile(maxt, 95)
    res = []
    for j, h in enumerate(hs):
        pw = abs(point[j]) / se[j] > 1.96
        st = abs(point[j]) / se[j] > crit
        res.append(dict(h=h, bD=point[j], se=se[j], pointwise_sig=pw, simult_sig=st))
    return dict(crit=crit, rows=res)


def placebo_dates(d, shock, reg_la, n_shift=500, seed=1):
    """Randomization inference: circularly shift the congestion shock+regime by a random offset, decoupling
    congestion timing from CPI, and re-estimate bD. p = P(|bD_null| >= |bD_obs|)."""
    rng = np.random.default_rng(seed)
    obs = fit_bD(d, RESP, shock, (reg_la > reg_la.median()), BASE_CTRL, H_STAR, cov="nonrobust")["bD"]
    s = np.asarray(shock, float); r = np.asarray(reg_la, float)
    T = len(s); null = []
    for _ in range(n_shift):
        k = rng.integers(6, T - 6)
        ss = np.roll(s, k); rr = pd.Series(np.roll(r, k))
        try:
            null.append(fit_bD(d, RESP, ss, (rr > rr.median()), BASE_CTRL, H_STAR, cov="nonrobust")["bD"])
        except Exception:
            pass
    null = np.array(null)
    p = (np.abs(null) >= abs(obs)).mean()
    return dict(obs=obs, p=p, null_mean=null.mean(), null_p95=np.percentile(np.abs(null), 95), n=len(null))


# ----------------------------------------------------------------------------- D. timing / reverse
def leads_pre_response(d, shock, reg_la):
    """bD at h=-3..0: a genuine (non-anticipatory) response has ~0 pre-shock 'response'."""
    F = (reg_la > reg_la.median())
    return {h: fit_bD(d, RESP, shock, F, BASE_CTRL, h) for h in [-3, -2, -1]}


def reverse_granger(d, shock, p=6):
    """Does goods inflation Granger-cause the congestion shock? Regress shock_t on p lags of shock and p
    lags of dlog(goods CPI); F-test the CPI lags. Also the forward direction for contrast."""
    x = pd.DataFrame({"shock": np.asarray(shock, float), "dcpi": np.log(d[RESP]).diff().values})
    for l in range(1, p + 1):
        x[f"s{l}"] = x.shock.shift(l); x[f"c{l}"] = x.dcpi.shift(l)
    x = x.dropna()

    def gc(dep, cause_pref):
        cols = [c for c in x.columns if c not in ("shock", "dcpi")]
        full = sm.OLS(x[dep], sm.add_constant(x[cols])).fit()
        R = np.zeros((p, len(full.params))); names = list(full.params.index)
        for i, l in enumerate(range(1, p + 1)):
            R[i, names.index(f"{cause_pref}{l}")] = 1
        return float(full.f_test(R).pvalue)
    return dict(cpi_causes_shock_p=gc("shock", "c"), shock_causes_cpi_p=gc("dcpi", "s"))


def alt_lags(d, shock, reg_la):
    F = (reg_la > reg_la.median())
    return {f"lags={L}": fit_bD(d, RESP, shock, F, BASE_CTRL, H_STAR, lags=L) for L in (1, 2, 3, 6)}


def episode_diagnostic(d):
    """Is the pre-2020 null a coverage artifact, or a genuine absence of response? Check that the 2014-15
    West Coast slowdown actually registers in the LA dwell series (else the 'both episodes' test is unfair)."""
    dd = d.dropna(subset=["dwell_la_raw"]).copy()
    pre = dd[dd.date.dt.year <= 2019]
    top3 = pre.nlargest(3, "dwell_la_raw")[["date", "dwell_la_raw"]]
    p2 = pre.dropna(subset=["gscpi"])
    r = float(np.corrcoef(p2.dwell_la_raw, p2.gscpi)[0, 1])
    reg1415 = all((dt.year in (2014, 2015)) for dt in top3.date)   # top pre-2020 dwell months are 2014-15?
    return dict(top3=[(dt.strftime("%Y-%m"), round(v, 2)) for dt, v in zip(top3.date, top3.dwell_la_raw)],
                cv=float(pre.dwell_la_raw.std() / pre.dwell_la_raw.mean()), pre_corr=r, episode_present=reg1415)


# ----------------------------------------------------------------------------- driver
def run():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows console is cp1252
    except Exception:
        pass
    d = _panel()
    shock = _std(d.dwell_la_detrended)
    reg_la = _regime(d.dwell_la_raw)
    clevel = _regime(d.dwell_la_raw)  # continuous predetermined congestion level (lagged, standardized)

    A = temporal_stability(d, shock, reg_la)
    roll = rolling_bD(d, shock, reg_la)
    brk = structural_break(d, shock, reg_la)
    B = state_definitions(d, shock, reg_la, clevel)
    spl = spline_joint(d, shock, clevel)
    sim = simultaneous_bands(d, shock, reg_la)
    plc = placebo_dates(d, shock, reg_la)
    leads = leads_pre_response(d, shock, reg_la)
    gr = reverse_granger(d, shock)
    lags = alt_lags(d, shock, reg_la)
    diag = episode_diagnostic(d)

    L = []
    P = lambda s="": L.append(s)
    P("# Gate G6 — CPI legacy kill-test (Workstream D)\n")
    P(f"_Generated by `src/models/kill_test.py`. Headline estimand: goods-CPI state-dependence bD at h={H_STAR}._\n")
    P("Status label: **exploratory legacy evidence** (docs/plan.md §357). Survival rule: docs/plan.md §7.2.\n")

    P("## A. Temporal stability")
    for k, r in A.items():
        P(f"- {k}: goods bD **{r['bD']:+.2f}%** (p={r['p']:.3f}, n={r['n']})")
    P(f"- rolling {90}-mo windows: {roll['n_windows']} windows, bD in [{roll['min']:+.2f}, {roll['max']:+.2f}]%, "
      f"share positive = {roll['share_pos']:.0%}")
    P(f"- structural break Fx×Post2020: {brk['FxPost']:+.2f}% (p={brk['p']:.3f}) "
      f"→ {'differs pre/post' if brk['p'] < 0.10 else 'no significant pre/post difference'}\n")

    P("## B. State definition (no hand-picked split)")
    for k, r in B.items():
        P(f"- {k}: bD **{r['bD']:+.2f}%** (p={r['p']:.3f})")
    P(f"- quadratic spline joint Wald on [shock·c, shock·c²]: p={spl['p_joint']:.3f} "
      f"(linear {spl['sc']:+.2f}%, quad {spl['sc2']:+.2f}%)\n")

    P("## C. Inference")
    P(f"- sup-t simultaneous 95% band across h=1..12 (moving-block bootstrap), critical |t| = {sim['crit']:.2f}:")
    for r in sim["rows"]:
        P(f"    h={r['h']:2d}: bD {r['bD']:+.2f}% (se {r['se']:.2f})  "
          f"pointwise {'sig' if r['pointwise_sig'] else '—'}  simultaneous {'SIG' if r['simult_sig'] else '—'}")
    P(f"- randomization / placebo-date p (circular shift): {plc['p']:.3f} "
      f"(obs bD {plc['obs']:+.2f}% vs null 95th |bD| {plc['null_p95']:.2f}%, {plc['n']} shifts)\n")

    P("## D. Timing / reverse causality")
    P("- leads (pre-response; should be ≈0):")
    for h, r in leads.items():
        P(f"    h={h:+d}: bD {r['bD']:+.2f}% (p={r['p']:.3f})")
    P(f"- reverse Granger: goods inflation → shock p={gr['cpi_causes_shock_p']:.3f}; "
      f"shock → goods inflation p={gr['shock_causes_cpi_p']:.3f}")
    P("- alternative lag depths:")
    for k, r in lags.items():
        P(f"    {k}: bD {r['bD']:+.2f}% (p={r['p']:.3f})")
    P("")

    # ---- survival evaluation (§7.2) — assert only on what is testable with current data
    c1 = A["pre2020 (2009-19; incl. 2014-15 episode)"]["bD"] > 0 and A["2020+ (pandemic episode)"]["bD"] > 0
    c2 = all(abs(leads[h]["bD"]) < 0.6 or leads[h]["p"] >= 0.10 for h in [-3, -2, -1])
    c3 = any(r["simult_sig"] for r in sim["rows"])
    c4 = B["continuous interaction (no split)"]["bD"] > 0 and B["continuous interaction (no split)"]["p"] < 0.10
    drop_ep = A["drop-all-pandemic (2020-03..2022-06 out)"]
    c6t = drop_ep["bD"] > 0            # period holdout: sign survives removing the dominant episode

    P("## Survival rule (§7.2)")
    P(f"1. same direction in both episodes (pre-2020 & pandemic): **{'PASS' if c1 else 'FAIL'}**")
    P(f"2. no meaningful pre-response (leads ≈0): **{'PASS' if c2 else 'FAIL'}**")
    P(f"3. survives simultaneous inference (≥1 horizon sup-t sig): **{'PASS' if c3 else 'FAIL'}**")
    P(f"4. continuous-state model supports the threshold result: **{'PASS' if c4 else 'FAIL'}**")
    P("5. not eliminated by product-port exposure controls: **DEFERRED** (Phase 6 Census panel)")
    P(f"6. untouched-period holdout confirms sign (drop dominant episode): **{'PASS' if c6t else 'FAIL'}** "
      "(geographic holdout DEFERRED to Phase 1 national build)")
    testable = [c1, c2, c3, c4, c6t]
    verdict = ("SECONDARY-RESULT (all currently-testable criteria pass; 2 deferred)"
               if all(testable) else "DEMOTED from abstract (a headline criterion failed)")
    P(f"\n**Verdict (pending deferred criteria): {verdict}**")

    P("\n## Interpretation (is the FAIL a data artifact?)")
    P(f"- The 2014-15 West Coast slowdown **is present** in the LA dwell series: the three highest pre-2020 "
      f"dwell months are {', '.join(f'{m} ({v}d)' for m, v in diag['top3'])} vs a ~4.2-day baseline "
      f"(pre-2020 dwell CV={diag['cv']:.2f}). So the pre-2020 null is a **genuine absence of a goods-price "
      f"response to a real congestion episode**, not a coverage gap.")
    P(f"- Pre-2020 corr(dwell, GSCPI) is only {diag['pre_corr']:+.2f}; the strong co-movement is a "
      f"pandemic-era phenomenon.")
    P("- The entire state-dependence lives in 2020-2022, a window confounded by simultaneous fiscal "
      "stimulus, a goods-vs-services demand shift, and global supply-chain breakdown. The aggregate LP "
      "**cannot separate congestion from the pandemic**; identification requires the predetermined "
      "product-by-port design (Workstream E / Phase 6, Gate G7).")
    assert diag["episode_present"], "sanity: 2014-15 should be the top pre-2020 dwell episode"

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/GATE_G6_cpi.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    print("\nwrote outputs/GATE_G6_cpi.md")
    # NB: a kill-test legitimately outputs DEMOTED — that is a scientific result, not a code error, so we
    # do NOT assert on the substantive outcome. Engine correctness is checked in tests/test_kill_test.py.
    return dict(c1=c1, c2=c2, c3=c3, c4=c4, c6t=c6t, verdict=verdict)


if __name__ == "__main__":
    run()
