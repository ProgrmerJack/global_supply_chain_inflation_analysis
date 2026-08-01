"""Re-audit the stopped Nature route without altering any frozen decision.

This is a scientific-status audit, not a gate rerun. It distinguishes:

* a real failure of the exact registered construct;
* a broader conclusion invalidated by acquisition or construct mismatch;
* a gate that was never independently fired; and
* an upstream-blocked extension that was incorrectly summarized as failed.

Run:
    python src/analysis/nature_route_failure_reaudit.py
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from src.analysis import final_gate_claim_audit, h1_offshore_cargo, h6_labour_spatial_replication
except ModuleNotFoundError:  # direct script execution from the repository root
    import final_gate_claim_audit
    import h1_offshore_cargo
    import h6_labour_spatial_replication

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/development/nature_route_failure_reaudit"
EVIDENCE = {
    "original_final_audit": ROOT / "results/development/final_gate_claim_audit/decision.json",
    "direct_measurement": ROOT / "results/deep_case_SPB/NS_G1_direct_measurement_gate.json",
    "direct_measurement_lags": ROOT / "results/deep_case_SPB/NS_G1_direct_measurement_lags.csv",
    "emissions": ROOT / "results/confirmatory/spb_emissions_component_validation/one_shot_gate.json",
    "ab617_old": ROOT / "results/development/spb_ab617_source_aq/feasibility_decision.json",
    "ab617_site9": ROOT / "data/external/ab617_wcwlb_observations/raw/site_9.html",
    "aqview_history": (
        ROOT / "data/external/ab617_wcwlb_metadata/aqview_historical_feasibility.json"
    ),
    "atberth": ROOT / "results/deep_case_SPB/atberth_tanker_blind_gate.json",
    "replication": (
        ROOT / "results/confirmatory/spb_labour_spatial_replication_corrected/decision.json"
    ),
    "replication_daily_panel": (
        ROOT / "results/confirmatory/spb_labour_spatial_replication_corrected/daily_physical_panel.csv"
    ),
    "economics": ROOT / "results/development/product_port_economics_feasibility/decision.json",
    "atberth_source": ROOT / "src/analysis/atberth_tanker_event.py",
    "call_segmentation_source": ROOT / "src/process_ais/port_call_segmentation.py",
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(name: str) -> dict:
    return json.loads(EVIDENCE[name].read_text(encoding="utf-8"))


def detect_atberth_construct_mismatch(
    atberth_source: str,
    segmentation_source: str,
    official_measure: str,
) -> dict[str, bool]:
    """Detect the frozen in-port-gap versus sea-arrival construct mismatch."""
    old_geometry_block = atberth_source
    if "def berth_geometries" in atberth_source:
        old_geometry_block = atberth_source.split("def berth_geometries", 1)[1]
        if "def mark_berth_pings" in old_geometry_block:
            old_geometry_block = old_geometry_block.split("def mark_berth_pings", 1)[0]
    return {
        "official_unit_is_sea_arrival": "from sea to berth or anchorage" in official_measure,
        "ais_unit_uses_in_port_gap_segmentation": (
            "assign_port_call_ids(pings)" in atberth_source
            and "gap.gt(gap_hours)" in segmentation_source
        ),
        "primary_geometry_omits_frozen_terminal_points": (
            'state.eq("berth")' in old_geometry_block
            and "carb_atberth_spb_tanker_terminals.csv" not in old_geometry_block
        ),
    }


def reproduce_registered_failures(
    g1: dict[str, object],
    emissions: dict[str, object],
    replication: dict[str, object],
) -> dict[str, object]:
    """Recompute the decisive statistics without invoking any write-once driver."""
    daily = h1_offshore_cargo.speed_bin_daily_panel()
    weekly = h1_offshore_cargo.bts_weekly_panel(daily)
    g1_gate, _ = h1_offshore_cargo.evaluate_bts_gate(weekly, draws=10_000)
    annual_calls, _ = h1_offshore_cargo.annual_call_check()
    frozen_g1 = g1["gfw_bts_aggregate_operational_relevance"]
    g1_exact = (
        g1_gate == frozen_g1
        and annual_calls == g1["annual_container_call_check"]
    )

    panel = pd.read_csv(EVIDENCE["replication_daily_panel"], parse_dates=["date"])
    primary_result, primary_terms = h6_labour_spatial_replication.fit_effect(
        panel, np.log1p(panel["low_0-50nm"])
    )
    speed_outcome = (
        h6_labour_spatial_replication._baseline_z(panel, "low_0-50nm")
        - h6_labour_spatial_replication._baseline_z(panel, "movement_0-50nm")
    )
    _, speed_terms = h6_labour_spatial_replication.fit_effect(panel, speed_outcome)
    approach_outcome = (
        h6_labour_spatial_replication._baseline_z(panel, "low_west_0_300")
        - h6_labour_spatial_replication._baseline_z(
            panel, "low_north_south_mean_0_300"
        )
    )
    _, approach_terms = h6_labour_spatial_replication.fit_effect(panel, approach_outcome)

    def _term(frame: pd.DataFrame, name: str) -> dict[str, float]:
        row = frame.set_index("term").loc[name]
        return {key: float(row[key]) for key in ("beta", "standard_error", "ci_low", "ci_high", "p_value")}

    primary = _term(primary_terms, "disruption")
    speed = _term(speed_terms, "disruption")
    approach = _term(approach_terms, "disruption")
    frozen_primary = next(
        row for row in replication["primary_log1p_effects"] if row["term"] == "disruption"
    )
    frozen_speed = next(
        row for row in replication["speed_specificity_effects"] if row["term"] == "disruption"
    )
    frozen_approach = next(
        row for row in replication["approach_specificity_effects"] if row["term"] == "disruption"
    )
    replication_exact = all(
        np.isclose(recomputed[key], frozen[key], rtol=0, atol=1e-12)
        for recomputed, frozen in (
            (primary, frozen_primary),
            (speed, frozen_speed),
            (approach, frozen_approach),
        )
        for key in recomputed
    )

    metrics = emissions["metrics"]
    hours_error = 100 * (
        metrics["ais_stationary_freight_vessel_hours"]
        / metrics["official_stationary_freight_vessel_hours"] - 1
    )
    berth_error = 100 * (
        metrics["ais_berth_share_resolved"] - metrics["official_berth_share_resolved"]
    )
    emissions_arithmetic_exact = (
        np.isclose(hours_error, metrics["stationary_hours_error_pct"], rtol=0, atol=1e-12)
        and np.isclose(
            berth_error,
            metrics["berth_share_error_percentage_points"],
            rtol=0,
            atol=1e-12,
        )
    )
    if not (g1_exact and replication_exact and emissions_arithmetic_exact):
        raise RuntimeError("an independently recomputed registered failure no longer matches its receipt")
    return {
        "g1_exact": True,
        "g1_observations": int(g1_gate["n_bts_observations"]),
        "g1_low_pearson": g1_gate["estimates"]["low_pearson"],
        "g1_low_spearman": g1_gate["estimates"]["low_spearman"],
        "g1_best_lags": g1_gate["best_gfw_shift_observations"],
        "g1_annual_calls_exact": True,
        "emissions_arithmetic_exact": True,
        "emissions_stationary_hours_error_pct": hours_error,
        "emissions_berth_share_error_pp": berth_error,
        "replication_exact": True,
        "replication_primary_disruption_beta": primary["beta"],
        "replication_approach_disruption_beta": approach["beta"],
        "replication_disruption_minus_recovery": (
            h6_labour_spatial_replication._contrast(
                primary_result, "disruption", "recovery"
            )["estimate"]
        ),
    }


def build_reaudit() -> dict[str, object]:
    missing = [name for name, path in EVIDENCE.items() if not path.exists()]
    if missing:
        raise FileNotFoundError("re-audit evidence missing: " + ", ".join(missing))

    original = _load_json("original_final_audit")
    g1 = _load_json("direct_measurement")
    emissions = _load_json("emissions")
    ab617 = _load_json("ab617_old")
    aqview = _load_json("aqview_history")
    atberth = _load_json("atberth")
    replication = _load_json("replication")
    economics = _load_json("economics")
    reproductions = reproduce_registered_failures(g1, emissions, replication)
    mismatch = detect_atberth_construct_mismatch(
        EVIDENCE["atberth_source"].read_text(encoding="utf-8"),
        EVIDENCE["call_segmentation_source"].read_text(encoding="utf-8"),
        atberth["official_2024_comparator"]["measure"],
    )

    if original.get("journal", {}).get("current_journal_decision") != "stop_current_nature_route":
        raise RuntimeError("unexpected original journal decision")
    if emissions.get("status") != "FAIL":
        raise RuntimeError("emissions evidence no longer matches the frozen failed gate")
    site9 = EVIDENCE["ab617_site9"].read_text(encoding="utf-8", errors="ignore")
    if not (
        ab617.get("in_window_observations") == 0
        and aqview.get("historical_window_feasible") is True
        and aqview.get("no2_hourly_records_in_window", 0) >= 20_000
        and "/AB617CommunityAirMonitoring/Home/HistoricalSearch/9" in site9
    ):
        raise RuntimeError("AQview evidence does not establish the acquisition-path contradiction")
    if not all(mismatch.values()):
        raise RuntimeError("At-Berth source no longer exhibits the audited construct mismatch")
    if "policy_model" in final_gate_claim_audit.EVIDENCE:
        raise RuntimeError("original final audit now has independent policy-model evidence; re-audit required")

    gates = [
        {
            "gate": "NS-G1",
            "original_summary": "failed",
            "reaudit_class": "REGISTERED_CONSTRUCT_FAILURE_CONFIRMED",
            "bug_status": "no numerical bug found",
            "correct_interpretation": (
                "The frozen GFW/BTS timing rule and mismatched annual cargo-versus-container-call "
                "check failed and the numerical result reproduces exactly. The timing rule selects "
                "the peak cross-correlation of autocorrelated level series, so it is a brittle "
                "construct-validity test rather than evidence of a coding error. This closes that "
                "registered queue proxy; it does not invalidate directly observed speed, time, or "
                "physical presence."
            ),
        },
        {
            "gate": "NS-G2",
            "original_summary": "failed/not passed",
            "reaudit_class": "UPSTREAM_BLOCKED_NOT_INDEPENDENTLY_FIRED",
            "bug_status": "programme-status overreach",
            "correct_interpretation": (
                "The operational relocation extension was not admissibly fired after NS-G1. "
                "Cargo-presence accounting remains descriptive evidence, not a failed causal estimate."
            ),
        },
        {
            "gate": "NS-G3",
            "original_summary": "failed",
            "reaudit_class": "REGISTERED_FAILURE_CONFIRMED",
            "bug_status": "no implementation bug found",
            "correct_interpretation": (
                f"The held-out gate genuinely failed: stationary-hours error "
                f"{emissions['metrics']['stationary_hours_error_pct']:.3f}%, berth-share error "
                f"{emissions['metrics']['berth_share_error_percentage_points']:.3f} percentage points, and "
                "class-by-control emissions were not identifiable from published marginal tables."
            ),
        },
        {
            "gate": "NS-G4",
            "original_summary": "failed feasibility",
            "reaudit_class": "SCIENTIFIC_FAILURE_INVALIDATED_BY_ACQUISITION_BUG",
            "bug_status": "wrong official access path",
            "correct_interpretation": (
                "The frozen SCAQMD latest-chart acquisition returned no 2020-2024 values, but CARB "
                f"AQview independently reports {aqview['no2_hourly_records_in_window']:,} hourly NO2 "
                "records in that window; the retained site response itself links to a separate "
                "HistoricalSearch path. The old retrieval remains closed; historical feasibility "
                "requires a new independently frozen acquisition."
            ),
        },
        {
            "gate": "NS-G5",
            "original_summary": "failed/not passed",
            "reaudit_class": "UPSTREAM_BLOCKED_NOT_FIRED",
            "bug_status": "incorrectly inherited NS-G4 failure",
            "correct_interpretation": (
                "Baseline resident/workplace disparity was descriptive. Policy-attributable equity "
                "was never estimated because the environmental contrast was unavailable."
            ),
        },
        {
            "gate": "NS-G6",
            "original_summary": "both intervention routes failed",
            "reaudit_class": "MIXED_REAL_QUEUE_FAILURE_AND_INVALID_ATBERTH_MEASUREMENT",
            "bug_status": "At-Berth call unit and geometry mismatch",
            "correct_interpretation": (
                "The queue route genuinely failed its exact registered timing rule. The At-Berth run "
                "also correctly failed its frozen algorithm, but that algorithm counted >24-hour gaps "
                "inside truncated port tracks against one sea-to-anchorage/berth official arrival and "
                "did not use the frozen tanker-terminal points in the primary geometry gate. Its "
                "broader infeasibility conclusion is invalid."
            ),
        },
        {
            "gate": "NS-G7",
            "original_summary": "failed",
            "reaudit_class": "REGISTERED_FAILURE_CONFIRMED",
            "bug_status": "original index bug corrected before the valid run",
            "correct_interpretation": (
                f"The corrected run genuinely failed approach and placebo specificity despite a "
                f"{replication['primary_percent_effect']:.1f}% near-port low-speed increase. It supports "
                "disruption-associated accumulation, not the same relocation mechanism."
            ),
        },
        {
            "gate": "NS-G8",
            "original_summary": "failed/not passed",
            "reaudit_class": "NOT_FIRED_AND_FINAL_AUDIT_MAPPING_BUG",
            "bug_status": "mapped to economics_model_authorized",
            "correct_interpretation": (
                "No out-of-sample policy simulator was built or tested. The original final audit used "
                "the economics feasibility flag as NS-G8 evidence, which is conceptually wrong."
            ),
        },
        {
            "gate": "NS-G9",
            "original_summary": "failed",
            "reaudit_class": "OUTCOME_BLIND_FEASIBILITY_CLOSURE_CONFIRMED",
            "bug_status": "no protected outcome opened",
            "correct_interpretation": (
                "The optional product-price extension appropriately stopped because no validated "
                "policy-specific shock survived and the generic bridge overlaps current deposited work."
            ),
        },
        {
            "gate": "NS-G10",
            "original_summary": "failed/not passed",
            "reaudit_class": "UPSTREAM_BLOCKED_NOT_FIRED",
            "bug_status": "logical conjunction summarized as scientific failure",
            "correct_interpretation": (
                "No integrated model was fired. The gate is unready because upstream mechanisms are "
                "unvalidated; there is no independent negative integration result."
            ),
        },
    ]
    return {
        "study": "Nature-route failure re-audit",
        "status": "CURRENT_PACKAGE_NOT_SUBMISSION_READY_BUT_GLOBAL_FAILURE_VERDICT_SUPERSEDED",
        "old_frozen_audit_preserved": True,
        "current_nature_sustainability_ready": False,
        "nature_route_scientifically_dead": False,
        "central_finding": (
            "The current package is not Nature Sustainability-ready, but the 0/10 'all gates failed' "
            "summary conflated genuine registered failures with an acquisition bug, a construct "
            "mismatch, upstream blocking, and a gate-mapping error."
        ),
        "atberth_construct_checks": mismatch,
        "independent_reproduction": reproductions,
        "economics_feasibility_status": economics.get("decision"),
        "g1_exact_registered_status": g1["decision"]["status"],
        "gates": gates,
        "input_hashes": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha(path),
            }
            for name, path in EVIDENCE.items()
        },
    }


def _report(decision: dict[str, object]) -> str:
    reproduced = decision["independent_reproduction"]
    rows = "\n".join(
        f"| {row['gate']} | {row['reaudit_class']} | {row['bug_status']} | "
        f"{row['correct_interpretation']} |"
        for row in decision["gates"]
    )
    return f"""# Nature-route failure re-audit

