import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))


def test_postscreen_rule_requires_one_unflagged_physical_intersection():
    import pillar_b_route_a_v2 as v2

    accepted = {"sceptical_uncertain": False, "physical": {"kinematic": ["anchor", "berth"], "geometry": ["anchor"], "trajectory_shape": ["anchor"]}}
    ambiguous = {**accepted, "physical": {"kinematic": ["anchor", "berth"], "geometry": ["anchor", "berth"], "trajectory_shape": ["anchor", "berth"]}}
    assert v2._selected(accepted)
    assert not v2._selected({**accepted, "sceptical_uncertain": True})
    assert not v2._selected(ambiguous)


def test_v2_external_timestamp_fails_closed_and_binds_the_public_title(tmp_path, monkeypatch):
    import pillar_b_route_a_v2 as v2

    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(v2, "verify_local_freeze", lambda: {"sha256": {"candidate_manifest": "manifest", "model_prompt": "prompt"}})
    monkeypatch.setattr(v2.route_a, "sha256", lambda path: "freeze")
    monkeypatch.setattr(v2.route_a, "_osf_registration_attributes", lambda _: {"title": v2.TITLE, "date_registered": "2026-07-17T00:00:00Z"})
    receipt.write_text(json.dumps({"status": "PENDING_EXTERNAL_REGISTRATION"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not externally timestamped"):
        v2.require_external_timestamp(receipt)
    receipt.write_text(json.dumps({
        "status": "EXTERNALLY_TIMESTAMPED", "local_freeze_receipt_sha256": "freeze", "registration_id": "abc12",
        "registration_url": "https://osf.io/abc12/", "registration_title": v2.TITLE,
        "sha256": {"candidate_manifest": "manifest"}, "model_kimi": "kimi", "model_kimi_version": "v1",
        "model_kimi_parameters": {}, "model_claude": "claude", "model_claude_version": "claude-sonnet-5",
        "model_claude_parameters": {"cli_model": "sonnet"}, "prompt_sha256": "prompt", "claude_cli_version": "2.1.199",
    }), encoding="utf-8")
    assert v2.require_external_timestamp(receipt)["model_claude"] == "claude"
