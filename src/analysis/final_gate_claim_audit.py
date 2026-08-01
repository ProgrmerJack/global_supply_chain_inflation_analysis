"""Freeze the post-analysis gate table, claim boundary and current journal decision."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/development/final_gate_claim_audit"

EVIDENCE = {
    "ns_g1": ROOT / "results/deep_case_SPB/NS_G1_direct_measurement_gate.json",
    "freight_boundary": ROOT / "results/development/spb_freight_boundary/summary.json",
    "emissions_gate": (
        ROOT / "results/confirmatory/spb_emissions_component_validation/completion_receipt.json"
    ),
    "air_quality": ROOT / "results/development/spb_ab617_source_aq/feasibility_decision.json",
    "atberth": ROOT / "results/deep_case_SPB/atberth_tanker_blind_gate.json",
    "replication": (
        ROOT / "results/confirmatory/spb_labour_spatial_replication_corrected/decision.json"
    ),
    "economics": (
        ROOT / "results/development/product_port_economics_feasibility/decision.json"
    ),
    "legacy_cpi": ROOT / "outputs/GATE_G6_cpi.md",
    "h1_presence": ROOT / "results/deep_case_SPB/H1_cargo_result.md",
    "route_a_silver": ROOT / "prereg/studies/route_a/pillar_b_route_a_v22_completion_receipt.json",
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_frozen_outputs(
    out: Path = OUT,
    current_input_hashes: dict[str, dict[str, str]] | None = None,
) -> dict[str, object]:
    """Verify an existing audit rather than silently replacing frozen outputs."""
    receipt_path = out / "audit_receipt.json"
    decision_path = out / "decision.json"
    if not receipt_path.exists():
        raise FileNotFoundError(f"frozen audit receipt missing: {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "FINAL_GATE_CLAIM_AUDIT_FROZEN":
        raise RuntimeError("final audit receipt does not declare the frozen status")
    for name, expected in receipt.get("outputs_sha256", {}).items():
        path = out / name
        if not path.exists() or _sha(path) != expected:
            raise RuntimeError(f"frozen final-audit output failed hash verification: {name}")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if current_input_hashes is not None and decision.get("input_hashes") != current_input_hashes:
        raise RuntimeError(
            "upstream evidence differs from the inputs bound to the frozen final audit"
        )
    return decision


def load_gate_evidence() -> dict[str, object]:
    missing = [name for name, path in EVIDENCE.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"final audit evidence missing: {', '.join(missing)}")
    ns_g1 = json.loads(EVIDENCE["ns_g1"].read_text(encoding="utf-8"))
    emissions = json.loads(EVIDENCE["emissions_gate"].read_text(encoding="utf-8"))
    aq = json.loads(EVIDENCE["air_quality"].read_text(encoding="utf-8"))
    atberth = json.loads(EVIDENCE["atberth"].read_text(encoding="utf-8"))
    replication = json.loads(EVIDENCE["replication"].read_text(encoding="utf-8"))
    economics = json.loads(EVIDENCE["economics"].read_text(encoding="utf-8"))
    return {
        "g1": bool(ns_g1["decision"]["full_ns_g1_pass"]),
        "g2": bool(ns_g1["decision"]["gfw_spatial_policy_branch_authorized"]),
        "g3": emissions["gate_status"] == "PASS",
        "g4": bool(aq["ns_g4_passed"]),
        "g5": bool(aq["ns_g4_passed"] and aq["source_model_estimated"]),
        "g6": bool(
            ns_g1["decision"]["gfw_spatial_policy_branch_authorized"]
            or atberth["effect_estimation_authorized"]
        ),
        "g7": bool(replication["ns_g7_passed"]),
        "g8": bool(economics["economics_model_authorized"]),
        "g9": bool(economics["ns_g9_passed"]),
        "g10": bool(
            ns_g1["decision"]["full_ns_g1_pass"]
            and emissions["gate_status"] == "PASS"
            and aq["ns_g4_passed"]
            and (
                ns_g1["decision"]["gfw_spatial_policy_branch_authorized"]
                or atberth["effect_estimation_authorized"]
            )
        ),
        "input_hashes": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha(path),
            }
            for name, path in EVIDENCE.items()
        },
    }


def gate_table(values: dict[str, object]) -> list[dict[str, str]]:
    definitions = [
        ("NS-G1", "Measurement", "A coherent analysed population passes direct external validation",
         "No operational waiting or state-specific claim"),
        ("NS-G2", "Offshore", "Operationally validated offshore reconciliation",
         "Descriptive cargo presence only"),
        ("NS-G3", "Emissions", "Held-out vessel-year-mode emissions validation",
         "Official boundary accounting and conditional scenarios only"),
        ("NS-G4", "Air quality", "Observed source response or appropriately bounded null",
         "No observed source-response or health claim"),
        ("NS-G5", "Equity", "Policy-attributable resident and worker exposure distribution",
         "Baseline inequality and modelled scenarios only"),
        ("NS-G6", "Intervention", "At least one credible causal policy estimate",
         "No policy-effect claim"),
        ("NS-G7", "Replication", "Same mechanism passes an independent episode or gateway",
         "No mechanism generalization"),
        ("NS-G8", "Policy model", "Out-of-sample validated integrated counterfactual model",
         "No policy frontier or prescriptive optimum"),
        ("NS-G9", "Economics", "Unique product-port result beyond current literature",
         "No price channel"),
        ("NS-G10", "Integration", "One validated mechanism links operations through social burden",
         "No coupled sustainability claim"),
    ]
    return [
        {
            "gate": gate,
            "domain": domain,
            "passed": str(bool(values[f"g{index}"])).lower(),
            "requirement": requirement,
            "consequence": consequence,
        }
        for index, (gate, domain, requirement, consequence) in enumerate(definitions, start=1)
    ]


def claim_matrix() -> list[dict[str, str]]:
    return [
        {
            "claim_id": "C01",
            "claim": "Cargo-vessel presence changed across frozen San Pedro Bay distance rings",
            "status": "descriptive_context_only",
            "evidence": "results/deep_case_SPB/H1_cargo_result.md",
            "boundary": "Report absolute vessel-hours and accounting; not waiting, causal policy effect or validation.",
        },
        {
            "claim_id": "C02",
            "claim": "The 2021 queue reform relocated operational waiting",
            "status": "prohibited",
            "evidence": "results/deep_case_SPB/NS_G1_direct_measurement_gate.json",
            "boundary": "Timing and annual-call conditions failed; spatial policy branch was not authorized.",
        },
        {
            "claim_id": "C03",
            "claim": "Absolute AIS-derived vessel emissions are validated",
            "status": "prohibited",
            "evidence": "results/confirmatory/spb_emissions_component_validation/completion_receipt.json",
            "boundary": "Held-out stationary-hours, berth-share and identifiability conditions failed.",
        },
        {
            "claim_id": "C04",
            "claim": "Official SPB freight inventories close the five-sector descriptive boundary",
            "status": "supported_descriptive",
            "evidence": "results/development/spb_freight_boundary/summary.json",
            "boundary": "112/112 published totals reproduce; no AIS validation or policy attribution.",
        },
        {
            "claim_id": "C05",
            "claim": "Observed air quality responds to the registered freight source",
            "status": "not_estimated",
            "evidence": "results/development/spb_ab617_source_aq/feasibility_decision.json",
            "boundary": "No registered-window observations; neither response nor bounded null is supported.",
        },
        {
            "claim_id": "C06",
            "claim": "The intervention changed resident or worker exposure inequality",
            "status": "prohibited",
            "evidence": "results/development/spb_ab617_source_aq/feasibility_decision.json",
            "boundary": "Incremental exposure is downstream of failed source and emissions gates.",
        },
        {
            "claim_id": "C07",
            "claim": "The 2025 CARB At-Berth tanker extension caused an SPB effect",
            "status": "not_estimated",
            "evidence": "results/deep_case_SPB/atberth_tanker_blind_gate.json",
            "boundary": "Geometry and official call-count gates failed before the effect panel opened.",
        },
        {
            "claim_id": "C08",
            "claim": "The 2014–2015 episode independently replicates the relocation mechanism",
            "status": "prohibited",
            "evidence": "results/confirmatory/spb_labour_spatial_replication_corrected/decision.json",
            "boundary": "Only disruption-associated physical accumulation; approach and placebo conditions failed.",
        },
        {
            "claim_id": "C09",
            "claim": "Aggregate congestion has a stable causal consumer-price effect",
            "status": "retired_exploratory",
            "evidence": "outputs/GATE_G6_cpi.md",
            "boundary": "Fails episode stability, simultaneous inference and dominant-episode holdout.",
        },
        {
            "claim_id": "C10",
            "claim": "A new product-port price effect is established",
            "status": "not_estimated",
            "evidence": "results/development/product_port_economics_feasibility/decision.json",
            "boundary": "Shock and novelty gates failed before product and price outcomes opened.",
        },
        {
            "claim_id": "C11",
            "claim": "Integrated policies define a validated sustainability Pareto frontier",
            "status": "prohibited",
            "evidence": "results/development/product_port_economics_feasibility/decision.json",
            "boundary": "No validated intervention or integrated empirical chain exists.",
        },
        {
            "claim_id": "C12",
            "claim": "Scenario emissions and exposure estimates are observed validation",
            "status": "modelled_only",
            "evidence": "docs/deep_case_review_dossier.md",
            "boundary": "Retain explicit modelled/conditional labels; never use as validation or health evidence.",
        },
        {
            "claim_id": "C13",
            "claim": "Route-A computational silver is human validation or Pillar-B passage",
            "status": "prohibited",
            "evidence": "prereg/studies/route_a/pillar_b_route_a_v22_completion_receipt.json",
            "boundary": "Five exploratory computational-silver episodes remain isolated from training and validation.",
        },
    ]


def journal_decision(gates: list[dict[str, str]]) -> dict[str, object]:
    passed = {row["gate"]: row["passed"] == "true" for row in gates}
    nature_sustainability = bool(
        passed["NS-G1"] and passed["NS-G6"] and passed["NS-G10"] and passed["NS-G7"]
    )
    nature_communications = bool(
        passed["NS-G1"] and (passed["NS-G2"] or passed["NS-G3"] or passed["NS-G4"])
    )
    return {
        "nature_sustainability_submission_ready": nature_sustainability,
        "nature_communications_fallback_ready": nature_communications,
        "current_journal_decision": (
            "nature_sustainability"
            if nature_sustainability
            else "nature_communications"
            if nature_communications
            else "stop_current_nature_route"
        ),
        "manuscript_editing_authorized_for_current_nature_route": bool(
            nature_sustainability or nature_communications
        ),
        "reason": (
            "Measurement, both interventions, emissions validation, observed air quality, incremental equity, "
            "replication, economics and integration do not pass. Descriptive assets cannot substitute for "
            "the plan's non-substitutable foundations."
        ),
        "future_reopening_rule": (
            "Only a genuinely new, independently frozen measurement/intervention design with untouched "
            "validation data may reopen the Nature route; closed constructs cannot be retuned."
        ),
    }


def run() -> dict[str, object]:
    evidence = load_gate_evidence()
    if (OUT / "audit_receipt.json").exists():
        decision = verify_frozen_outputs(OUT, evidence["input_hashes"])
        print(decision["journal"]["current_journal_decision"])
        return decision
    gates = gate_table(evidence)
    claims = claim_matrix()
    decision = {
        "study": "Final gate and claim audit for the current Nature-route evidence package",
        "run_at_utc": datetime.now(UTC).isoformat(),
        "gate_count": len(gates),
        "gates_passed": sum(row["passed"] == "true" for row in gates),
        "gate_table": gates,
        "journal": journal_decision(gates),
        "claim_counts": {
            status: sum(row["status"] == status for row in claims)
            for status in sorted({row["status"] for row in claims})
        },
        "input_hashes": evidence["input_hashes"],
        "manuscript_files_modified_by_audit": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    decision_path = OUT / "decision.json"
    claims_path = OUT / "claim_evidence_matrix.csv"
    gates_path = OUT / "gate_table.csv"
    decision_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for path, rows in ((claims_path, claims), (gates_path, gates)):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    report = f"""# Final gate and claim audit

