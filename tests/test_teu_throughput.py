"""G1-v2 matched-comparator registry + official-series adapter (teu_throughput.py)."""

import os
import sys

import pandas as pd
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)
REPO = os.path.join(os.path.dirname(__file__), "..")


def test_registry_population_is_external_not_correlation_selected():
    from process_ais.teu_throughput import load_comparator_registry

    reg = load_comparator_registry(os.path.join(REPO, "config", "registries", "g1v2_comparator_registry.csv"))
    complexes = set(reg.complex_id)
    # container gateways included
    assert {"san_pedro_bay", "new_york_new_jersey", "savannah_ga", "houston_tx", "charleston_sc"} <= complexes
    # Mobile had the STRONGEST development correlation but is NOT a container gateway -> excluded (proves
    # the population is defined from external criteria, not observed correlations)
    assert "mobile_al" not in complexes and "new_orleans_la" not in complexes
    # primary = calls, secondary = TEU declared
    assert (reg.primary_or_secondary == "primary").any() and (reg.primary_or_secondary == "secondary").any()
    assert reg.ais_metric_matched.str.contains("call|capacity", case=False).all()


def test_ingest_and_assemble_round_trip(tmp_path):
    from process_ais.teu_throughput import ingest_official_series, assemble_official

    raw = tmp_path / "raw_savannah.csv"
    raw.write_text("year_month,value\n2021-01,300000\n2021-02,310000\n", encoding="utf-8")
    dest = ingest_official_series("savannah_ga", "CONTAINER_TEU_TOTAL", raw,
                                  source="Georgia Ports Authority", access_date="2026-07-14",
                                  official_dir=tmp_path / "official")
    assert dest.exists()
    manifest = pd.read_csv(tmp_path / "official" / "ingestion_manifest.csv")
    assert manifest.loc[0, "n_months"] == 2 and len(str(manifest.loc[0, "sha256"])) == 64

    registry = pd.DataFrame({
        "complex_id": ["savannah_ga", "charleston_sc"],
        "official_metric": ["CONTAINER_TEU_TOTAL", "CONTAINER_TEU_TOTAL"],
        "unit": ["TEU", "TEU"], "primary_or_secondary": ["primary", "primary"],
        "official_source": ["GPA", "SCPA"], "ais_metric_matched": ["capacity", "capacity"],
    })
    long, cov = assemble_official(registry, official_dir=tmp_path / "official")
    assert len(long) == 2 and set(long.complex_id) == {"savannah_ga"}   # only the ingested one present
    assert cov.set_index("complex_id").loc["savannah_ga", "present"]
    assert not cov.set_index("complex_id").loc["charleston_sc", "present"]   # awaiting fetch


def test_ingest_rejects_bad_month(tmp_path):
    from process_ais.teu_throughput import ingest_official_series

    raw = tmp_path / "bad.csv"
    raw.write_text("year_month,value\n2021,300000\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ingest_official_series("x", "CONTAINER_TEU_TOTAL", raw, source="s", official_dir=tmp_path / "o")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
