from pathlib import Path
import importlib.util

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_validator():
    path = ROOT / "scripts/validate_protocol.py"
    spec = importlib.util.spec_from_file_location("validate_protocol", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_required_protocol_scaffold_is_valid():
    validator = load_validator()
    assert validator.validate(strict=False) == []


def test_confirmatory_unlock_is_created_only_with_a_registration_receipt():
    receipt = ROOT / "prereg/governance/registration_receipt.json"
    unlock = ROOT / "prereg/governance/CONFIRMATORY_UNLOCK.json"
    assert receipt.exists() == unlock.exists()


def test_results_directories_are_separated():
    assert (ROOT / "results/exploratory").is_dir()
    assert (ROOT / "results/confirmatory").is_dir()


def test_protocol_uses_equity_gate_and_explicit_ais_gap_policy():
    config = yaml.safe_load((ROOT / "config/protocol/gates.yml").read_text(encoding="utf-8"))
    gates = config["gates"]
    preregistration = (ROOT / "prereg/protocol/preregistration_v1.md").read_text(encoding="utf-8")

    assert gates["G10"]["name"] == "Equity"
    assert "journal_decision" in config
    assert "2020-07, 2020-08, 2023-03 and 2023-04" in preregistration
    assert "never back-filled from dwell summaries" in preregistration


def test_validator_rejects_a_journal_gate_in_place_of_equity():
    validator = load_validator()
    gates_path = ROOT / "config/protocol/gates.yml"
    gates = gates_path.read_text(encoding="utf-8")

    assert validator.validate_gate_configuration(gates) == []
    assert validator.validate_gate_configuration(gates.replace("name: Equity", "name: Journal gate")) == [
        "G10 must be named Equity"
    ]
