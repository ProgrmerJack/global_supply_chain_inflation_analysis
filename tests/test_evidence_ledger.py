"""Tests for the boundary between inspected pilot evidence and confirmation."""

import csv
from pathlib import Path


def test_evidence_ledger_has_unique_ids_and_permitted_statuses():
    ledger_path = Path(__file__).resolve().parents[1] / "prereg/governance/evidence_status.csv"
    with ledger_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert rows
    assert set(reader.fieldnames or []) == {
        "claim_id",
        "claim_text",
        "data_seen",
        "period_seen",
        "status",
        "allowed_use",
    }
    assert len({row["claim_id"] for row in rows}) == len(rows)
    assert all(row["period_seen"].strip() for row in rows)
    assert {row["status"] for row in rows} <= {
        "exploratory",
        "confirmatory-unseen",
        "metadata-only",
    }
    assert all(row["allowed_use"].strip() for row in rows)
    assert any(row["claim_id"] == "PILOT-C14" for row in rows)


def test_prior_knowledge_explicitly_discloses_the_four_main_legacy_expectations():
    text = (Path(__file__).resolve().parents[1] / "prereg/protocol/prior_knowledge.md").read_text(encoding="utf-8").lower()

    for phrase in ("la/lb concentration", "2021 peak", "reform decline", "goods-price asymmetry"):
        assert phrase in text
