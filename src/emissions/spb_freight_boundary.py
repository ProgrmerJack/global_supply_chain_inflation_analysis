"""Extract the official San Pedro Bay multi-sector freight emissions boundary.

This is descriptive inventory accounting. It does not attribute a policy effect,
validate the AIS vessel model, or override the failed prospective NS-G3 gate.

Run: python src/emissions/spb_freight_boundary.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

try:
    from . import spb_component_validation as archive
except ImportError:  # direct script execution
    import spb_component_validation as archive

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/external/spb_emissions_inventories"
OUT = ROOT / "results/development/spb_freight_boundary"
YEARS = range(2018, 2025)
PORTS = {"pola": "POLA", "polb": "POLB"}
POLLUTANTS = ("PM10", "PM2.5", "DPM", "NOx", "SOx", "CO", "HC", "CO2e")
CATEGORY_PATTERNS = {
    "ocean_going_vessels": r"Ocean[- ]going vessels",
    "harbor_craft": r"Harbor craft",
    "cargo_handling_equipment": r"Cargo handling equipment",
    "locomotives": r"(?:Rail )?Locomotives",
    "heavy_duty_vehicles": r"Heavy-duty vehicles",
}
NUMBER = re.compile(r"(?<![A-Za-z])(?:\d[\d,]*(?:\.\d+)?|\.\d+)")
TITLE = re.compile(r"Table\s+(?:7|8)\.1:\s+(?:\d{4}\s+)?Emissions by Source Category", re.I)


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def parse_summary_page(text: str, *, port: str, year: int, page: int, source_file: str,
                       source_sha256: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse the first complete five-category table and reproduce its total."""
    rows: dict[str, list[float]] = {}
    total: list[float] | None = None
    for raw in text.splitlines():
        line = " ".join(raw.split())
        for category, pattern in CATEGORY_PATTERNS.items():
            match = re.match(rf"^{pattern}\s+(.+)$", line, re.I)
            if match and category not in rows:
                values = [_number(value) for value in NUMBER.findall(match.group(1))]
                if len(values) >= 8:
                    rows[category] = values[:8]
                break
        if len(rows) == len(CATEGORY_PATTERNS) and re.match(r"^Total\s+", line, re.I):
            values = [_number(value) for value in NUMBER.findall(line)]
            if len(values) >= 8:
                total = values[:8]
                break
    if set(rows) != set(CATEGORY_PATTERNS) or total is None:
        raise RuntimeError(f"{source_file}: incomplete five-sector summary table on page {page}")

    records, checks = [], []
    for index, pollutant in enumerate(POLLUTANTS):
        unit = "metric_tonnes" if pollutant == "CO2e" else "short_tons"
        extracted = sum(values[index] for values in rows.values())
        published = total[index]
        tolerance = max(1.0, abs(published) * 0.01)
        checks.append({
            "port": port, "year": year, "pollutant": pollutant,
            "extracted_category_sum": extracted, "published_total": published,
            "difference": extracted - published, "rounding_tolerance": tolerance,
            "pass": abs(extracted - published) <= tolerance, "reported_unit": unit,
            "page": page, "source_file": source_file, "source_sha256": source_sha256,
        })
        for category, values in rows.items():
            records.append({
                "port": port, "year": year, "source_category": category,
                "pollutant": pollutant, "reported_quantity": values[index],
                "reported_unit": unit, "page": page, "source_file": source_file,
                "source_sha256": source_sha256,
            })
    return pd.DataFrame(records), pd.DataFrame(checks)


def extract_report(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    match = re.fullmatch(r"(pola|polb)_(20(?:18|19|2[0-4]))_air_emissions_inventory\.pdf", path.name)
    if not match:
        raise RuntimeError(f"unexpected inventory path: {path.name}")
    port, year = PORTS[match.group(1)], int(match.group(2))
    source_sha256 = archive.sha256(path)
    candidates = []
    for page, pdf_page in enumerate(PdfReader(path).pages, start=1):
        text = pdf_page.extract_text() or ""
        if not TITLE.search(text):
            continue
        try:
            parsed = parse_summary_page(
                text, port=port, year=year, page=page, source_file=path.name,
                source_sha256=source_sha256,
            )
            candidates.append(parsed)
        except RuntimeError:
            continue
    if len(candidates) != 1:
        raise RuntimeError(f"{path.name}: expected one complete source-category table; found {len(candidates)}")
    return candidates[0]


def build() -> dict:
    archive.verify_archive()
    records, checks = [], []
    for year in YEARS:
        for prefix in PORTS:
            record, check = extract_report(SOURCE / f"{prefix}_{year}_air_emissions_inventory.pdf")
            records.append(record)
            checks.append(check)
    port = pd.concat(records, ignore_index=True)
    check = pd.concat(checks, ignore_index=True)
    if not check["pass"].all():
        failed = check.loc[~check["pass"], ["port", "year", "pollutant"]].to_dict("records")
        raise RuntimeError(f"published multi-sector totals not reproduced: {failed}")
    spb = port.groupby(
        ["year", "source_category", "pollutant", "reported_unit"], as_index=False
    )["reported_quantity"].sum()
    totals = spb.groupby(["year", "pollutant"], as_index=False)["reported_quantity"].sum().rename(
        columns={"reported_quantity": "spb_all_sector_total"}
    )
    spb = spb.merge(totals, on=["year", "pollutant"], validate="many_to_one")
    spb["share_of_spb_total"] = spb["reported_quantity"] / spb["spb_all_sector_total"]
    baseline = spb.loc[spb["year"].eq(2018), ["source_category", "pollutant", "reported_quantity"]].rename(
        columns={"reported_quantity": "reported_quantity_2018"}
    )
    spb = spb.merge(baseline, on=["source_category", "pollutant"], validate="many_to_one")
    spb["change_from_2018_pct"] = 100.0 * (
        spb["reported_quantity"] / spb["reported_quantity_2018"] - 1.0
    )

    OUT.mkdir(parents=True, exist_ok=True)
    port.to_csv(OUT / "port_sector_pollutant_2018_2024.csv", index=False, float_format="%.6f", lineterminator="\n")
    spb.to_csv(OUT / "spb_sector_pollutant_2018_2024.csv", index=False, float_format="%.6f", lineterminator="\n")
    check.to_csv(OUT / "published_total_checks_2018_2024.csv", index=False, float_format="%.6f", lineterminator="\n")
    summary = {
        "status": "DESCRIPTIVE_OFFICIAL_FREIGHT_BOUNDARY_COMPLETE",
        "reports": 14,
        "port_years": 14,
        "source_categories": list(CATEGORY_PATTERNS),
        "pollutants": list(POLLUTANTS),
        "published_total_checks": len(check),
        "published_total_checks_passed": int(check["pass"].sum()),
        "policy_attribution": False,
        "ais_model_validation": False,
        "overrides_failed_ns_g3": False,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    build()
