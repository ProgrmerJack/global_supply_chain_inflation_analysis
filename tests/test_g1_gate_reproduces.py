"""End-to-end reproduction of the FAILED national G1 gate (Paper C claims M02 and M03).

A failed gate is still a result, and a result that cannot be recomputed is not evidence — it is an
assertion about a file. Until 2026-08-06 the only check on M02/M03 was re-hashing the stored decision,
and the driver could not be invoked at all because its two required arguments were documented nowhere.

This test runs the real driver on the real registered inputs and requires the three published component
values to full float precision. It writes only to a tmp path, so the registered decision at
`results/development/G1_ais_fullcensus/gate_decision_ves_wgt_mo.json` is never touched.

If this test starts failing, either an input drifted or the gate arithmetic changed — both are reasons
to stop, not to update the expected numbers.
"""

import json
import os
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PANEL = os.path.join(REPO, "data", "processed", "national_activity_month.csv")
OFFICIAL = os.path.join(REPO, "data", "processed", "official_port_activity_ves_wgt_mo.csv")
LABELS = os.path.join(REPO, "data", "processed", "blind_state_labels.csv")
DRIVER = os.path.join(REPO, "src", "process_ais", "validate_g1.py")

# the registered decision these must match
REGISTERED = os.path.join(
    REPO, "results", "development", "G1_ais_fullcensus", "gate_decision_ves_wgt_mo.json"
)

pytestmark = pytest.mark.skipif(
    not all(os.path.exists(p) for p in (PANEL, OFFICIAL, LABELS, DRIVER)),
    reason="G1 inputs not present in this checkout",
)


def test_failed_g1_gate_reproduces_to_full_precision(tmp_path):
    out = tmp_path / "g1_recheck.json"
    proc = subprocess.run(
        [sys.executable, DRIVER,
         "--panel", PANEL,
         "--official", OFFICIAL,
         "--measure", "freight_port_calls",
         "--comparator", "cargo_tonnage",
         "--blind-labels", LABELS,
         "--evidence-status", "development",
         "--out", str(out)],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    assert proc.returncode == 0, f"driver failed:\n{proc.stdout}\n{proc.stderr}"
    got = json.loads(out.read_text(encoding="utf-8"))["components"]

    assert got["activity_correlation"]["median_r"] == 0.3200241092239818
    assert got["activity_correlation"]["status"] == "fail"
    assert got["motion_state"]["macro_f1"] == 0.7288887505928576
    assert got["motion_state"]["status"] == "fail"
    assert got["berth_anchor_state"]["macro_f1_confident"] == 0.9895978427549311

    # and they must equal the registered decision, not merely a number we like
    if os.path.exists(REGISTERED):
        reg = json.loads(open(REGISTERED, encoding="utf-8").read())["components"]
        for comp, field in (("activity_correlation", "median_r"),
                            ("motion_state", "macro_f1"),
                            ("berth_anchor_state", "macro_f1_confident")):
            assert got[comp][field] == reg[comp][field], (
                f"{comp}.{field}: recomputed {got[comp][field]!r} != registered {reg[comp][field]!r}")


def test_gate_recomputation_does_not_touch_the_registered_decision(tmp_path):
    """The driver must never be able to overwrite the frozen decision."""
    if not os.path.exists(REGISTERED):
        pytest.skip("registered decision not present")
    before = open(REGISTERED, "rb").read()
    subprocess.run(
        [sys.executable, DRIVER, "--panel", PANEL, "--official", OFFICIAL,
         "--measure", "freight_port_calls", "--comparator", "cargo_tonnage",
         "--evidence-status", "development", "--out", str(tmp_path / "x.json")],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    assert open(REGISTERED, "rb").read() == before, "registered G1 decision was modified"
