"""Outcome-free checks for the separately registered G1-v2 preparation package."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def test_g1_v2_draft_uses_only_complete_current_ais_coverage_without_comparator_values():
    registry = pd.read_csv(ROOT / "config/registries/g1_v2_comparator_registry_draft.csv")
    panel = pd.read_csv(ROOT / "data/processed/national_activity_month.csv")

    assert registry.registry_status.eq("draft_not_frozen").all()
    assert registry.retrieval_status.eq("no comparator values retrieved").all()
    assert registry.official_unit.eq("TEU").all()
    assert registry.source_metadata_url.str.startswith("https://").all()

    coverage = panel.groupby("port_complex_id").year_month.agg(["nunique", "min", "max"])
    selected = coverage.loc[registry.gateway_id]
    assert selected["nunique"].eq(132).all()
    assert selected["min"].eq("2015-01").all()
    assert selected["max"].eq("2025-12").all()
