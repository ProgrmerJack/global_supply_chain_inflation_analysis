"""Pillar B — episode-level, blinded, duration-aware state validation harness."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))


def _pings(mmsi, start, sogs, complex_id="san_pedro_bay", vt=70, step_min=30):
    ts = pd.date_range(start, periods=len(sogs), freq=f"{step_min}min", tz="UTC")
    return pd.DataFrame({"mmsi": mmsi, "timestamp": ts, "lon": -118.2, "lat": 33.7,
                         "sog": sogs, "vessel_type": vt, "port_complex_id": complex_id})


def test_reconstruct_collapses_pings_into_coarse_state_episodes():
    from pillar_b_state_validation import reconstruct_episodes
    # one vessel: fast approach (transit) -> slow (stationary) -> fast (depart)
    p = _pings(1, "2021-10-01", [8, 8, 8, 0.1, 0.1, 0.1, 0.1, 9, 9])
    ep = reconstruct_episodes(p, zones=None)
    assert list(ep["coarse_state"]) == ["moving", "stationary", "moving"]
    # the stationary episode spans 3 * 30 min = 1.5 h and is unresolved without zones
    stat = ep.loc[ep["coarse_state"] == "stationary"].iloc[0]
    assert stat["substate"] == "unresolved"
    assert stat["duration_h"] == pytest.approx(1.5)


def test_zone_assignment_filters_complex_and_prioritises_berth(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point, box
    from pillar_b_state_validation import _substate_by_zone, load_state_zones

    zones = gpd.GeoDataFrame(
        {"complex_id": ["san_pedro_bay", "other"], "zone_type": ["berth", "anchor"]},
        geometry=[box(-118.3, 33.6, -118.1, 33.8), box(-119.3, 34.6, -119.1, 34.8)],
        crs="EPSG:4326",
    )
    path = tmp_path / "zones.geojson"
    zones.to_file(path, driver="GeoJSON")
    filtered = load_state_zones(path, port="san_pedro_bay")
    assert len(filtered) == 1 and filtered.iloc[0]["zone_type"] == "berth"

    overlap = gpd.GeoDataFrame(
        {"zone_type": ["anchor", "berth"]},
        geometry=[box(-118.3, 33.6, -118.1, 33.8), box(-118.3, 33.6, -118.1, 33.8)],
        crs="EPSG:4326",
    )
    stationary = pd.DataFrame({"lon": [-118.2], "lat": [33.7]})
    assert _substate_by_zone(stationary, overlap).iloc[0] == "berth"


def test_blinded_bundle_hides_predictions(tmp_path):
    from pillar_b_state_validation import reconstruct_episodes, stratified_episode_sample, write_blinded_annotation_bundle
    p = pd.concat([_pings(m, "2021-10-01", [8, 8, 0.1, 0.1, 0.1, 9]) for m in range(1, 8)], ignore_index=True)
    ep = reconstruct_episodes(p, zones=None)
    sample = stratified_episode_sample(ep, per_stratum=50, seed=0)
    paths = write_blinded_annotation_bundle(sample, tmp_path)
    template = pd.read_csv(paths["template"])
    # the classifier's answer must NOT leak into what annotators see
    assert "coarse_state" not in template.columns and "substate" not in template.columns
    assert {"annotator_1_label", "annotator_2_label", "adjudicated_label",
            "adjudicated_start_utc", "adjudicated_end_utc"} <= set(template.columns)
    key = pd.read_csv(paths["prediction_key"])
    assert {"coarse_state", "substate"} <= set(key.columns)
    assert set(template["episode_id"]) == set(key["episode_id"])


def test_adjudicate_and_kappa():
    from pillar_b_state_validation import adjudicate, cohen_kappa
    labeled = pd.DataFrame({
        "episode_id": ["a", "b", "c", "d"],
        "annotator_A_label": ["moving", "berth", "anchor", "berth"],
        "annotator_B_label": ["moving", "berth", "berth", "anchor"],
        "adjudicated_label": ["", "", "anchor", ""],
    })
    gold = adjudicate(labeled).set_index("episode_id")["gold"]
    assert gold["a"] == "moving" and gold["b"] == "berth"        # agreement
    assert gold["c"] == "anchor"                                  # disagreement resolved by adjudicator
    assert gold["d"] == "uncertain"                               # disagreement, no adjudication
    assert 0.0 <= cohen_kappa(labeled["annotator_A_label"], labeled["annotator_B_label"]) <= 1.0


def test_decision_rejects_the_registered_failure():
    from pillar_b_state_validation import decide_pillar_b
    passing = {"motion_macro_f1": 0.90, "motion_f1_ci_low": 0.86, "berth_anchor_f1": 0.88,
               "resolved_coverage": 0.93, "anchor_duration_bias": 0.04, "berth_duration_bias": -0.05}
    assert decide_pillar_b(passing)["pass"]
    # the binding registered result must fail
    failed = dict(passing, motion_macro_f1=0.7289, motion_f1_ci_low=0.70)
    d = decide_pillar_b(failed)
    assert not d["pass"] and "motion_macro_f1>=0.85" in d["failed"]
    # a missing duration reference blocks (cannot confirm within ±10%)
    assert not decide_pillar_b(dict(passing, berth_duration_bias=float("nan")))["pass"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
