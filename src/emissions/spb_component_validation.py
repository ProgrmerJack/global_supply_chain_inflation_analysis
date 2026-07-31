"""Prospective POLA/POLB freight-OGV component validation.

The development command reads only 2019-2024.  It extracts directly reported
class activity, stationary durations and load defaults without inventing the
unpublished class-by-control cells.  The protected 2018 gate is implemented
only after the development artifact is frozen.

Run: python src/emissions/spb_component_validation.py development
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import pdfplumber
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/external/spb_emissions_inventories"
OUT = ROOT / "results/development/spb_emissions_component_validation"
DEVELOPMENT_YEARS = range(2019, 2025)
PORTS = {"pola": "POLA", "polb": "POLB"}
FREIGHT_CLASSES = {
    "auto carrier": "auto_carrier",
    "bulk": "bulk_carrier",
    "container": "containership",
    "general cargo": "general_cargo",
    "reefer": "reefer",
    "roro": "ro_ro",
    "tanker": "tanker",
}

LABEL = re.compile(
    r"^(Auto Carrier|Bulk(?:\s*-\s*[A-Za-z ]+)?|Container(?:ship)?(?:\s*-\s*(?:<?\s*)?[0-9,]+)?|"
    r"Cruise(?: Ship)?|General Cargo|Miscellaneous(?: Vessel)?|Reefer(?: Vessel)?|Refrigerated Vessel|"
    r"Ocean Tugboat(?:\s*\(ATB(?:/ITB)?\))?|RoRo|Roll-on Roll-off|"
    r"Tanker(?:\s*-\s*[A-Za-z]+)?)\s+(.+)$",
    re.I,
)
NUMBER = re.compile(r"(?<![A-Za-z])(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:%)?")
TABLES = {
    "activity": r"Table\s+\d+\.\s*\d+:\s+\d{4}\s+Total OGV Activities",
    "aux": r"Table\s+\d+\.\s*\d+:\s+(?:\d{4}\s+)?Average Auxiliary(?: Engine)? Load Defaults",
    "boiler": r"Table\s+\d+\.\s*\d+:\s+(?:\d{4}\s+)?Auxiliary Boiler Load Defaults by Mode",
    "berth": r"Table\s+\d+\.\s*\d+:\s+\d{4}\s+(?:At-Berth Hotelling Times|Hotelling Times at Berth)",
    "anchor": r"Table\s+\d+\.\s*\d+:\s+\d{4}\s+(?:At-Anchorage Hotelling Times|Hotelling Times at Anchorage)",
    "type_emissions": r"Table\s+\d+\.\s*\d+:\s+(?:\d{4}\s+)?(?:OGV|Ocean-Going Vessel) Emissions by Vessel Type",
}
POLLUTANTS = ("PM10", "PM2.5", "DPM", "NOx", "SOx", "CO", "HC", "CO2e")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_archive() -> None:
    """Hash-check every cached PDF without interpreting protected values."""
    pdfs = sorted(SOURCE.glob("*.pdf"))
    if len(pdfs) != 15:
        raise RuntimeError(f"expected 15 official PDFs; found {len(pdfs)}")
    for path in pdfs:
        sidecar = path.with_suffix(path.suffix + ".manifest.json")
        if not sidecar.exists() or json.loads(sidecar.read_text(encoding="utf-8"))["sha256"] != sha256(path):
            raise RuntimeError(f"official source provenance mismatch: {path.name}")


def _number(value: str) -> float:
    return float(value.rstrip("%").replace(",", ""))


def _detail_key(label: str) -> str:
    value = " ".join(label.lower().replace("–", "-").split())
    value = re.sub(r"\s*-\s*", "-", value).replace(",", "")
    if value in {"bulk", "bulk-general"}:
        return "bulk-general"
    if value in {"reefer vessel", "refrigerated vessel"}:
        return "reefer"
    if value == "roll-on roll-off":
        return "roro"
    return value


def _official_class(detail: str) -> str | None:
    for prefix, official in FREIGHT_CLASSES.items():
        if detail.startswith(prefix):
            return official
    return None


def _class_rows(text: str, minimum_numbers: int) -> list[dict]:
    rows = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        match = LABEL.match(line)
        if not match:
            continue
        values = [_number(value) for value in NUMBER.findall(match.group(2))]
        if len(values) >= minimum_numbers:
            detail = _detail_key(match.group(1))
            rows.append({"detail": detail, "official_class": _official_class(detail), "values": values})
    if len({row["detail"] for row in rows}) != len(rows):
        raise RuntimeError("official table contains a duplicated vessel row")
    return rows


def _table(pages: list[str], name: str, minimum_rows: int = 5) -> tuple[str, int]:
    pattern = re.compile(TABLES[name], re.I)
    candidates = []
    for index, page in enumerate(pages):
        match = pattern.search(page)
        if not match:
            continue
        end = re.search(r"\nTable\s+\d+\.\s*\d+:", page[match.end():], re.I)
        # Some POLB PDFs place the next table's heading before the current
        # table's cells in extracted text. Vessel-class row labels remain
        # unique on the page, so retain the page and delimit its totals below.
        if name == "type_emissions":
            text = page[match.start():]
        else:
            text = page[match.start(): match.end() + end.start()] if end else page[match.start():]
        if len(_class_rows(text, 3)) >= minimum_rows:
            candidates.append((text, index + 1))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one populated {name} table; found {len(candidates)}")
    return candidates[0]


def _rows_frame(text: str, page: int, minimum: int, columns: dict[str, int]) -> pd.DataFrame:
    records = []
    for row in _class_rows(text, minimum):
        record = {"detail": row["detail"], "official_class": row["official_class"], "page": page}
        record.update({name: row["values"][index] for name, index in columns.items()})
        records.append(record)
    return pd.DataFrame(records)


def _published_total_check(text: str, page: int) -> list[dict]:
    rows = _class_rows(text, 8)
    totals = []
    seen_class_row = False
    first_total_seen = False
    additional = []
    for line in text.splitlines():
        normalized = " ".join(line.split())
        class_match = LABEL.match(normalized)
        if class_match and len(NUMBER.findall(class_match.group(2))) >= 8:
            seen_class_row = True
            continue
        if not seen_class_row:
            continue
        if first_total_seen and re.match(r"^(?:Mode|Engine Type|Transit|Maneuvering|Hotelling)", normalized, re.I):
            break
        if re.match(r"^Total\s+", normalized):
            values = [_number(value) for value in NUMBER.findall(normalized)]
            if len(values) >= 8:
                totals.append(values[-8:])
                first_total_seen = True
        elif first_total_seen and re.match(r"^Additional loitering/anchorage\s+", normalized, re.I):
            additional = [_number(value) for value in NUMBER.findall(normalized)][-8:]
    if len(totals) not in {1, 2}:
        raise RuntimeError(f"expected one or two vessel-type emissions totals on page {page}; found {len(totals)}")
    checks = []
    for index, pollutant in enumerate(POLLUTANTS):
        extracted = sum(row["values"][-8 + index] for row in rows)
        published = totals[0][index]
        tolerance = max(1.0, abs(published) * 0.01)
        checks.append({"component": "class_rows", "pollutant": pollutant, "extracted_sum": extracted,
                       "published_total": published,
                       "difference": extracted - published, "rounding_tolerance": tolerance,
                       "pass": abs(extracted - published) <= tolerance, "page": page})
        if len(totals) == 2:
            if len(additional) != 8:
                raise RuntimeError(f"unallocated anchorage row missing on page {page}")
            grand_extracted = published + additional[index]
            grand_published = totals[1][index]
            grand_tolerance = max(1.0, abs(grand_published) * 0.01)
            checks.append({"component": "grand_total_with_unallocated_anchorage", "pollutant": pollutant,
                           "extracted_sum": grand_extracted, "published_total": grand_published,
                           "difference": grand_extracted - grand_published,
                           "rounding_tolerance": grand_tolerance,
                           "pass": abs(grand_extracted - grand_published) <= grand_tolerance, "page": page})
    return checks


def extract_report(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    match = re.fullmatch(r"(pola|polb)_(\d{4})_air_emissions_inventory\.pdf", path.name)
    if not match or int(match.group(2)) not in DEVELOPMENT_YEARS:
        raise RuntimeError("development extractor refuses protected or unknown inventory")
    port, year = PORTS[match.group(1)], int(match.group(2))
    # Neither engine is uniformly superior across the inventories. PyPDF
    # correctly reads landscape tables in older POLB reports, while pdfplumber
    # preserves word/number grouping in several later tables. Use the latter
    # only when a populated table cannot be recovered by the former.
    pages = [page.extract_text() or "" for page in PdfReader(path).pages]
    layout_pages: list[str] | None = None

    def get_table(name: str) -> tuple[str, int]:
        nonlocal layout_pages
        try:
            return _table(pages, name)
        except RuntimeError as primary_error:
            if layout_pages is None:
                with pdfplumber.open(path) as report:
                    layout_pages = [page.extract_text() or "" for page in report.pages]
            try:
                return _table(layout_pages, name)
            except RuntimeError:
                raise RuntimeError(f"{path.name}: {primary_error}") from primary_error

    activity, activity_page = get_table("activity")
    aux, aux_page = get_table("aux")
    boiler, boiler_page = get_table("boiler")
    berth, berth_page = get_table("berth")
    anchor, anchor_page = get_table("anchor")
    emissions, emissions_page = get_table("type_emissions")

    frames = [
        _rows_frame(activity, activity_page, 4, {"arrivals": 0}),
        _rows_frame(aux, aux_page, 4, {"aux_berth_kw": 2, "aux_anchor_kw": 3}),
        _rows_frame(boiler, boiler_page, 4, {"boiler_berth_kw": 2, "boiler_anchor_kw": 3}),
        _rows_frame(berth, berth_page, 3, {"mean_berth_hours": 2}),
        _rows_frame(anchor, anchor_page, 4, {"mean_anchor_hours": 2, "anchor_count": -1}),
    ]
    merged = frames[0].drop(columns="page")
    page_columns = {"activity_page": activity_page, "aux_page": aux_page, "boiler_page": boiler_page,
                    "berth_page": berth_page, "anchor_page": anchor_page}
    for frame in frames[1:]:
        merged = merged.merge(frame.drop(columns=["official_class", "page"]), on="detail", how="outer",
                              validate="one_to_one")
    merged["official_class"] = merged["detail"].map(_official_class)
    merged["component_complete"] = merged[["arrivals", "aux_berth_kw", "aux_anchor_kw", "boiler_berth_kw",
                                             "boiler_anchor_kw", "mean_berth_hours", "mean_anchor_hours",
                                             "anchor_count"]].notna().all(axis=1)
    merged["official_berth_hours"] = merged["arrivals"] * merged["mean_berth_hours"]
    merged["official_anchor_hours"] = merged["anchor_count"] * merged["mean_anchor_hours"]
    merged["port"] = port
    merged["year"] = year
    merged["source_file"] = path.name
    merged["source_sha256"] = sha256(path)
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

    complete = merged[merged.component_complete].copy()
    aggregate = complete.groupby(["port", "year", "official_class", "source_file", "source_sha256"],
                                  as_index=False).agg(
        arrivals=("arrivals", "sum"), official_berth_hours=("official_berth_hours", "sum"),
        anchor_count=("anchor_count", "sum"), official_anchor_hours=("official_anchor_hours", "sum"),
        detail_rows=("detail", "count"),
    )
    missing = merged[~merged.component_complete].groupby("official_class").size()
    aggregate["incomplete_detail_rows"] = aggregate.official_class.map(missing).fillna(0).astype(int)
    aggregate["class_control_joint_cell_published"] = False
    aggregate["class_emissions_identifiable"] = False
    for column, value in page_columns.items():
        aggregate[column] = value

    checks = pd.DataFrame(_published_total_check(emissions, emissions_page))
    checks.insert(0, "year", year)
    checks.insert(0, "port", port)
    checks["source_file"] = path.name
    checks["source_sha256"] = sha256(path)
    audit_columns = [
        "port", "year", "detail", "official_class", "included_in_matched_freight_population",
        "crosswalk_decision", "component_complete", "arrivals", "mean_berth_hours",
        "official_berth_hours", "anchor_count", "mean_anchor_hours", "official_anchor_hours",
        "aux_berth_kw", "aux_anchor_kw", "boiler_berth_kw", "boiler_anchor_kw",
        "activity_page", "aux_page", "boiler_page", "berth_page", "anchor_page",
        "source_file", "source_sha256",
    ]
    return aggregate, checks, merged[audit_columns].copy()


def development() -> None:
    verify_archive()
    components, checks, crosswalks = [], [], []
    for year in DEVELOPMENT_YEARS:
        for prefix in PORTS:
            component, check, crosswalk = extract_report(
                SOURCE / f"{prefix}_{year}_air_emissions_inventory.pdf"
            )
            components.append(component)
            checks.append(check)
            crosswalks.append(crosswalk)
    component = pd.concat(components, ignore_index=True)
    check = pd.concat(checks, ignore_index=True)
    crosswalk = pd.concat(crosswalks, ignore_index=True)
    incomplete = crosswalk["crosswalk_decision"] == "ERROR_INCOMPLETE_REQUIRED_COMPONENTS"
    if incomplete.any():
        details = crosswalk.loc[incomplete, ["port", "year", "detail"]].to_dict("records")
        raise RuntimeError(f"activity-observed freight class lacks required components: {details}")
    if not check["pass"].all():
        failed = check.loc[~check["pass"], ["port", "year", "pollutant"]]
        raise RuntimeError(f"published table total reproduction failed: {failed.to_dict('records')}")
    OUT.mkdir(parents=True, exist_ok=True)
    component.to_csv(OUT / "official_freight_components_2019_2024.csv", index=False, float_format="%.6f",
                     lineterminator="\n")
    check.to_csv(OUT / "published_total_checks_2019_2024.csv", index=False, float_format="%.6f",
                 lineterminator="\n")
    crosswalk.to_csv(
        OUT / "official_class_crosswalk_and_inputs_2019_2024.csv", index=False,
        float_format="%.6f", lineterminator="\n"
    )
    summary = {
        "status": "DEVELOPMENT_EXTRACTION_COMPLETE_HOLDOUT_UNOPENED",
        "reports": len(components),
        "years": [min(DEVELOPMENT_YEARS), max(DEVELOPMENT_YEARS)],
        "ports": sorted(PORTS.values()),
        "published_total_checks": len(check),
        "published_total_checks_passed": int(check["pass"].sum()),
        "crosswalk_detail_rows": len(crosswalk),
        "matched_freight_detail_rows": int(crosswalk["included_in_matched_freight_population"].sum()),
        "incomplete_freight_detail_rows": int(
            (crosswalk["crosswalk_decision"] == "ERROR_INCOMPLETE_REQUIRED_COMPONENTS").sum()
        ),
        "freight_detail_rows_without_reported_activity": int(
            (crosswalk["crosswalk_decision"] == "EXCLUDED_NO_REPORTED_ACTIVITY").sum()
        ),
        "class_control_joint_cells_published": False,
        "class_emissions_identifiable": False,
        "identifiability_reason": "reports publish port-wide shore-power/CAECS margins, not class-by-control cells",
        "protected_2018_values_opened": False,
        "protected_gate_fired": False,
    }
    (OUT / "development_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("development",))
    args = parser.parse_args()
    development()