**Current journal decision:** `{decision['journal']['current_journal_decision']}`

All ten Nature-programme gates are closed for the current evidence package. The required measurement,
credible-intervention and integrated-system foundations do not pass; the Nature Sustainability route therefore
stops under the plan's own rule. The narrower Nature Communications fallback is also not submission-ready
because no validated headline measurement or environmental effect survived.

The claim matrix preserves the useful record without laundering it into stronger evidence:

- descriptive cargo-presence accounting and the reproduced five-sector official freight boundary remain usable;
- scenario emissions/exposure remain explicitly modelled and conditional;
- operational waiting relocation, causal intervention, validated absolute emissions, observed AQ/health,
  incremental equity, mechanism replication, product-price effects and a policy frontier are not authorized;
- Route-A computational silver remains isolated from human validation and classifier decisions.

No manuscript file was edited. Reopening the Nature route requires a genuinely new, independently frozen
measurement/intervention design with untouched validation data; it cannot be achieved by retuning a closed
construct.
"""
    (OUT / "README.md").write_text(report, encoding="utf-8")
    receipt = {
        "status": "FINAL_GATE_CLAIM_AUDIT_FROZEN",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "outputs_sha256": {
            path.name: _sha(path) for path in (decision_path, claims_path, gates_path, OUT / "README.md")
        },
    }
    (OUT / "audit_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(decision["journal"]["current_journal_decision"])
    return decision


if __name__ == "__main__":
    run()
