import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))


def _track():
    return pd.DataFrame({"relative_h": [0, 1, 2, 3, 4, 5], "lat": [33.7] * 6,
                         "lon": [-118.2, -118.203, -118.206, -118.209, -118.212, -118.215],
                         "sog": [4, 4, 4, 4, 4, 4], "cog": [90] * 6})


def test_features_and_rule_channels_do_not_force_a_stationary_label():
    from pillar_b_route_a import episode_features, rule_outputs
    f = episode_features(_track(), 1, 4); f.update({"berth_fraction": 0.0, "anchor_fraction": 0.0})
    labels = rule_outputs(f)
    assert labels["kinematic"] == ["moving"] and labels["geometry"] == ["moving", "manoeuvre"]


def test_strict_consensus_requires_every_channel_and_repeat_to_agree():
    from pillar_b_route_a import strict_consensus
    physical = {"kinematic": ["anchor", "berth"], "geometry": ["anchor"], "trajectory_shape": ["anchor"]}
    runs = [{"primary_class": "anchor", "state_start_h": 1.0, "state_end_h": 3.0} for _ in range(3)]
    accepted = strict_consensus(physical, runs, runs, False, tolerance_h=.1)
    assert accepted["status"] == "accepted_silver"
    rejected = strict_consensus(physical, runs, [{**runs[0], "primary_class": "berth"}] * 3, False, tolerance_h=.1)
    assert rejected["status"] == "uncertain"
    no_state = strict_consensus({key: [] for key in physical}, [{**run, "primary_class": "uncertain"} for run in runs], [{**run, "primary_class": "uncertain"} for run in runs], False, tolerance_h=.1)
    assert no_state["status"] == "uncertain"


def test_model_runs_require_distinct_ids_and_frozen_channel():
    from pillar_b_route_a import _validated_model_runs, sha256_text
    runs = [{"blind_id": "BLIND_001", "run_id": f"run-{i}", "model_id": "family-a", "prompt_sha256": "a" * 64,
             "primary_class": "anchor", "state_start_h": 1.0, "state_end_h": 3.0, "confidence": .9,
             "evidence": ["x"], "counterevidence": [], "model_version": "v1", "model_parameters": {"temperature": .7},
             "response_timestamp_utc": "2026-07-17T00:00:00Z", "raw_response": "{\"primary_class\": \"anchor\"}"} for i in range(3)]
    for run in runs:
        run["raw_response_sha256"] = sha256_text(run["raw_response"])
    assert _validated_model_runs(runs, "BLIND_001", model_id="family-a", model_version="v1",
                                 model_parameters={"temperature": .7}, prompt_sha256="a" * 64) == runs
    duplicate = [{**run, "run_id": "repeat"} for run in runs]
    with pytest.raises(RuntimeError, match="independently identified"):
        _validated_model_runs(duplicate, "BLIND_001", model_id="family-a", model_version="v1",
                              model_parameters={"temperature": .7}, prompt_sha256="a" * 64)


def test_openrouter_record_preserves_raw_response_and_frozen_metadata():
    import json
    from pillar_b_route_a import _model_record, sha256_text
    response = {"id": "gen-1", "model": "family-a", "choices": [{"message": {"content": json.dumps({
        "primary_class": "anchor", "state_start_h": 1.0, "state_end_h": 3.0, "confidence": .9,
        "evidence": ["x"], "counterevidence": []})}}], "usage": {"total_tokens": 12}}
    raw = json.dumps(response, sort_keys=True)
    record = _model_record(raw, response, blind_id="BLIND_001", replica=1, model_id="family-a",
                           model_version="catalog-id", model_parameters={"max_tokens": 1024}, prompt_sha256="a" * 64)
    assert record["run_id"] == "gen-1" and record["raw_response_sha256"] == sha256_text(raw)


def test_external_timestamp_must_bind_verified_osf_registration(tmp_path, monkeypatch):
    import json
    import pillar_b_route_a as route
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(route, "verify_local_freeze", lambda bundle: {"sha256": {"evidence_manifest": "manifest-hash", "model_prompt": "a" * 64}})
    monkeypatch.setattr(route, "sha256", lambda path: "local-receipt-hash")
    monkeypatch.setattr(route, "_osf_registration_attributes", lambda registration_id: {"title": route.ROUTE_A_TITLE, "date_registered": "2026-07-17T00:00:00Z"})
    pending = {"status": "PENDING_EXTERNAL_REGISTRATION"}
    receipt.write_text(json.dumps(pending), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not externally timestamped"):
        route.require_external_timestamp(receipt, tmp_path)
    ready = {
        "status": "EXTERNALLY_TIMESTAMPED", "local_freeze_receipt_sha256": "local-receipt-hash",
        "sha256": {"evidence_manifest": "manifest-hash"}, "registration_id": "abc12",
        "registration_url": "https://osf.io/abc12/", "registration_title": route.ROUTE_A_TITLE,
        "model_a": "family-a", "model_b": "family-b", "prompt_a_sha256": "a" * 64,
        "prompt_b_sha256": "a" * 64, "model_a_version": "v1", "model_b_version": "v2",
        "model_a_parameters": {"temperature": .7}, "model_b_parameters": {"temperature": .7},
    }
    receipt.write_text(json.dumps(ready), encoding="utf-8")
    assert route.require_external_timestamp(receipt, tmp_path)["model_a"] == "family-a"
