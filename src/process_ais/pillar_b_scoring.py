"""Pillar-B scoring machinery — built BEFORE labels return (review Priority 2), tested on synthetic labels.

Operates on the labelled benchmark (one row per EPISODE, not ping):
  episode_id, gold (adjudicated), classifier_label, duration_hours (classifier), ref_duration_hours
  (annotator-marked true duration), regime, vessel_type, boundary_distance_m, annotator_1, annotator_2.
Produces: inter-annotator reliability, classification scorecard, DURATION-BIAS metrics (the emissions-critical
ones), episode-clustered bootstrap CIs, six predeclared pass/fail sub-gates, and a blind power check that
reports attainable CI width WITHOUT exposing classifier performance.

Frozen thresholds (docs/plan.md §5.3): motion macro-F1 >= 0.85 & CI-low >= 0.80; anchor/berth F1 >= 0.85 &
resolved coverage >= 0.90; anchorage & berth duration signed bias within +-10%.
Run: python src/process_ais/pillar_b_scoring.py   # synthetic self-check
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MOTION_F1_MIN, MOTION_CI_LOW_MIN = 0.85, 0.80
BA_F1_MIN, RESOLVED_MIN, DUR_BIAS_MAX = 0.85, 0.90, 0.10
STATES = ("moving", "berth", "anchor", "uncertain")
STATIONARY = ("berth", "anchor")


# --------------------------------------------------------------------------- inter-annotator reliability
def interrater_reliability(a: pd.Series, b: pd.Series) -> dict:
    a, b = a.astype(str).to_numpy(), b.astype(str).to_numpy()
    n = len(a)
    po = float((a == b).mean())
    cats = sorted(set(a) | set(b))
    k = len(cats)
    pe = sum(np.mean(a == c) * np.mean(b == c) for c in cats)
    kappa = 1.0 if pe == 1 else (po - pe) / (1 - pe)
    pabak = (k * po - 1) / (k - 1) if k > 1 else float("nan")          # prevalence-adjusted bias-adjusted
    per_class = {c: float(((a == c) != (b == c)).mean()) for c in cats}
    return {"n": n, "raw_agreement": round(po, 3), "cohen_kappa": round(kappa, 3),
            "pabak": round(pabak, 3), "per_class_disagreement": {c: round(v, 3) for c, v in per_class.items()}}


# --------------------------------------------------------------------------- classification scorecard
def _prf(gold, pred, lab):
    tp = int(((pred == lab) & (gold == lab)).sum()); fp = int(((pred == lab) & (gold != lab)).sum())
    fn = int(((pred != lab) & (gold == lab)).sum())
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if p and r and (p + r) else 0.0
    return p, r, f


def classification_scorecard(gold: np.ndarray, pred: np.ndarray, labels) -> dict:
    per = {lab: dict(zip(("precision", "recall", "f1"), _prf(gold, pred, lab))) for lab in labels}
    macro_f1 = float(np.mean([per[l]["f1"] for l in labels]))
    recalls = [per[l]["recall"] for l in labels if not np.isnan(per[l]["recall"])]
    bal_acc = float(np.mean(recalls)) if recalls else float("nan")
    conf = pd.crosstab(pd.Series(gold, name="gold"), pd.Series(pred, name="pred"))
    return {"macro_f1": round(macro_f1, 3), "balanced_accuracy": round(bal_acc, 3),
            "per_class": {l: {k: round(v, 3) for k, v in d.items()} for l, d in per.items()},
            "confusion": conf}


def resolved_coverage(gold: np.ndarray, pred: np.ndarray) -> float:
    """Among truly-stationary episodes, fraction the classifier resolves to berth/anchor (not unresolved)."""
    stat = np.isin(gold, STATIONARY)
    if not stat.any():
        return float("nan")
    return float(np.isin(pred[stat], STATIONARY).mean())


# --------------------------------------------------------------------------- DURATION-BIAS (emissions-critical)
def duration_bias(df: pd.DataFrame) -> dict:
    """Total STATE-HOUR bias per state = (classifier hours in s − true hours in s) / true hours in s.
    Captures misclassification AND duration error together (the thing that biases the emissions total)."""
    out = {}
    for s in STATIONARY + ("moving",):
        true_h = df.loc[df.gold == s, "ref_duration_hours"].sum()
        clf_h = df.loc[df.classifier_label == s, "duration_hours"].sum()
        out[f"{s}_hour_bias"] = float((clf_h - true_h) / true_h) if true_h else float("nan")
    # per-episode signed / absolute duration error (where gold state matches)
    matched = df[df.gold == df.classifier_label]
    err = (matched["duration_hours"] - matched["ref_duration_hours"])
    out["mean_signed_dur_err_h"] = round(float(err.mean()), 3) if len(matched) else float("nan")
    out["median_abs_dur_err_h"] = round(float(err.abs().median()), 3) if len(matched) else float("nan")
    return out


def emissions_propagated_bias(state_hour_bias: dict, rate_t_per_vhr=None) -> dict:
    """Propagate anchor/berth hour bias into CO2 (t) using per-vessel-hour hoteling rates."""
    rate = rate_t_per_vhr or {"anchor": 0.56, "berth": 0.62}      # t CO2/vessel-hr (from the LA/LB model)
    return {f"{s}_co2_bias_pct": round(100 * state_hour_bias.get(f"{s}_hour_bias", float("nan")), 1)
            for s in STATIONARY}


# --------------------------------------------------------------------------- episode-clustered bootstrap
def episode_bootstrap(df: pd.DataFrame, n: int = 10000, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    eids = df["episode_id"].to_numpy()
    idx_by = {e: np.where(eids == e)[0] for e in np.unique(eids)}    # here 1 row/episode, but general
    uniq = np.array(list(idx_by))
    f1s, ab_f1s, anc_bias, ber_bias = [], [], [], []
    for _ in range(n):
        pick = rng.choice(uniq, len(uniq), replace=True)
        rows = np.concatenate([idx_by[e] for e in pick])
        b = df.iloc[rows]
        gm = np.where(np.isin(b.gold, STATIONARY), "stationary", "moving")
        pm = np.where(np.isin(b.classifier_label, STATIONARY), "stationary", "moving")
        f1s.append(classification_scorecard(gm, pm, ("moving", "stationary"))["macro_f1"])
        st = b[np.isin(b.gold, STATIONARY)]
        if len(st):
            ab_f1s.append(classification_scorecard(st.gold.to_numpy(), st.classifier_label.to_numpy(), STATIONARY)["macro_f1"])
        db = duration_bias(b)
        anc_bias.append(db["anchor_hour_bias"]); ber_bias.append(db["berth_hour_bias"])
    ci = lambda x: (round(float(np.nanpercentile(x, 2.5)), 3), round(float(np.nanpercentile(x, 97.5)), 3))
    return {"motion_f1_ci": ci(f1s), "berth_anchor_f1_ci": ci(ab_f1s),
            "anchor_hour_bias_ci": ci(anc_bias), "berth_hour_bias_ci": ci(ber_bias)}


# --------------------------------------------------------------------------- blind power check
def power_check(df: pd.DataFrame) -> dict:
    """Class counts + attainable proportion-CI half-width at p=0.85, WITHOUT touching classifier labels."""
    counts = df["gold"].value_counts().to_dict()
    hw = {c: (round(1.96 * np.sqrt(0.85 * 0.15 / n), 3) if n else None) for c, n in counts.items()}
    sparse = [c for c, n in counts.items() if n < 20]
    return {"class_counts": counts, "ci_halfwidth_at_p0.85": hw,
            "sparse_classes_lt20": sparse, "expand_recommended": bool(sparse)}


# --------------------------------------------------------------------------- six predeclared sub-gates
def decide_pillar_b_full(sc: dict) -> dict:
    ok = lambda v, t: bool(np.isfinite(v) and v >= t)
    within = lambda v, t: bool(np.isfinite(v) and abs(v) <= t)
    gates = {
        "motion_classification": ok(sc["motion_f1"], MOTION_F1_MIN) and ok(sc["motion_f1_ci_low"], MOTION_CI_LOW_MIN),
        "anchor_vs_berth": ok(sc["berth_anchor_f1"], BA_F1_MIN),
        "resolved_coverage": ok(sc["resolved_coverage"], RESOLVED_MIN),
        "anchorage_duration_bias": within(sc["anchor_hour_bias"], DUR_BIAS_MAX),
        "berth_duration_bias": within(sc["berth_hour_bias"], DUR_BIAS_MAX),
        "policy_effect_robustness": bool(sc.get("policy_effect_robust", False)),
    }
    return {"sub_gates": gates, "overall_pass": all(gates.values()),
            "failed": [k for k, v in gates.items() if not v]}


ANNOTATOR_PACKET_FIELDS = ["episode_id", "vessel_id_hash", "regime", "start_utc", "end_utc", "duration_hours",
                           "port_zone", "trajectory_reference", "boundary_distance_m",
                           "annotator_1_label", "annotator_2_label", "adjudicated_label"]


def _self_check() -> None:
    rng = np.random.default_rng(7)
    n = 240
    gold = rng.choice(STATES[:3], n, p=[0.4, 0.3, 0.3])
    # a "good" classifier: 92% correct, small duration error
    clf = np.where(rng.random(n) < 0.92, gold, rng.choice(STATES[:3], n))
    ref_dur = rng.uniform(2, 30, n); dur = ref_dur * rng.uniform(0.97, 1.03, n)
    df = pd.DataFrame({"episode_id": [f"e{i}" for i in range(n)], "gold": gold, "classifier_label": clf,
                       "ref_duration_hours": ref_dur, "duration_hours": dur,
                       "annotator_1": gold, "annotator_2": np.where(rng.random(n) < 0.9, gold, rng.choice(STATES[:3], n))})
    ir = interrater_reliability(df.annotator_1, df.annotator_2)
    gm = np.where(np.isin(df.gold, STATIONARY), "stationary", "moving")
    pm = np.where(np.isin(df.classifier_label, STATIONARY), "stationary", "moving")
    scc = classification_scorecard(gm, pm, ("moving", "stationary"))
    st = df[np.isin(df.gold, STATIONARY)]
    ab = classification_scorecard(st.gold.to_numpy(), st.classifier_label.to_numpy(), STATIONARY)
    db = duration_bias(df); boot = episode_bootstrap(df, n=500)
    sc = {"motion_f1": scc["macro_f1"], "motion_f1_ci_low": boot["motion_f1_ci"][0],
          "berth_anchor_f1": ab["macro_f1"], "resolved_coverage": resolved_coverage(df.gold.to_numpy(), df.classifier_label.to_numpy()),
          "anchor_hour_bias": db["anchor_hour_bias"], "berth_hour_bias": db["berth_hour_bias"],
          "policy_effect_robust": True}
    dec = decide_pillar_b_full(sc)
    assert dec["overall_pass"], (sc, dec)
    # a duration-biased-but-high-F1 classifier must FAIL on duration even if F1 is fine
    bad = dict(sc, anchor_hour_bias=0.35)
    assert not decide_pillar_b_full(bad)["overall_pass"]
    assert "anchorage_duration_bias" in decide_pillar_b_full(bad)["failed"]
    print("interrater:", {k: ir[k] for k in ("raw_agreement", "cohen_kappa", "pabak")})
    print("motion F1:", scc["macro_f1"], "CI:", boot["motion_f1_ci"], "| berth/anchor F1:", ab["macro_f1"])
    print("duration bias:", {k: round(v, 3) for k, v in db.items() if isinstance(v, float)})
    print("power check:", power_check(df)["sparse_classes_lt20"], "sparse")
    print("sub-gates:", dec["sub_gates"])
    print("pillar_b_scoring self-check OK")


if __name__ == "__main__":
    _self_check()
