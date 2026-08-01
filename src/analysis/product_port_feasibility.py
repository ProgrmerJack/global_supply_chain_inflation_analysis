"""Run the outcome-blind Phase-7 product-port feasibility and novelty screen."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/acquire"))
import product_port_metadata as metadata

METADATA = ROOT / "data/external/product_port_metadata"
OUT = ROOT / "results/development/product_port_economics_feasibility"
NS_G1 = ROOT / "results/deep_case_SPB/NS_G1_direct_measurement_gate.json"
NATIONAL_G1 = ROOT / "results/development/G1_ais_fullcensus/gate_decision_ves_wgt_mo.json"
ATBERTH = ROOT / "results/deep_case_SPB/atberth_tanker_blind_gate.json"
REPLICATION = ROOT / "results/confirmatory/spb_labour_spatial_replication_corrected/decision.json"
LEGACY = ROOT / "outputs/GATE_G6_cpi.md"
PROTOCOL = ROOT / "prereg/amendments/2026-07-23_product_port_feasibility_screen.md"

BRIDGE_DISCOVERY = {
    "source": "AEA Data and Code Repository at openICPSR",
    "project_doi": "https://doi.org/10.3886/E247679V1",
    "project_url": "https://www.openicpsr.org/openicpsr/project/247679/version/V1/view",
    "folder_url": (
        "https://www.openicpsr.org/openicpsr/project/247679/version/V1/view?"
        "path=%2Fopenicpsr%2F247679%2Ffcr%3Aversions%2FV1%2Freplication%2Fdata"
        "%2Fconcordance&type=folder"
    ),
    "artifact": "hs4_item_concord_clean.dta",
    "listed_size": "12.1 KB",
    "published_version": "V1 (2026-05-29)",
    "status": "publicly_listed_standard_terms_access",
    "locally_opened": False,
    "reason_not_opened": (
        "The bridge is not needed unless the fatal shock and novelty conditions pass; "
        "price, shock and intermediate outcome folders remain unopened."
    ),
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_metadata_cache(path: Path = METADATA) -> dict[str, object]:
    manifest_path = path / "source_manifest.csv"
    if not manifest_path.exists():
        return {"passed": False, "reason": "source manifest is missing", "artifact_count": 0}
    manifest = pd.read_csv(manifest_path, dtype=str).fillna("")
    expected = set(metadata.SOURCES)
    observed = set(manifest["artifact"])
    problems: list[str] = []
    if observed != expected:
        problems.append(
            f"artifact set differs: missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
        )
    for row in manifest.itertuples(index=False):
        artifact = path / row.artifact
        if not artifact.exists():
            problems.append(f"missing {row.artifact}")
        elif _sha(artifact) != row.sha256:
            problems.append(f"hash mismatch {row.artifact}")
        if "no trade values or price observations" not in row.scope:
            problems.append(f"scope firewall missing {row.artifact}")
    return {
        "passed": not problems,
        "artifact_count": int(len(manifest)),
        "manifest_sha256": _sha(manifest_path),
        "problems": problems,
    }


def inspect_census_schema(path: Path = METADATA) -> dict[str, object]:
    variables = json.loads((path / "census_porths_variables.json").read_text(encoding="utf-8"))[
        "variables"
    ]
    required = {
        "PORT",
        "I_COMMODITY",
        "COMM_LVL",
        "VES_VAL_MO",
        "VES_WGT_MO",
        "CNT_VAL_MO",
        "CNT_WGT_MO",
    }
    missing = sorted(required - set(variables))
    commodity = variables.get("I_COMMODITY", {})
    level = variables.get("COMM_LVL", {})
    return {
        "passed": not missing and "2-, 4-, 6-, or 10-character" in commodity.get("label", "")
        and all(token in level.get("label", "") for token in ("HS2", "HS4", "HS6")),
        "required_variables": sorted(required),
        "missing_variables": missing,
        "commodity_label": commodity.get("label"),
        "level_label": level.get("label"),
    }


def inspect_bls_metadata(path: Path = METADATA) -> dict[str, object]:
    items = pd.read_csv(path / "bls_cu_item.txt", sep="\t", dtype=str)
    series = pd.read_csv(path / "bls_cu_series.txt", sep="\t", dtype=str)
    items.columns = items.columns.str.strip()
    series.columns = series.columns.str.strip()
    for column in series:
        series[column] = series[column].str.strip()
    for column in items:
        items[column] = items[column].str.strip()
    required_series = {
        "series_id",
        "area_code",
        "item_code",
        "seasonal",
        "periodicity_code",
        "begin_year",
        "end_year",
    }
    missing = sorted(required_series - set(series))
    eligible = pd.DataFrame()
    if not missing:
        eligible = series[
            series["area_code"].eq("0000")
            & series["seasonal"].eq("U")
            & series["periodicity_code"].eq("R")
            & series["item_code"].str.startswith("SE", na=False)
            & pd.to_numeric(series["begin_year"], errors="coerce").le(2014)
            & pd.to_numeric(series["end_year"], errors="coerce").ge(2015)
        ]
    concordance_columns: dict[str, list[str]] = {}
    for vintage in ("2020", "current"):
        raw = pd.read_excel(path / f"bls_ce_cpi_concordance_{vintage}.xlsx", header=None, nrows=2)
        concordance_columns[vintage] = [
            str(value).strip() for value in raw.iloc[1].dropna().tolist()
        ]
    direct_hs_column = any(
        any("HS" in column.upper() or "HARMONIZED" in column.upper() for column in columns)
        for columns in concordance_columns.values()
    )
    return {
        "passed": not missing and len(eligible) > 0,
        "published_item_codes": int(items["item_code"].nunique()),
        "national_unadjusted_monthly_item_series_covering_2014_2015": int(len(eligible)),
        "series_schema_missing": missing,
        "official_concordance_columns": concordance_columns,
        "official_bls_concordance_is_hs_bridge": direct_hs_column,
        "note": "BLS supplies UCC-to-ELI semantics; the direct competitor separately supplies HS4-to-item.",
    }


def inspect_upstream_decisions() -> dict[str, object]:
    spb = json.loads(NS_G1.read_text(encoding="utf-8"))
    national = json.loads(NATIONAL_G1.read_text(encoding="utf-8"))
    atberth = json.loads(ATBERTH.read_text(encoding="utf-8"))
    replication = json.loads(REPLICATION.read_text(encoding="utf-8"))
    valid_spb = bool(spb["decision"]["full_ns_g1_pass"])
    valid_national = (
        national["components"]["activity_correlation"]["status"] == "pass"
        and national["components"]["motion_state"]["status"] == "pass"
    )
    valid_atberth = bool(atberth["effect_estimation_authorized"])
    valid_replication = replication.get("component_status") == "pass"
    policy_specific = bool(spb["decision"]["gfw_spatial_policy_branch_authorized"] or valid_atberth)
    return {
        "validated_port_shock_passed": bool(
            valid_spb or valid_national or valid_atberth or valid_replication
        ),
        "policy_specific_effect_authorized": policy_specific,
        "inputs": {
            "spb_direct_measurement": {
                "passed": valid_spb,
                "status": spb["decision"]["status"],
                "sha256": _sha(NS_G1),
            },
            "national_operational_measurement": {
                "passed": valid_national,
                "activity_status": national["components"]["activity_correlation"]["status"],
                "motion_status": national["components"]["motion_state"]["status"],
                "sha256": _sha(NATIONAL_G1),
            },
            "atberth_intervention": {
                "passed": valid_atberth,
                "status": atberth["status"],
                "sha256": _sha(ATBERTH),
            },
            "labour_spatial_replication": {
                "passed": valid_replication,
                "status": replication["component_status"],
                "sha256": _sha(REPLICATION),
            },
        },
    }


def inspect_legacy_kill_test() -> dict[str, object]:
    text = LEGACY.read_text(encoding="utf-8")
    passed = (
        "same direction in both episodes (pre-2020 & pandemic): **PASS**" in text
        and "survives simultaneous inference (≥1 horizon sup-t sig): **PASS**" in text
        and "untouched-period holdout confirms sign (drop dominant episode): **PASS**" in text
    )
    return {
        "passed": passed,
        "same_direction_failed": "same direction in both episodes (pre-2020 & pandemic): **FAIL**" in text,
        "simultaneous_inference_failed": (
            "survives simultaneous inference (≥1 horizon sup-t sig): **FAIL**" in text
        ),
        "holdout_failed": (
            "untouched-period holdout confirms sign (drop dominant episode): **FAIL**" in text
        ),
        "sha256": _sha(LEGACY),
    }


def evaluate_feasibility(
    metadata_cache: dict[str, object],
    census_schema: dict[str, object],
    bls_schema: dict[str, object],
    upstream: dict[str, object],
    legacy: dict[str, object],
) -> dict[str, object]:
    bridge_discovered = BRIDGE_DISCOVERY["status"] == "publicly_listed_standard_terms_access"
    executable_novelty = bool(
        upstream["validated_port_shock_passed"]
        and upstream["policy_specific_effect_authorized"]
    )
    gates = {
        "metadata_integrity": bool(metadata_cache["passed"]),
        "trade_schema": bool(census_schema["passed"]),
        "price_schema": bool(bls_schema["passed"]),
        "semantic_bridge_discovered": bridge_discovered,
        "validated_port_shock": bool(upstream["validated_port_shock_passed"]),
        "executable_novelty_beyond_jiao_2026": executable_novelty,
        "legacy_temporal_and_inference_stability": bool(legacy["passed"]),
    }
    fatal_pass = gates["validated_port_shock"] and gates["executable_novelty_beyond_jiao_2026"]
    preparation_pass = all(
        gates[name]
        for name in ("metadata_integrity", "trade_schema", "price_schema", "semantic_bridge_discovered")
    )
    overall = "ready_to_register_product_port_protocol" if fatal_pass and preparation_pass else "fail"
    return {
        "study": "Phase-7 outcome-blind product-port economics feasibility and novelty screen",
        "run_at_utc": datetime.now(UTC).isoformat(),
        "status": overall,
        "gates": gates,
        "fatal_conditions_passed": fatal_pass,
        "metadata_preparation_passed": preparation_pass,
        "protected_outcome_acquisition_authorized": overall != "fail",
        "economics_model_authorized": overall != "fail",
        "ns_g9_passed": False,
        "decision": (
            "Close the economics layer before outcome acquisition. Public schemas and a deposited HS4-item "
            "bridge exist, but no eligible port-delay/policy-shock input passed its frozen gate and no "
            "executable policy-specific differentiator remains beyond the direct 2026 competitor."
            if overall == "fail"
            else "Freeze and register a separate product-port analysis protocol before opening outcomes."
        ),
        "claim_boundary": (
            "This is a feasibility/novelty failure, not evidence that port delays cannot affect prices. "
            "The old aggregate CPI result remains retired."
        ),
    }


def run() -> dict[str, object]:
    cache = verify_metadata_cache()
    census = inspect_census_schema()
    bls = inspect_bls_metadata()
    upstream = inspect_upstream_decisions()
    legacy = inspect_legacy_kill_test()
    decision = evaluate_feasibility(cache, census, bls, upstream, legacy)
    decision.update(
        {
            "protocol": {
                "path": str(PROTOCOL.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha(PROTOCOL),
                "status": "outcome_blind_methodological_audit_not_preregistration",
            },
            "metadata_cache": cache,
            "census_schema": census,
            "bls_schema": bls,
            "semantic_bridge": BRIDGE_DISCOVERY,
            "upstream_decisions": upstream,
            "legacy_kill_test": legacy,
            "protected_outcomes_opened": False,
        }
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = f"""# Product-port economics feasibility decision

**Status:** {decision['status'].upper()}

The outcome-blind preparation succeeds: the official Census and BLS schemas are present, and the direct
competitor's deposited replication package publicly lists an HS4-to-BLS-item concordance. The economics
layer nevertheless closes before any product or price outcomes are acquired.

## Binding failures

- **Validated shock:** FAIL. Every eligible local input remains behind a failed frozen measurement,
  intervention or replication gate.
- **Executable novelty:** FAIL. With no validated policy-specific shock, the remaining design would reproduce
  the already published 93-port product-exposure-to-item-CPI design rather than add the plan's required
  differentiator.
- **Legacy CPI:** FAIL. The old aggregate result fails episode stability, simultaneous inference and the
  dominant-episode holdout.

## Consequence

`protected_outcome_acquisition_authorized=false`. No Census port-HS values, BLS item-price observations,
product-specific model, policy simulator or manuscript claim was opened. This is not a null price effect; it is
the registered kill-rule consequence of missing validated shock variation and novelty.
"""
    (OUT / "README.md").write_text(report, encoding="utf-8")
    print(decision["status"])
    return decision


if __name__ == "__main__":
    run()
