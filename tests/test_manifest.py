"""Tests for the outcome-free OSF registration manifest."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_validator():
    path = ROOT / "scripts/validate_protocol.py"
    spec = importlib.util.spec_from_file_location("validate_protocol", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_registration_bundle_is_complete_and_excludes_outcomes():
    validator = load_validator()
    labels = [label for label, _ in validator.manifest_rows()]

    assert "prereg/protocol/preregistration_v1.md" in labels
    assert "data/processed/port_registry.csv" in labels
    assert not any(
        label.startswith(("data/", "results/")) and label != "data/processed/port_registry.csv"
        for label in labels
    )


def test_manifest_validation_detects_a_changed_or_missing_entry(tmp_path):
    validator = load_validator()
    manifest = tmp_path / "osf_manifest.csv"
    manifest.write_text("path,sha256\nmissing.md,not-a-hash\n", encoding="utf-8")

    errors = validator.validate_manifest(manifest)

    assert errors
