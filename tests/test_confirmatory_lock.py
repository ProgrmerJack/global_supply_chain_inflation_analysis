"""Tests for fail-closed access to confirmatory and held-out paths."""

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

import governance.access as access  # noqa: E402
from governance.access import (  # noqa: E402
    assert_confirmatory_unlocked,
    assert_g1_v2_unlocked,
    assert_nature_recovery_unlocked,
    assert_baltimore_unlocked,
)


def test_holdout_and_confirmatory_paths_are_locked_without_a_registration_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(access, "UNLOCK_PATH", tmp_path / "CONFIRMATORY_UNLOCK.json")

    with pytest.raises(PermissionError, match="confirmatory access is locked"):
        assert_confirmatory_unlocked(REPOSITORY_ROOT / "data/holdout/synthetic_fixture.csv")

    with pytest.raises(PermissionError, match="confirmatory access is locked"):
        assert_confirmatory_unlocked(REPOSITORY_ROOT / "results/confirmatory/model_output.csv")

    with pytest.raises(PermissionError, match="confirmatory access is locked"):
        assert_confirmatory_unlocked(
            REPOSITORY_ROOT / "data/interim/national_ais_coverage.csv"
        )


def test_malformed_unlock_cannot_bypass_the_guard(monkeypatch, tmp_path):
    manifest = tmp_path / "osf_manifest.csv"
    unlock = tmp_path / "CONFIRMATORY_UNLOCK.json"
    manifest.write_text("path,sha256\n", encoding="utf-8")
    unlock.write_text('{"registration_url": "not-an-osf-url"}', encoding="utf-8")
    monkeypatch.setattr(access, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(access, "UNLOCK_PATH", unlock)

    with pytest.raises(PermissionError, match="OSF receipt URL"):
        assert_confirmatory_unlocked(REPOSITORY_ROOT / "data/holdout/synthetic_fixture.csv")


def test_unlock_script_record_allows_protected_access(monkeypatch, tmp_path):
    manifest = tmp_path / "osf_manifest.csv"
    unlock = tmp_path / "CONFIRMATORY_UNLOCK.json"
    manifest.write_text("path,sha256\n", encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    unlock.write_text(
        '{"registration_id": "htdqp", "registration_url": "https://osf.io/htdqp/", '
        '"registered_at_utc": "2026-07-13T00:00:00+00:00", '
        f'"manifest_sha256": "{manifest_sha256}", '
        '"unlocked_at_utc": "2026-07-13T00:00:00+00:00"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(access, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(access, "UNLOCK_PATH", unlock)

    assert_confirmatory_unlocked(REPOSITORY_ROOT / "data/holdout/synthetic_fixture.csv")


def test_g1_v2_paths_require_a_separate_matching_registration(monkeypatch, tmp_path):
    manifest = tmp_path / "g1_v2_manifest.csv"
    unlock = tmp_path / "g1_v2_unlock.json"
    monkeypatch.setattr(access, "G1_V2_MANIFEST_PATH", manifest)
    monkeypatch.setattr(access, "G1_V2_UNLOCK_PATH", unlock)

    target = REPOSITORY_ROOT / "data/interim/g1_v2/official_calls.csv"
    with pytest.raises(PermissionError, match="G1-v2 access is locked"):
        assert_g1_v2_unlocked(target)

    manifest.write_text("path,sha256\n", encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    unlock.write_text(
        '{"registration_id": "g1v2", "registration_url": "https://osf.io/g1v2/", '
        '"registered_at_utc": "2026-07-15T00:00:00+00:00", '
        f'"manifest_sha256": "{manifest_sha256}"}}',
        encoding="utf-8",
    )

    assert_g1_v2_unlocked(target)


def test_nature_recovery_tree_requires_its_own_matching_registration(monkeypatch, tmp_path):
    manifest = tmp_path / "nature_recovery_manifest.csv"
    unlock = tmp_path / "nature_recovery_unlock.json"
    monkeypatch.setattr(access, "NATURE_RECOVERY_MANIFEST_PATH", manifest)
    monkeypatch.setattr(access, "NATURE_RECOVERY_UNLOCK_PATH", unlock)
    target = REPOSITORY_ROOT / "data/interim/nature_recovery/coastal_pings"

    with pytest.raises(PermissionError, match="Nature recovery access is locked"):
        assert_nature_recovery_unlocked(target)

    manifest.write_text("path,sha256\n", encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    unlock.write_text(
        '{"registration_id": "newid", "registration_url": "https://osf.io/newid/", '
        f'"manifest_sha256": "{manifest_sha256}"}}',
        encoding="utf-8",
    )

    assert_nature_recovery_unlocked(target)


def test_pending_nature_recovery_receipt_allows_only_coastal_acquisition(monkeypatch, tmp_path):
    manifest = tmp_path / "nature_recovery_manifest.csv"
    manifest.write_text("path,sha256,bytes\n", encoding="utf-8")
    unlock = tmp_path / "nature_recovery_unlock.json"
    unlock.write_text(
        json.dumps(
            {
                "registration_url": "https://osf.io/jh3ea/",
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "protected_outcome_analysis_unlocked": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(access, "NATURE_RECOVERY_MANIFEST_PATH", manifest)
    monkeypatch.setattr(access, "NATURE_RECOVERY_UNLOCK_PATH", unlock)

    assert_nature_recovery_unlocked(
        REPOSITORY_ROOT / "data/interim/nature_recovery/coastal_pings"
    )
    with pytest.raises(PermissionError, match="acquisition only"):
        assert_nature_recovery_unlocked(
            REPOSITORY_ROOT / "results/confirmatory/nature_recovery/r_g1.json"
        )
    with pytest.raises(PermissionError, match="acquisition only"):
        assert_nature_recovery_unlocked(
            REPOSITORY_ROOT / "data/interim/nature_recovery/aqview_history"
        )


def test_baltimore_tree_requires_its_own_accepted_registration(monkeypatch, tmp_path):
    manifest = tmp_path / "baltimore_manifest.csv"
    unlock = tmp_path / "baltimore_unlock.json"
    monkeypatch.setattr(access, "BALTIMORE_MANIFEST_PATH", manifest)
    monkeypatch.setattr(access, "BALTIMORE_UNLOCK_PATH", unlock)
    target = REPOSITORY_ROOT / "results/confirmatory/baltimore_shock/b_g1.json"

    with pytest.raises(PermissionError, match="Baltimore shock access is locked"):
        assert_baltimore_unlocked(target)

    manifest.write_text("path,sha256,bytes\n", encoding="utf-8")
    receipt = {
        "registration_url": "https://osf.io/newid/",
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "protected_outcome_analysis_unlocked": False,
    }
    unlock.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(PermissionError, match="not accepted"):
        assert_baltimore_unlocked(target)

    receipt["protected_outcome_analysis_unlocked"] = True
    unlock.write_text(json.dumps(receipt), encoding="utf-8")
    assert_baltimore_unlocked(target)


def test_holdout_registry_defines_all_five_classes_with_a_frozen_seed():
    registry_path = Path(__file__).resolve().parents[1] / "prereg/governance/holdout_registry.csv"
    with registry_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert {row["holdout_class"] for row in rows} == {
        "geographic",
        "temporal",
        "monitor",
        "inventory",
        "event",
    }
    assert {row["seed"] for row in rows} == {"20260714"}
    assert {row["access_status"] for row in rows} == {"sealed"}