**Status:** `{decision['status']}`

{decision['central_finding']}

The immutable earlier audit is preserved. This document supersedes only its programme-wide interpretation;
it does not turn a failed registered construct into a pass or inspect any protected outcome.

## Independent numerical reproduction

The audit calls the pure analysis functions and reads the retained panels without invoking any write-once
driver. It exactly reproduces:

* NS-G1: {reproduced['g1_observations']} observations, low-speed Pearson
  {reproduced['g1_low_pearson']:.6f}, Spearman {reproduced['g1_low_spearman']:.6f}, and best shifts
  +{reproduced['g1_best_lags']['pearson']}/+{reproduced['g1_best_lags']['spearman']} observations;
* NS-G3 arithmetic: stationary-hours error
  {reproduced['emissions_stationary_hours_error_pct']:.6f}% and berth-share error
  {reproduced['emissions_berth_share_error_pp']:.6f} percentage points;
* NS-G7: disruption coefficient {reproduced['replication_primary_disruption_beta']:.6f} and
  approach-specificity coefficient {reproduced['replication_approach_disruption_beta']:.6f}.

| Gate | Re-audit class | Bug status | Correct interpretation |
| --- | --- | --- | --- |
{rows}

## Journal consequence

The evidence package is still not ready for Nature Sustainability today. However, the route is not
scientifically exhausted: the public historical air-quality source exists, and the At-Berth intervention can
be re-tested only through a genuinely new, prospectively frozen sea-to-port trajectory and official-terminal
design. The failed G1, emissions and 2014–2015 constructs remain closed exactly as registered.
"""


def main() -> None:
    decision = build_reaudit()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "decision.json").write_text(
        json.dumps(decision, indent=2) + "\n", encoding="utf-8"
    )
    with (OUT / "gate_reaudit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(decision["gates"][0]))
        writer.writeheader()
        writer.writerows(decision["gates"])
    (OUT / "report.md").write_text(_report(decision), encoding="utf-8")
    print(decision["status"])


if __name__ == "__main__":
    main()
