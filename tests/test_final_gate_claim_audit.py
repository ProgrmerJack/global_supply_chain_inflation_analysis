import hashlib
import json

import pytest

from src.analysis import final_gate_claim_audit as audit
from src.analysis import nature_route_failure_reaudit as reaudit


def test_nature_routes_require_their_non_substitutable_gates():
    gates = [
        {
            "gate": f"NS-G{index}",
            "passed": "true" if index in {1, 2, 3, 4, 6, 7, 10} else "false",
        }
        for index in range(1, 11)
    ]
    decision = audit.journal_decision(gates)
    assert decision["nature_sustainability_submission_ready"]
    assert decision["nature_communications_fallback_ready"]


def test_current_all_failed_gate_table_stops_both_nature_routes():
    evidence = {f"g{index}": False for index in range(1, 11)}
    gates = audit.gate_table(evidence)
    decision = audit.journal_decision(gates)
    assert len(gates) == 10
    assert not decision["nature_sustainability_submission_ready"]
    assert not decision["nature_communications_fallback_ready"]
    assert decision["current_journal_decision"] == "stop_current_nature_route"
    assert not decision["manuscript_editing_authorized_for_current_nature_route"]


def test_claim_matrix_never_promotes_computational_silver_or_modelled_exposure():
    claims = {row["claim_id"]: row for row in audit.claim_matrix()}
    assert claims["C12"]["status"] == "modelled_only"
    assert claims["C13"]["status"] == "prohibited"
    assert claims["C04"]["status"] == "supported_descriptive"


def test_frozen_audit_verifier_rejects_output_tampering(tmp_path):
    decision = {"input_hashes": {"source": {"path": "source.json", "sha256": "a" * 64}}}
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    expected = hashlib.sha256(decision_path.read_bytes()).hexdigest()
    (tmp_path / "audit_receipt.json").write_text(
        json.dumps(
            {
                "status": "FINAL_GATE_CLAIM_AUDIT_FROZEN",
                "outputs_sha256": {"decision.json": expected},
            }
        ),
        encoding="utf-8",
    )
    assert audit.verify_frozen_outputs(tmp_path, decision["input_hashes"]) == decision
    decision_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="failed hash verification"):
        audit.verify_frozen_outputs(tmp_path, decision["input_hashes"])


def test_frozen_audit_verifier_rejects_changed_upstream_evidence(tmp_path):
    input_hashes = {"source": {"path": "source.json", "sha256": "a" * 64}}
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps({"input_hashes": input_hashes}), encoding="utf-8")
    expected = hashlib.sha256(decision_path.read_bytes()).hexdigest()
    (tmp_path / "audit_receipt.json").write_text(
        json.dumps(
            {
                "status": "FINAL_GATE_CLAIM_AUDIT_FROZEN",
                "outputs_sha256": {"decision.json": expected},
            }
        ),
        encoding="utf-8",
    )
    changed = {"source": {"path": "source.json", "sha256": "b" * 64}}
    with pytest.raises(RuntimeError, match="upstream evidence differs"):
        audit.verify_frozen_outputs(tmp_path, changed)


def test_atberth_reaudit_detects_gap_segmented_in_port_calls_against_sea_arrivals():
    checks = reaudit.detect_atberth_construct_mismatch(
        'calls = assign_port_call_ids(pings)\nzones.loc[zones.state.eq("berth")]',
        "new_call = gap.gt(gap_hours)",
        "tanker arrivals from sea to berth or anchorage before shifting to berth",
    )
    assert checks == {
        "official_unit_is_sea_arrival": True,
        "ais_unit_uses_in_port_gap_segmentation": True,
        "primary_geometry_omits_frozen_terminal_points": True,
    }


def test_current_reaudit_separates_real_failures_from_bugs_and_unfired_gates():
    decision = reaudit.build_reaudit()
    gates = {row["gate"]: row["reaudit_class"] for row in decision["gates"]}
    assert decision["current_nature_sustainability_ready"] is False
    assert decision["nature_route_scientifically_dead"] is False
    assert gates["NS-G3"] == "REGISTERED_FAILURE_CONFIRMED"
    assert gates["NS-G4"] == "SCIENTIFIC_FAILURE_INVALIDATED_BY_ACQUISITION_BUG"
    assert gates["NS-G8"] == "NOT_FIRED_AND_FINAL_AUDIT_MAPPING_BUG"
