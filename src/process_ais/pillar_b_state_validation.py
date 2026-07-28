"""Pillar B — episode-level, blinded, duration-aware state validation (G1-v2).

Rebuilds the state benchmark that FAILED at ping level (registered motion macro-F1 = 0.7289). Per
`prereg/studies/g1_v2/G1v2_operational_validation_protocol.md` (FROZEN 2026-07-15) and `docs/plan.md §5.2-5.3`:

  * the validation unit is the OPERATIONAL EPISODE (call-hour), NOT the raw ping — raw-ping scores
    overweight long densely-sampled episodes and hide duration bias;
  * two blinded annotators label each sampled episode moving / berth / anchor / uncertain with the
    classifier prediction HIDDEN, then adjudicate; inter-rater agreement is reported;
  * scoring: episode macro-F1 (moving/stationary) + bootstrap lower CI; berth/anchor F1 + resolved
    coverage; anchorage & berth duration signed bias;
  * `decide_pillar_b` applies the FROZEN §5.3 thresholds and is not adjustable toward 0.729.

This module BUILDS the harness (episode reconstruction, stratified sampling, blinded bundle, adjudication,
scorer, decision). Human labels are collected separately; `decide_pillar_b` is the run-once gate.

Reuses `port_call_segmentation.assign_port_call_ids` (call segmentation) and the `mode_time` SOG thresholds
(single-sourced). No downloads.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:  # flat load (src/process_ais on path) or package load (src on path)
    from port_call_segmentation import assign_port_call_ids
    from mode_time import HOTELING_SOG_KN, MANOEUVRE_SOG_KN
except ImportError:  # pragma: no cover - path shim mirrors the rest of the pipeline
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[1]))
    sys.path.insert(0, str(_here.parent))
    from port_call_segmentation import assign_port_call_ids
    from mode_time import HOTELING_SOG_KN, MANOEUVRE_SOG_KN

# Frozen §5.3 Pillar-B thresholds (mirror the protocol; do NOT tune toward the 0.729 failure).
MOTION_MACRO_F1_MIN = 0.85
MOTION_F1_CI_LOW_MIN = 0.80
BERTH_ANCHOR_F1_MIN = 0.85
RESOLVED_COVERAGE_MIN = 0.90
DURATION_BIAS_MAX = 0.10

EPISODE_STATES = ("moving", "stationary")
STATIONARY_SUBSTATES = ("berth", "anchor")
LABEL_CHOICES = ("moving", "manoeuvre", "berth", "anchor", "uncertain")
_REQUIRED_PING_COLUMNS = {"mmsi", "timestamp", "lon", "lat", "sog", "vessel_type", "port_complex_id"}


# --------------------------------------------------------------------------- episode reconstruction
def load_state_zones(path: str | Path, port: str | None = None) -> "pd.DataFrame":
    """Load berth/anchor polygons tolerantly from the mode-zone or NOAA-anchorage geojson."""
    import geopandas as gpd

    zones = gpd.read_file(path).to_crs("EPSG:4326")
    if "zone_type" in zones.columns:
        zones["zone_type"] = zones["zone_type"].astype(str).str.lower()
    elif "anchoragetype" in zones.columns:      # NOAA anchorages are all 'anchor'
        zones["zone_type"] = "anchor"
    else:
        raise ValueError("state zone file needs a 'zone_type' or 'anchoragetype' column")
    if port is not None:
        port_column = next((c for c in ("port_complex_id", "complex_id", "Port") if c in zones.columns), None)
        if port_column is not None:
            zones = zones.loc[zones[port_column].astype(str) == port]
    zones = zones.loc[zones["zone_type"].isin(STATIONARY_SUBSTATES), ["zone_type", "geometry"]]
    return zones.reset_index(drop=True)


def _substate_by_zone(stationary: pd.DataFrame, zones) -> pd.Series:
    """Point-in-polygon berth/anchor label for stationary pings (else 'unresolved')."""
    import geopandas as gpd

    if zones is None or not len(zones) or not len(stationary):
        return pd.Series("unresolved", index=stationary.index)
    pts = gpd.GeoDataFrame(
        stationary[["lon", "lat"]].copy(),
        geometry=gpd.points_from_xy(stationary["lon"], stationary["lat"]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(pts, zones[["zone_type", "geometry"]], how="left", predicate="within")
    # berth wins over anchor if a ping falls in both (overlapping charts)
    joined["_priority"] = joined["zone_type"].map({"berth": 0, "anchor": 1}).fillna(99)
    zone_type = joined.sort_values("_priority").groupby(level=0)["zone_type"].first()
    return zone_type.reindex(stationary.index).fillna("unresolved")


def reconstruct_episodes(pings: pd.DataFrame, zones=None, gap_hours: float = 24.0) -> pd.DataFrame:
    """Collapse a complex's pings into operational EPISODES (maximal same-coarse-state runs within a call).

    coarse_state = moving iff SOG >= HOTELING_SOG_KN (0.5 kn) else stationary; stationary substate = the
    majority berth/anchor zone of the episode's pings (else 'unresolved'). Episode duration = last-first
    ping time within the run.
    """
    if missing := _REQUIRED_PING_COLUMNS - set(pings.columns):
        raise ValueError(f"pings missing columns: {sorted(missing)}")
    df = pings.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["sog"] = pd.to_numeric(df["sog"], errors="coerce")
    df = df.dropna(subset=["timestamp", "mmsi", "port_complex_id"]).reset_index(drop=True)

    df = assign_port_call_ids(df, gap_hours=gap_hours)
    df["coarse_state"] = np.where(df["sog"].ge(HOTELING_SOG_KN), "moving", "stationary")
    df["ping_substate"] = "n/a"
    stationary = df.loc[df["coarse_state"].eq("stationary")]
    if len(stationary):
        df.loc[stationary.index, "ping_substate"] = _substate_by_zone(stationary, zones).values

    df = df.sort_values(["call_id", "timestamp"], kind="stable")
    # new episode when the coarse_state changes within a call
    new_ep = (df["coarse_state"].ne(df.groupby("call_id")["coarse_state"].shift())
              | df["call_id"].ne(df["call_id"].shift()))
    df["episode_idx"] = new_ep.groupby(df["call_id"]).cumsum()
    df["episode_id"] = df["call_id"] + "|e" + df["episode_idx"].astype(str)

    def _agg(g: pd.DataFrame) -> pd.Series:
        coarse = g["coarse_state"].iloc[0]
        sub = "n/a"
        if coarse == "stationary":
            counts = g.loc[g["ping_substate"].isin(STATIONARY_SUBSTATES), "ping_substate"].value_counts()
            sub = counts.index[0] if len(counts) else "unresolved"
        return pd.Series({
            "port_complex_id": g["port_complex_id"].iloc[0],
            "mmsi": g["mmsi"].iloc[0],
            "vessel_type": g["vessel_type"].iloc[0],
            "call_id": g["call_id"].iloc[0],
            "year": g["timestamp"].dt.year.iloc[0],
            "t_start": g["timestamp"].min(),
            "t_end": g["timestamp"].max(),
            "duration_h": (g["timestamp"].max() - g["timestamp"].min()).total_seconds() / 3600.0,
            "n_pings": len(g),
            "median_sog": g["sog"].median(),
            "max_sog": g["sog"].max(),
            "coarse_state": coarse,
            "substate": sub,
        })

    episodes = df.groupby("episode_id", sort=False).apply(_agg, include_groups=False).reset_index()
    return episodes


# --------------------------------------------------------------------------- blinded sampling + bundle
def stratified_episode_sample(episodes: pd.DataFrame, per_stratum: int = 5, seed: int = 0) -> pd.DataFrame:
    """Blinded-annotation sample stratified by gateway x vessel-type x year x easy/ambiguous.

    'ambiguous' = median SOG near the 0.5-kn moving/stationary cut, OR a stationary episode the classifier
    could not resolve to berth/anchor. Ambiguous cases are drawn deliberately (plan §5.2 'easy and
    ambiguous cases').
    """
    ep = episodes.copy()
    ep["vt_bucket"] = np.where(ep["vessel_type"].between(70, 79), "cargo",
                       np.where(ep["vessel_type"].between(80, 89), "tanker", "other"))
    near_cut = ep["median_sog"].between(0.3, 0.8)
    unresolved = ep["coarse_state"].eq("stationary") & ep["substate"].eq("unresolved")
    ep["ambiguous"] = (near_cut | unresolved).fillna(False)
    keys = ["port_complex_id", "vt_bucket", "year", "ambiguous"]
    # deterministic shuffle, then take up to per_stratum per stratum (== min(per_stratum, len), no apply)
    return (ep.sample(frac=1.0, random_state=seed)
              .groupby(keys, sort=False, group_keys=False).head(per_stratum)
              .reset_index(drop=True))


_BLINDED_FEATURES = ["episode_id", "port_complex_id", "vessel_type", "year", "t_start", "t_end",
                     "duration_h", "n_pings", "median_sog", "max_sog"]
_KEY_COLUMNS = ["episode_id", "coarse_state", "substate", "duration_h"]


def write_blinded_annotation_bundle(sample: pd.DataFrame, out_dir: str | Path) -> dict[str, Path]:
    """Write the blinded template (NO classifier prediction) + a sequestered prediction key."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    template = sample[_BLINDED_FEATURES].copy()
    for col in ("annotator_1_label", "annotator_2_label", "adjudicated_label",
                "annotator_1_start_utc", "annotator_1_end_utc",
                "annotator_2_start_utc", "annotator_2_end_utc",
                "adjudicated_start_utc", "adjudicated_end_utc"):
        template[col] = ""                        # in: moving | berth | anchor | uncertain
    tpath = out / "annotation_template.csv"
    kpath = out / "prediction_key.csv"             # sequester from annotators
    template.to_csv(tpath, index=False, lineterminator="\n")
    sample[_KEY_COLUMNS].to_csv(kpath, index=False, lineterminator="\n")
    return {"template": tpath, "prediction_key": kpath}


# --------------------------------------------------------------------------- adjudication + scoring
def cohen_kappa(a: pd.Series, b: pd.Series) -> float:
    """Cohen's kappa for two blinded annotators (categorical labels)."""
    a, b = pd.Series(list(a)).astype(str), pd.Series(list(b)).astype(str)
    n = len(a)
    if n == 0:
        return float("nan")
    po = float((a.values == b.values).mean())
    cats = sorted(set(a) | set(b))
    pe = sum((a.eq(c).mean()) * (b.eq(c).mean()) for c in cats)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def adjudicate(labeled: pd.DataFrame) -> pd.DataFrame:
    """Gold label plus adjudicated duration; old A/B column names remain readable for audit files."""
    a_col = "annotator_1_label" if "annotator_1_label" in labeled else "annotator_A_label"
    b_col = "annotator_2_label" if "annotator_2_label" in labeled else "annotator_B_label"
    a, b = labeled[a_col].astype(str), labeled[b_col].astype(str)
    adj = labeled.get("adjudicated_label", pd.Series([""] * len(labeled))).astype(str)
    gold = np.where(a == b, a, np.where(adj.str.len() > 0, adj, "uncertain"))
    out = labeled[["episode_id"]].copy()
    out["gold"] = gold
    starts = labeled.get("adjudicated_start_utc", labeled.get("ref_start", pd.Series([""] * len(labeled))))
    ends = labeled.get("adjudicated_end_utc", labeled.get("ref_end", pd.Series([""] * len(labeled))))
    starts, ends = pd.to_datetime(starts, utc=True, errors="coerce"), pd.to_datetime(ends, utc=True, errors="coerce")
    out["ref_duration_h"] = (ends - starts).dt.total_seconds() / 3600.0
    return out


def _macro_f1(y_true: np.ndarray, y_pred: np.ndarray, labels) -> float:
    f1s = []
    for lab in labels:
        tp = int(((y_pred == lab) & (y_true == lab)).sum())
        fp = int(((y_pred == lab) & (y_true != lab)).sum())
        fn = int(((y_pred != lab) & (y_true == lab)).sum())
        denom = 2 * tp + fp + fn
        f1s.append(1.0 if denom == 0 else 2 * tp / denom)
    return float(np.mean(f1s)) if f1s else float("nan")


def score_state(episodes: pd.DataFrame, gold: pd.DataFrame, *, n_boot: int = 2000, seed: int = 0) -> dict:
    """Score classifier episodes against adjudicated gold labels (episode-level)."""
    m = episodes.merge(gold, on="episode_id", how="inner")
    m = m.loc[m["gold"].ne("uncertain")].reset_index(drop=True)      # exclude uncertain from primary metrics
    if not len(m):
        raise ValueError("no adjudicated (non-uncertain) episodes to score")

    gold_coarse = np.where(m["gold"].isin(STATIONARY_SUBSTATES), "stationary", "moving")
    pred_coarse = m["coarse_state"].to_numpy()
    macro_f1 = _macro_f1(gold_coarse, pred_coarse, EPISODE_STATES)

    rng = np.random.default_rng(seed)
    idx = np.arange(len(m))
    boot = [_macro_f1(gold_coarse[s := rng.choice(idx, len(idx), replace=True)], pred_coarse[s], EPISODE_STATES)
            for _ in range(n_boot)]
    f1_ci_low = float(np.percentile(boot, 2.5))

    stat = m.loc[m["gold"].isin(STATIONARY_SUBSTATES)]
    if len(stat):
        ba_f1 = _macro_f1(stat["gold"].to_numpy(), stat["substate"].to_numpy(), STATIONARY_SUBSTATES)
        resolved_coverage = float(stat["substate"].isin(STATIONARY_SUBSTATES).mean())
    else:
        ba_f1, resolved_coverage = float("nan"), float("nan")

    dur_bias = {}
    if {"ref_duration_h"} <= set(m.columns):
        for sub in STATIONARY_SUBSTATES:
            g = m.loc[m["gold"].eq(sub) & m["ref_duration_h"].gt(0)]
            dur_bias[sub] = (float(((g["duration_h"] - g["ref_duration_h"]) / g["ref_duration_h"]).mean())
                             if len(g) else float("nan"))
    else:
        dur_bias = {"berth": float("nan"), "anchor": float("nan")}

    return {
        "n_scored": int(len(m)), "n_uncertain_excluded": int((gold["gold"] == "uncertain").sum()),
        "motion_macro_f1": macro_f1, "motion_f1_ci_low": f1_ci_low,
        "berth_anchor_f1": ba_f1, "resolved_coverage": resolved_coverage,
        "anchor_duration_bias": dur_bias["anchor"], "berth_duration_bias": dur_bias["berth"],
    }


def decide_pillar_b(scores: dict) -> dict:
    """Apply the FROZEN §5.3 Pillar-B gate. Duration bias is required only when a reference is available."""
    def _ok(v, thresh, op):
        return bool(np.isfinite(v) and op(v, thresh))
    checks = {
        "motion_macro_f1>=0.85": _ok(scores["motion_macro_f1"], MOTION_MACRO_F1_MIN, lambda a, b: a >= b),
        "motion_f1_ci_low>=0.80": _ok(scores["motion_f1_ci_low"], MOTION_F1_CI_LOW_MIN, lambda a, b: a >= b),
        "berth_anchor_f1>=0.85": _ok(scores["berth_anchor_f1"], BERTH_ANCHOR_F1_MIN, lambda a, b: a >= b),
        "resolved_coverage>=0.90": _ok(scores["resolved_coverage"], RESOLVED_COVERAGE_MIN, lambda a, b: a >= b),
    }
    for sub in STATIONARY_SUBSTATES:
        v = scores[f"{sub}_duration_bias"]
        # a missing duration reference does not pass silently: it BLOCKS (cannot confirm within ±10%)
        checks[f"|{sub}_duration_bias|<=0.10"] = _ok(v, DURATION_BIAS_MAX, lambda a, b: abs(a) <= b)
    overall = all(checks.values())
    return {"pass": overall, "checks": checks,
            "failed": [k for k, ok in checks.items() if not ok]}


def _self_check() -> None:
    """Synthetic episodes: a good classifier passes; a degraded one fails. Runnable guard."""
    rng = np.random.default_rng(1)
    n = 400
    gold_lab = rng.choice(["moving", "berth", "anchor"], n, p=[0.4, 0.3, 0.3])
    # good classifier: 95% correct coarse + substate; ref durations within a few %
    pred_coarse, pred_sub, ref_dur, dur = [], [], [], []
    for lab in gold_lab:
        correct = rng.random() < 0.95
        if lab == "moving":
            pred_coarse.append("moving" if correct else "stationary")
            pred_sub.append("n/a")
        else:
            pred_coarse.append("stationary" if correct else "moving")
            pred_sub.append(lab if correct else ("anchor" if lab == "berth" else "berth"))
        r = rng.uniform(2, 30)
        ref_dur.append(r)
        dur.append(r * rng.uniform(0.97, 1.03))
    ep = pd.DataFrame({"episode_id": [f"e{i}" for i in range(n)], "coarse_state": pred_coarse,
                       "substate": pred_sub, "duration_h": dur, "ref_duration_h": ref_dur})
    gold = pd.DataFrame({"episode_id": ep["episode_id"], "gold": gold_lab})
    good = score_state(ep, gold, n_boot=300)
    assert decide_pillar_b(good)["pass"], good

    bad = dict(good, motion_macro_f1=0.729, motion_f1_ci_low=0.68)      # the registered failure
    assert not decide_pillar_b(bad)["pass"]
    assert "motion_macro_f1>=0.85" in decide_pillar_b(bad)["failed"]

    # a missing duration reference must BLOCK, not silently pass
    blocked = dict(good, berth_duration_bias=float("nan"))
    assert not decide_pillar_b(blocked)["pass"]
    print("pillar_b self-check OK:", {k: round(v, 3) for k, v in good.items()
                                      if isinstance(v, float) and np.isfinite(v)})


def main() -> None:
    ap = argparse.ArgumentParser(description="Pillar B — episode-level blinded state validation (freeze first).")
    ap.add_argument("--self-check", action="store_true", help="run the synthetic pass/fail guard")
    args = ap.parse_args()
    if args.self_check or True:
        _self_check()


if __name__ == "__main__":
    main()
