"""Tests for the cutoff-bounded novelty search record."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_search_log_records_every_registered_family_and_access_limit():
    with (ROOT / "docs/search_log.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert set(reader.fieldnames or []) == {
        "query_id",
        "query_string",
        "engine",
        "run_date",
        "novelty_cutoff",
        "result_count",
        "screened_count",
        "included_competitor_ids",
        "screening_status",
        "notes",
    }
    assert {row["query_id"] for row in rows} == {f"S{i:02d}" for i in range(1, 28)}
    assert all(row["query_string"].strip() and row["engine"].strip() for row in rows)
    assert all(row["novelty_cutoff"] == "2026-06-30" for row in rows)
    assert all(row["result_count"].isdigit() or row["result_count"] == "not-run" for row in rows)
    assert next(row for row in rows if row["query_id"] == "S13")["screening_status"] == (
        "replication-material-audit-complete"
    )
    assert "not_exported" not in (ROOT / "docs/search_log.csv").read_text(encoding="utf-8")


def test_competitor_matrix_exposes_overlap_and_novelty_status():
    with (ROOT / "docs/competitor_matrix.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert set(reader.fieldnames or []) == {
        "competitor_id",
        "citation_or_source",
        "year",
        "geography",
        "data",
        "identification",
        "outcomes",
        "policy",
        "equity",
        "overlap_level",
        "required_differentiation",
        "novelty_status",
    }
    assert {row["competitor_id"] for row in rows} >= {
        "COMP-01",
        "COMP-02",
        "COMP-03",
        "COMP-04",
        "COMP-05",
        "COMP-06",
        "COMP-11",
        "COMP-12",
        "COMP-14",
        "COMP-15",
        "COMP-16",
        "COMP-17",
        "COMP-18",
        "COMP-19",
        "COMP-20",
        "COMP-21",
    }
    assert {row["overlap_level"] for row in rows} <= {
        "component",
        "substantial",
        "project-displacing",
    }
    assert {row["novelty_status"] for row in rows} <= {"constraint", "project-displacing"}
    assert all(row["required_differentiation"].strip() for row in rows)
