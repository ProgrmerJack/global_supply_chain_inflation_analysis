"""Pillar-B scoring machinery — the emissions-critical duration-bias gate must not be masked by high F1."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))


def _df(n=200, seed=1):
    rng = np.random.default_rng(seed)
    gold = rng.choice(["moving", "berth", "anchor"], n, p=[0.4, 0.3, 0.3])
    clf = np.where(rng.random(n) < 0.9, gold, rng.choice(["moving", "berth", "anchor"], n))
    ref = rng.uniform(2, 30, n)
    return pd.DataFrame({"episode_id": [f"e{i}" for i in range(n)], "gold": gold,
                        "classifier_label": clf, "ref_duration_hours": ref, "duration_hours": ref})


def test_high_f1_but_biased_duration_fails():
    from pillar_b_scoring import duration_bias, classification_scorecard, decide_pillar_b_full, resolved_coverage
    df = _df()
    # inflate classifier anchor durations by 40% -> big anchor-hour bias, F1 unchanged
    df.loc[df.classifier_label == "anchor", "duration_hours"] *= 1.4
    db = duration_bias(df)
    assert db["anchor_hour_bias"] > 0.10          # biased
    gm = np.where(np.isin(df.gold, ("berth", "anchor")), "stationary", "moving")
    pm = np.where(np.isin(df.classifier_label, ("berth", "anchor")), "stationary", "moving")
    sc = {"motion_f1": classification_scorecard(gm, pm, ("moving", "stationary"))["macro_f1"],
          "motion_f1_ci_low": 0.86, "berth_anchor_f1": 0.9,
          "resolved_coverage": resolved_coverage(df.gold.to_numpy(), df.classifier_label.to_numpy()),
          "anchor_hour_bias": db["anchor_hour_bias"], "berth_hour_bias": db["berth_hour_bias"],
          "policy_effect_robust": True}
    d = decide_pillar_b_full(sc)
    assert not d["overall_pass"] and "anchorage_duration_bias" in d["failed"]


def test_interrater_and_power():
    from pillar_b_scoring import interrater_reliability, power_check
    a = pd.Series(["moving", "berth", "anchor", "moving"]); b = pd.Series(["moving", "berth", "moving", "moving"])
    ir = interrater_reliability(a, b)
    assert 0 <= ir["cohen_kappa"] <= 1 and "raw_agreement" in ir
    pw = power_check(_df(n=10))
    assert pw["expand_recommended"] is True        # 10 episodes -> sparse classes


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
