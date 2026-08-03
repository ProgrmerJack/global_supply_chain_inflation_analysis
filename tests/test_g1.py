"""Revised, component-separated G1 gate (validate_g1.py).

Validates the driver after the critique-driven restructure: import-value activity correlation is DIAGNOSTIC
(not a confirmatory gate), navigation-status state validation uses the 2-class motion metric, development
evidence emits no confirmatory pass/fail, and a reproducibility manifest is attached. Synthetic fixtures only.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def _activity_frames(n_good, n_bad, months=18, prefix=""):
    ym = ([f"2018-{m:02d}" for m in range(1, 13)] + [f"2019-{m:02d}" for m in range(1, 13)])[:months]
    base = np.arange(len(ym), dtype=float) + 5.0
    ais_rows, off_rows = [], []
    for i in range(n_good + n_bad):
        port = f"{prefix}port_{i:02d}"
        official = base + i
        ais = official * 2.0 + 1.0 if i < n_good else official[::-1]
        for k, month in enumerate(ym):
            ais_rows.append({"port_complex_id": port, "year_month": month, "ais_activity": ais[k]})
            off_rows.append({"port_complex_id": port, "year_month": month, "official_activity": official[k]})
    return pd.DataFrame(ais_rows), pd.DataFrame(off_rows)


def _labels(motion_good, motion_bad, unresolved=2):
    rows = []
    for _ in range(motion_good):
        rows.append({"motion_truth": "moving", "motion_pred": "moving", "berth_truth": np.nan, "berth_pred": np.nan})
        rows.append({"motion_truth": "stationary", "motion_pred": "stationary", "berth_truth": "moored", "berth_pred": "moored"})
    for _ in range(motion_bad):
        rows.append({"motion_truth": "moving", "motion_pred": "stationary", "berth_truth": np.nan, "berth_pred": np.nan})
    for _ in range(unresolved):
        rows.append({"motion_truth": "stationary", "motion_pred": "stationary", "berth_truth": "moored", "berth_pred": "unknown_stationary"})
    return pd.DataFrame(rows)


def test_correlations_require_minimum_overlap():
    from process_ais.validate_g1 import port_activity_correlations, MIN_OVERLAP_MONTHS

    ais, official = _activity_frames(2, 0, months=MIN_OVERLAP_MONTHS + 3)
    ais = ais.loc[(ais.port_complex_id != "port_01") | (ais.groupby("port_complex_id").cumcount() < 5)]
    corrs, report = port_activity_correlations(ais, official)
    assert "port_00" in corrs and "port_01" not in corrs


def test_import_value_correlation_is_diagnostic_not_a_gate():
    from process_ais.validate_g1 import decide_g1

    ais, official = _activity_frames(11, 2)  # majority correlate, but comparator is import_value
    d = decide_g1(ais, official, comparator="import_value", evidence_status="development")
    act = d["components"]["activity_correlation"]
    assert act["status"] == "diagnostic"          # NOT pass/fail
    assert act["operationally_matched"] is False
    assert "import value" in act["note"]


def test_development_evidence_emits_no_confirmatory_verdict():
    from process_ais.validate_g1 import decide_g1

    ais, official = _activity_frames(11, 2)
    d = decide_g1(ais, official, {"motion_macro_f1": 0.9, "n_motion_scored": 100}, evidence_status="development")
    assert d["evidence_status"] == "development"
    assert d["status"] == "development"           # not "pass" even though sub-gates look good


def test_matched_comparator_confirmatory_pass():
    from process_ais.validate_g1 import decide_g1

    ais, official = _activity_frames(12, 0)  # 12 ports all strongly correlated
    d = decide_g1(ais, official, {"motion_macro_f1": 0.9, "n_motion_scored": 100},
                  comparator="teu_throughput", evidence_status="confirmatory",
                  integrity={"status": "pass"})
    assert d["components"]["activity_correlation"]["status"] == "pass"
    assert d["components"]["motion_state"]["status"] == "pass"
    assert d["components"]["national_scope"]["status"] == "pass"
    assert d["status"] == "pass"


def test_ais_monthly_activity_accepts_true_port_call_measures():
    from process_ais.validate_g1 import ais_monthly_activity

    panel = pd.DataFrame(
        {
            "port_complex_id": ["alpha"],
            "year_month": ["2021-01"],
            "cargo_port_calls": [7],
            "freight_port_calls": [11],
        }
    )

    assert ais_monthly_activity(panel, "cargo_port_calls").ais_activity.tolist() == [7]
    assert ais_monthly_activity(panel, "freight_port_calls").ais_activity.tolist() == [11]


def test_confirmatory_fails_on_scope():
    from process_ais.validate_g1 import decide_g1

    ais, official = _activity_frames(10, 0)  # only 10 complexes < 12
    d = decide_g1(ais, official, {"motion_macro_f1": 0.9}, comparator="teu_throughput",
                  evidence_status="confirmatory", integrity={"status": "pass"})
    assert d["components"]["national_scope"]["status"] == "fail"
    assert d["status"] == "fail"


def test_motion_gate_fails_below_threshold():
    from process_ais.validate_g1 import decide_g1

    ais, official = _activity_frames(12, 0)
    d = decide_g1(ais, official, {"motion_macro_f1": 0.60}, comparator="teu_throughput",
                  evidence_status="confirmatory", integrity={"status": "pass"})
    assert d["components"]["motion_state"]["status"] == "fail"
    assert d["status"] == "fail"


def test_state_metrics_from_labels():
    from process_ais.validate_g1 import state_metrics_from_labels

    labels = _labels(motion_good=20, motion_bad=0, unresolved=5)
    m = state_metrics_from_labels(labels)
    assert m["motion_macro_f1"] == pytest.approx(1.0)          # all motion correct
    assert m["berth_unresolved_stationary_share"] > 0          # the unknown_stationary pings are unresolved


def test_state_metrics_rejects_the_retired_truth_predicted_label_schema():
    """The prior three-state label artifact cannot silently enter the revised motion gate."""
    from process_ais.validate_g1 import state_metrics_from_labels

    with pytest.raises(ValueError, match="legacy blind-label schema"):
        state_metrics_from_labels(pd.DataFrame({"truth": ["moving"], "predicted": ["moving"]}))


def test_ingestion_integrity(tmp_path):
    from process_ais.validate_g1 import ingestion_integrity

    m = tmp_path / "ingestion_manifest.csv"
    pd.DataFrame({"date": ["a", "b", "c"], "status": ["ok", "ok", "error"]}).to_csv(m, index=False)
    integ = ingestion_integrity(m)
    assert integ["status"] == "fail" and integ["days_error"] == 1
    pd.DataFrame({"date": ["a", "b"], "status": ["ok", "ok"]}).to_csv(m, index=False)
    assert ingestion_integrity(m)["status"] == "pass"


def test_ingestion_integrity_coalesces_superseded_retries_by_date(tmp_path):
    """The append-only ledger must report final day coverage, not historical retry attempts."""
    from process_ais.validate_g1 import ingestion_integrity

    m = tmp_path / "ingestion_manifest.csv"
    pd.DataFrame(
        {
            "date": ["2023-02-19", "2023-02-19", "2023-02-20", "2023-02-20"],
            "status": ["error", "ok", "error", "ok"],
        }
    ).to_csv(m, index=False)

    integrity = ingestion_integrity(m)

    assert integrity["status"] == "pass"
    assert integrity["days_total"] == 2
    assert integrity["days_ok"] == 2
    assert integrity["days_error"] == 0
    assert integrity["attempt_rows"] == 4
    assert integrity["superseded_error_attempts"] == 2


def test_reproducibility_manifest_hashes_inputs(tmp_path):
    from process_ais.validate_g1 import reproducibility_manifest

    p = tmp_path / "panel.csv"
    p.write_text("x\n1\n", encoding="utf-8")
    repro = reproducibility_manifest({"panel": p}, measure="cargo_vessels", comparator="import_value")
    assert repro["inputs"]["panel"]["sha256"] is not None and len(repro["inputs"]["panel"]["sha256"]) == 64
    assert repro["comparator"] == "import_value"


def test_write_is_confirmatory_guarded(tmp_path, monkeypatch):
    import process_ais.validate_g1 as g1

    calls = {}

    def fake_guard(path):
        calls["p"] = path
        raise PermissionError("locked")

    monkeypatch.setattr(g1, "assert_confirmatory_unlocked", fake_guard)
    with pytest.raises(PermissionError):
        g1.write_g1_decision({"gate": "G1"}, tmp_path / "G1_ais" / "gate_decision.json")
    assert "p" in calls


def test_g1_v1_audit_preserves_the_historical_decision_hash():
    """The post-result audit must document, not rewrite, the G1-v1 artifact."""
    root = Path(__file__).resolve().parents[1]
    result_dir = root / "results" / "development" / "G1_ais_fullcensus"
    decision = result_dir / "gate_decision_ves_wgt_mo.json"
    checksum = result_dir / "gate_decision_ves_wgt_mo.sha256"
    audit_path = result_dir / "audit_g1_v1_2026-07-15.json"
    audit_markdown = result_dir / "audit_g1_v1_2026-07-15.md"

    expected = checksum.read_text(encoding="utf-8").split()[0].lower()
    actual = hashlib.sha256(decision.read_bytes()).hexdigest()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert actual == expected
    assert audit["audit_target"] == decision.name
    assert audit["audit_target_sha256"] == actual
    assert audit["historical_record_modified"] is False
    assert audit["g1_v1_decision"] == "fail"
    assert audit["activity_pair"]["registered_classification"] == "operationally_matched"
    assert audit["activity_pair"]["realised_construct_match"] == "partial"
    assert audit["motion_pair"]["decision"] == "fail"
    assert audit["berth_anchor"]["resolved_coverage"] == pytest.approx(0.3914597959952761)
    assert audit["downstream_status"] == "blocked_pending_separately_preregistered_g1_v2"
    assert audit_markdown.exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
