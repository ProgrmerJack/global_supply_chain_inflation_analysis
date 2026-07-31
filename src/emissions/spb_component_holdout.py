"""Fire the registered 2018 SPB freight-OGV component gate exactly once.

This wrapper is intentionally separate from the hashed 2019-2024 development
extractor. It validates that frozen artifact, the public OSF receipt, and its own
pre-access freeze before it can parse any protected 2018 table value.

Run once: python src/emissions/spb_component_holdout.py fire
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pdfplumber
from pypdf import PdfReader

try:
    from . import spb_component_validation as dev
except ImportError:  # direct script execution
    import spb_component_validation as dev

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/external/spb_emissions_inventories"
MODE_FILE = ROOT / "data/processed/ais_dwell_census_mode/monthly_mode_time.csv"
COVERAGE_FILE = ROOT / "data/processed/ais_dwell_census_mode/month_manifest.csv"
DEVELOPMENT_FREEZE = ROOT / "prereg/studies/spb_emissions/spb_emissions_component_validation_development_freeze.json"
EXTERNAL_RECEIPT = ROOT / "prereg/studies/spb_emissions/spb_emissions_component_validation_external_timestamp.json"
EXECUTION_FREEZE = ROOT / "prereg/studies/spb_emissions/spb_emissions_component_validation_holdout_execution_freeze.json"
OUT = ROOT / "results/confirmatory/spb_emissions_component_validation"
GATE_FILE = OUT / "one_shot_gate.json"

STATIONARY_ERROR_MAX_PCT = 10.0
BERTH_SHARE_ERROR_MAX_POINTS = 10.0
EMISSIONS_ERROR_MAX_PCT = 20.0
CLASS_SPEARMAN_MIN = 0.80
MIN_CLASSES = 5
MIN_MONTHLY_SOURCE_COVERAGE = 0.95
MAX_UNRESOLVED_SHARE = 0.10


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validated_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"required freeze/receipt is absent: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def preflight(output_dir: Path = OUT) -> None:
    """Fail closed unless all registered access conditions still hold."""
    external = _validated_json(EXTERNAL_RECEIPT)
    if (
        external.get("registration_id") != "p5vqs"
        or external.get("registration_url") != "https://osf.io/p5vqs/"
        or external.get("verified_public") is not True
        or external.get("verified_revision_state") != "approved"
    ):
        raise RuntimeError("public OSF registration receipt is not approved and binding")

    development = _validated_json(DEVELOPMENT_FREEZE)
    if development.get("status") != "DEVELOPMENT_EXECUTABLE_FROZEN_PROTECTED_2018_VALUES_UNOPENED":
        raise RuntimeError("development freeze does not preserve the unopened holdout state")
    for relative, expected in development.get("sha256", {}).items():
        path = ROOT / relative
        if not path.exists() or _sha256(path) != expected:
            raise RuntimeError(f"development artifact changed after freeze: {relative}")

    execution = _validated_json(EXECUTION_FREEZE)
    if execution.get("status") != "HOLDOUT_EXECUTABLE_FROZEN_2018_VALUES_UNOPENED":
        raise RuntimeError("holdout execution freeze is absent or invalid")
    if _sha256(Path(__file__)) != execution.get("holdout_executable_sha256"):
        raise RuntimeError("holdout executable changed after its pre-access freeze")
    if _sha256(DEVELOPMENT_FREEZE) != execution.get("development_freeze_sha256"):
        raise RuntimeError("holdout execution freeze does not bind the development freeze")
    if _sha256(EXTERNAL_RECEIPT) != execution.get("external_receipt_sha256"):
        raise RuntimeError("holdout execution freeze does not bind the OSF receipt")

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"one-shot holdout artifacts already exist: {output_dir}")
    dev.verify_archive()


def _holdout_report(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    match = re.fullmatch(r"(pola|polb)_2018_air_emissions_inventory\.pdf", path.name)
    if not match:
        raise RuntimeError("holdout extractor accepts only a frozen 2018 port inventory")
    port = dev.PORTS[match.group(1)]
    pages = [page.extract_text() or "" for page in PdfReader(path).pages]
    layout_pages: list[str] | None = None

    def get_table(name: str) -> tuple[str, int]:
        nonlocal layout_pages
        try:
            return dev._table(pages, name)
        except RuntimeError as primary_error:
            if layout_pages is None:
                with pdfplumber.open(path) as report:
                    layout_pages = [page.extract_text() or "" for page in report.pages]
            try:
                return dev._table(layout_pages, name)
            except RuntimeError:
                raise RuntimeError(f"{path.name}: {primary_error}") from primary_error

    activity, activity_page = get_table("activity")
    aux, aux_page = get_table("aux")
    boiler, boiler_page = get_table("boiler")
    berth, berth_page = get_table("berth")
    anchor, anchor_page = get_table("anchor")
    emissions, emissions_page = get_table("type_emissions")
    frames = [
        dev._rows_frame(activity, activity_page, 4, {"arrivals": 0}),
        dev._rows_frame(aux, aux_page, 4, {"aux_berth_kw": 2, "aux_anchor_kw": 3}),
        dev._rows_frame(boiler, boiler_page, 4, {"boiler_berth_kw": 2, "boiler_anchor_kw": 3}),
        dev._rows_frame(berth, berth_page, 3, {"mean_berth_hours": 2}),
        dev._rows_frame(anchor, anchor_page, 4, {"mean_anchor_hours": 2, "anchor_count": -1}),
    ]
    merged = frames[0].drop(columns="page")
    page_columns = {
        "activity_page": activity_page,
        "aux_page": aux_page,
        "boiler_page": boiler_page,
        "berth_page": berth_page,
        "anchor_page": anchor_page,
    }
    for frame in frames[1:]:
        merged = merged.merge(
            frame.drop(columns=["official_class", "page"]), on="detail", how="outer",
            validate="one_to_one"
        )
    merged["official_class"] = merged["detail"].map(dev._official_class)
    required = [
        "arrivals", "aux_berth_kw", "aux_anchor_kw", "boiler_berth_kw", "boiler_anchor_kw",
        "mean_berth_hours", "mean_anchor_hours", "anchor_count",
    ]
    merged["component_complete"] = merged[required].notna().all(axis=1)
    merged["official_berth_hours"] = merged["arrivals"] * merged["mean_berth_hours"]
    merged["official_anchor_hours"] = merged["anchor_count"] * merged["mean_anchor_hours"]
    merged["port"] = port
    merged["year"] = 2018
    merged["source_file"] = path.name
    merged["source_sha256"] = _sha256(path)
    for column, value in page_columns.items():
        merged[column] = value
    merged["included_in_matched_freight_population"] = (
        merged["official_class"].notna() & merged["arrivals"].notna() & merged["component_complete"]
    )
    merged["crosswalk_decision"] = "EXCLUDED_NONFREIGHT_OFFICIAL_CLASS"
    merged.loc[
        merged["official_class"].notna() & merged["arrivals"].isna(), "crosswalk_decision"
    ] = "EXCLUDED_NO_REPORTED_ACTIVITY"
    merged.loc[
        merged["official_class"].notna() & merged["arrivals"].notna()
        & ~merged["component_complete"], "crosswalk_decision"
    ] = "ERROR_INCOMPLETE_REQUIRED_COMPONENTS"
    merged.loc[
        merged["included_in_matched_freight_population"], "crosswalk_decision"
    ] = "INCLUDED_MATCHED_FREIGHT_CLASS"

    complete = merged.loc[merged["included_in_matched_freight_population"]].copy()
    aggregate = complete.groupby(
        ["port", "year", "official_class", "source_file", "source_sha256"], as_index=False
    ).agg(
        arrivals=("arrivals", "sum"),
        official_berth_hours=("official_berth_hours", "sum"),
        anchor_count=("anchor_count", "sum"),
        official_anchor_hours=("official_anchor_hours", "sum"),
        detail_rows=("detail", "count"),
    )
    checks = pd.DataFrame(dev._published_total_check(emissions, emissions_page))
    checks.insert(0, "year", 2018)
    checks.insert(0, "port", port)
    checks["source_file"] = path.name
    checks["source_sha256"] = _sha256(path)

    headings = []
    for page in pages:
        headings.extend(
            " ".join(line.split()) for line in page.splitlines()
            if re.match(r"^Table\s+\d+\.\s*\d+:", " ".join(line.split()), re.I)
        )
    audit_columns = [
        "port", "year", "detail", "official_class", "included_in_matched_freight_population",
        "crosswalk_decision", "component_complete", "arrivals", "mean_berth_hours",
        "official_berth_hours", "anchor_count", "mean_anchor_hours", "official_anchor_hours",
        "aux_berth_kw", "aux_anchor_kw", "boiler_berth_kw", "boiler_anchor_kw",
        "activity_page", "aux_page", "boiler_page", "berth_page", "anchor_page",
        "source_file", "source_sha256",
    ]
    return aggregate, checks, merged[audit_columns].copy(), headings


def _class_control_candidates(headings: list[str]) -> list[str]:
    control = re.compile(r"shore power|capture|caecs|vessel boarding program|vbp", re.I)
    grouping = re.compile(r"vessel type|vessel class|class", re.I)
    return sorted({heading for heading in headings if control.search(heading) and grouping.search(heading)})


def _monthly_ais() -> tuple[pd.DataFrame, float]:
    modes = pd.read_csv(MODE_FILE)
    modes = modes.loc[
        modes["Port"].eq("LA_Long_Beach") & modes["YearMonth"].astype(str).str.startswith("2018-")
    ].copy()
    if sorted(modes["YearMonth"].unique()) != [f"2018-{month:02d}" for month in range(1, 13)]:
        raise RuntimeError("AIS holdout does not contain all twelve 2018 months")
    monthly = modes.groupby("YearMonth", as_index=False).agg(
        berth_hours=("berth_hours", "sum"),
        anchor_hours=("anchor_hours", "sum"),
        unresolved_stationary_hours=("unknown_hoteling_hours", "sum"),
        total_interval_hours=("total_mode_hours", "sum"),
        unique_vessels=("MMSI", "nunique"),
    )
    monthly["stationary_hours"] = monthly[
        ["berth_hours", "anchor_hours", "unresolved_stationary_hours"]
    ].sum(axis=1)

    coverage = pd.read_csv(COVERAGE_FILE)
    coverage = coverage.loc[coverage["YearMonth"].astype(str).str.startswith("2018-")].copy()
    if len(coverage) != 12 or coverage["YearMonth"].duplicated().any():
        raise RuntimeError("source-date coverage must contain one row per 2018 month")
    coverage["source_date_coverage"] = coverage["days_ok"] / coverage["days_total"]
    monthly = monthly.merge(
        coverage[["YearMonth", "days_total", "days_ok", "source_date_coverage"]],
        on="YearMonth", validate="one_to_one"
    )
    return monthly, float(monthly["source_date_coverage"].min())


def gate_decision(
    *, official_stationary_hours: float, official_berth_share: float,
    ais_stationary_hours: float, ais_resolved_berth_share: float,
    monthly_coverage_min: float, unresolved_share: float, represented_classes: int,
    source_integrity_pass: bool, emissions_identifiable: bool,
) -> dict:
    stationary_error_pct = 100.0 * (ais_stationary_hours / official_stationary_hours - 1.0)
    berth_share_error_points = 100.0 * (ais_resolved_berth_share - official_berth_share)
    conditions = {
        "source_hashes_tables_crosswalk": bool(source_integrity_pass),
        "monthly_source_date_coverage_gte_95pct": monthly_coverage_min >= MIN_MONTHLY_SOURCE_COVERAGE,
        "stationary_freight_hours_abs_error_lte_10pct": abs(stationary_error_pct) <= STATIONARY_ERROR_MAX_PCT,
        "resolved_berth_share_abs_error_lte_10pp": abs(berth_share_error_points) <= BERTH_SHARE_ERROR_MAX_POINTS,
        "stationary_freight_co2e_abs_error_lte_20pct": False if not emissions_identifiable else None,
        "at_least_five_official_freight_classes": represented_classes >= MIN_CLASSES,
        "class_stationary_emissions_spearman_gte_0_80": False if not emissions_identifiable else None,
        "ais_gap_unresolved_share_lte_10pct": unresolved_share <= MAX_UNRESOLVED_SHARE,
    }
    if any(value is None for value in conditions.values()):
        raise RuntimeError("identifiable emissions branch requires frozen emissions calculations")
    return {
        "conditions": conditions,
        "overall_pass": all(conditions.values()),
        "metrics": {
            "official_stationary_freight_vessel_hours": official_stationary_hours,
            "ais_stationary_freight_vessel_hours": ais_stationary_hours,
            "stationary_hours_error_pct": stationary_error_pct,
            "official_berth_share_resolved": official_berth_share,
            "ais_berth_share_resolved": ais_resolved_berth_share,
            "berth_share_error_percentage_points": berth_share_error_points,
            "monthly_source_date_coverage_min": monthly_coverage_min,
            "ais_unresolved_stationary_share": unresolved_share,
            "represented_official_freight_classes": represented_classes,
            "stationary_freight_co2e_error_pct": None,
            "class_stationary_emissions_spearman": None,
        },
    }


def fire() -> dict:
    preflight()
    components, checks, crosswalks, headings = [], [], [], []
    for prefix in ("pola", "polb"):
        component, check, crosswalk, report_headings = _holdout_report(
            SOURCE / f"{prefix}_2018_air_emissions_inventory.pdf"
        )
        components.append(component)
        checks.append(check)
        crosswalks.append(crosswalk)
        headings.extend(report_headings)
    component = pd.concat(components, ignore_index=True)
    check = pd.concat(checks, ignore_index=True)
    crosswalk = pd.concat(crosswalks, ignore_index=True)
    incomplete = crosswalk["crosswalk_decision"].eq("ERROR_INCOMPLETE_REQUIRED_COMPONENTS")
    source_integrity = bool(check["pass"].all() and not incomplete.any())

    candidates = _class_control_candidates(headings)
    emissions_identifiable = bool(candidates)
    # Development exposed no parser or tested calculation for an identifiable
    # joint-cell branch. Encountering one is safer than interpreting it after
    # holdout access and therefore aborts without writing a result.
    if emissions_identifiable:
        raise RuntimeError(
            "2018 unexpectedly publishes a class-by-control candidate; frozen development lacks "
            "an exercised reconstruction path, so no holdout result was written"
        )

    monthly, coverage_min = _monthly_ais()
    official_berth = float(component["official_berth_hours"].sum())
    official_anchor = float(component["official_anchor_hours"].sum())
    official_stationary = official_berth + official_anchor
    ais_berth = float(monthly["berth_hours"].sum())
    ais_anchor = float(monthly["anchor_hours"].sum())
    ais_unresolved = float(monthly["unresolved_stationary_hours"].sum())
    ais_stationary = ais_berth + ais_anchor + ais_unresolved
    decision = gate_decision(
        official_stationary_hours=official_stationary,
        official_berth_share=official_berth / official_stationary,
        ais_stationary_hours=ais_stationary,
        ais_resolved_berth_share=ais_berth / (ais_berth + ais_anchor),
        monthly_coverage_min=coverage_min,
        unresolved_share=ais_unresolved / ais_stationary,
        represented_classes=int(component["official_class"].nunique()),
        source_integrity_pass=source_integrity,
        emissions_identifiable=False,
    )
    decision.update({
        "study": "Prospective SPB freight-OGV emissions component validation",
        "registration": "https://osf.io/p5vqs/",
        "status": "PASS" if decision["overall_pass"] else "FAIL",
        "fired_at_utc": datetime.now(timezone.utc).isoformat(),
        "gate_fired_once": True,
        "protected_year": 2018,
        "class_control_joint_cells_published": False,
        "class_control_table_heading_candidates": candidates,
        "emissions_identifiable": False,
        "nonidentifiability_is_gate_failure": True,
        "consequence": (
            "Absolute vessel-emissions claims remain inadmissible; relative activity and explicitly labelled "
            "scenarios may remain. Pillar B is unchanged."
        ),
        "source_sha256": {
            "pola_2018_inventory": _sha256(SOURCE / "pola_2018_air_emissions_inventory.pdf"),
            "polb_2018_inventory": _sha256(SOURCE / "polb_2018_air_emissions_inventory.pdf"),
            "monthly_mode_time": _sha256(MODE_FILE),
            "month_manifest": _sha256(COVERAGE_FILE),
        },
    })

    OUT.mkdir(parents=True, exist_ok=False)
    component.to_csv(OUT / "official_2018_freight_components.csv", index=False, float_format="%.6f", lineterminator="\n")
    crosswalk.to_csv(OUT / "official_2018_class_crosswalk_and_inputs.csv", index=False, float_format="%.6f", lineterminator="\n")
    check.to_csv(OUT / "official_2018_published_total_checks.csv", index=False, float_format="%.6f", lineterminator="\n")
    monthly.to_csv(OUT / "ais_2018_monthly_stationary.csv", index=False, float_format="%.6f", lineterminator="\n")
    GATE_FILE.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    output_hashes = {
        path.name: _sha256(path) for path in sorted(OUT.iterdir()) if path.name != "completion_receipt.json"
    }
    receipt = {
        "status": "ONE_SHOT_GATE_COMPLETE_IMMUTABLE",
        "registration": "https://osf.io/p5vqs/",
        "gate_status": decision["status"],
        "holdout_executable_sha256": _sha256(Path(__file__)),
        "execution_freeze_sha256": _sha256(EXECUTION_FREEZE),
        "outputs_sha256": output_hashes,
    }
    (OUT / "completion_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, indent=2))
    return decision


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("fire",))
    parser.parse_args()
    fire()
