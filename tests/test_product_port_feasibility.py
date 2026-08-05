import json

import pandas as pd

from src.acquire import product_port_metadata as acquire
from src.analysis import product_port_feasibility as feasibility


def test_metadata_acquisition_is_hash_resumable_and_outcome_blind(tmp_path, monkeypatch):
    sources = {
        "census_porths_variables.json": {
            "owner": "Census",
            "url": "https://example.test/variables",
            "role": "schema",
            "format": "json",
        },
        "bls_metadata.txt": {
            "owner": "BLS",
            "url": "https://example.test/items",
            "role": "dictionary",
            "format": "text",
        },
        "bls_metadata.xlsx": {
            "owner": "BLS",
            "url": "https://example.test/hierarchy",
            "role": "hierarchy",
            "format": "xlsx",
        },
    }
    payloads = {
        "https://example.test/variables": json.dumps({"variables": {"PORT": {}}}).encode(),
        "https://example.test/items": b"item_code\titem_name\nSEAA01\tTest item\n",
        "https://example.test/hierarchy": b"PK" + b"outcome-blind workbook bytes",
    }
    calls = []
    monkeypatch.setattr(acquire, "OUT", tmp_path)
    monkeypatch.setattr(acquire, "SOURCES", sources)

    acquire.acquire(fetch=lambda url: calls.append(url) or payloads[url])
    acquire.acquire(fetch=lambda _url: (_ for _ in ()).throw(AssertionError("redownloaded")))

    assert len(calls) == len(sources)
    manifest = pd.read_csv(tmp_path / "source_manifest.csv")
    assert set(manifest["artifact"]) == set(sources)
    assert manifest["scope"].str.contains("no trade values or price observations").all()
    assert manifest["sha256"].str.len().eq(64).all()


def test_feasibility_fails_closed_when_schemas_exist_but_shock_and_novelty_do_not():
    decision = feasibility.evaluate_feasibility(
        {"passed": True},
        {"passed": True},
        {"passed": True},
        {
            "validated_port_shock_passed": False,
            "policy_specific_effect_authorized": False,
        },
        {"passed": False},
    )

    assert decision["metadata_preparation_passed"]
    assert decision["status"] == "fail"
    assert not decision["protected_outcome_acquisition_authorized"]
    assert not decision["economics_model_authorized"]
    assert not decision["ns_g9_passed"]


def test_feasibility_only_opens_registration_step_after_fatal_conditions_pass():
    decision = feasibility.evaluate_feasibility(
        {"passed": True},
        {"passed": True},
        {"passed": True},
        {
            "validated_port_shock_passed": True,
            "policy_specific_effect_authorized": True,
        },
        {"passed": False},
    )

    assert decision["status"] == "ready_to_register_product_port_protocol"
    assert decision["protected_outcome_acquisition_authorized"]
    assert not decision["ns_g9_passed"]
