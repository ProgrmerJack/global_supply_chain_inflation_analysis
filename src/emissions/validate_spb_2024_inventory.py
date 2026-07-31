"""Compare the 2024 AIS inventory with official POLA/POLB stationary-mode tables.

This is a numerical, boundary-audited check. It cannot fire NS-G3 because the AIS population is cargo/tanker
while the published tables cover all OGVs (including cruise), and Pillar B remains unresolved.

Run: python src/emissions/validate_spb_2024_inventory.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from compute_emissions import compute

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/external/spb_emissions_inventories"
OUT = ROOT / "results/deep_case_SPB/emissions_2024_official_mode_validation.csv"
REPORTS = {
    "POLA": SOURCE / "pola_2024_air_emissions_inventory.pdf",
    "POLB": SOURCE / "polb_2024_air_emissions_inventory.pdf",
}
ANNUAL_TOLERANCE_PCT = 20.0
MODE_SHARE_TOLERANCE_POINTS = 10.0


def _verified_text(path: Path) -> str:
    meta = json.loads(path.with_suffix(path.suffix + ".manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
        raise RuntimeError(f"official inventory hash mismatch: {path.name}")
    pages = [page.extract_text() or "" for page in PdfReader(path).pages]
    matches = [text for text in pages if "Emissions by Mode" in text and "Total Hotelling at-berth" in text]
    if len(matches) != 1:
        raise RuntimeError(f"expected one official OGV mode table in {path.name}; found {len(matches)}")
    return matches[0]


def _last_number(text: str, label: str) -> float:
    lines = [line for line in text.splitlines() if line.startswith(label)]
    if len(lines) != 1:
        raise RuntimeError(f"expected one {label!r} row; found {len(lines)}")
    return float(lines[0].split()[-1].replace(",", ""))


def official_stationary() -> dict[str, float]:
    values = {"berth": 0.0, "anchor": 0.0}
    for path in REPORTS.values():
        text = _verified_text(path)
        values["berth"] += _last_number(text, "Total Hotelling at-berth")
        values["anchor"] += _last_number(text, "Total Hotelling at-anchorage")
    return values


def model_stationary() -> dict[str, float]:
    modes = pd.read_csv(ROOT / "data/processed/ais_dwell_census_mode/monthly_mode_time.csv")
    modes = modes[(modes.Port == "LA_Long_Beach") & (modes.YearMonth.str[:4] == "2024")]
    vessels = pd.read_csv(ROOT / "data/processed/vessel_characteristics.csv").rename(columns={
        "mmsi": "MMSI", "length_m": "Length", "width_m": "Width", "draft_m": "Draft",
        "vessel_type": "VesselType",
    })
    modes = modes.merge(vessels[["MMSI", "Length", "Width", "Draft", "VesselType"]], on="MMSI", how="left")
    co2 = compute(modes)
    co2 = co2[co2.pollutant.eq("CO2")].groupby("mode").tonnes.sum()
    return {"berth": co2["berth"], "anchor": co2["anchor"], "unresolved": co2["unknown_hoteling"]}


def validate() -> pd.DataFrame:
    official, model = official_stationary(), model_stationary()
    official_total = official["berth"] + official["anchor"]
    model_total = model["berth"] + model["anchor"] + model["unresolved"]
    annual_error = 100 * (model_total / official_total - 1)
    official_berth_share = 100 * official["berth"] / official_total
    model_berth_share = 100 * model["berth"] / (model["berth"] + model["anchor"])
    rows = [
        {"metric": "stationary_co2_or_co2e_t", "official": official_total, "model": model_total,
         "difference": model_total - official_total, "difference_pct_or_points": annual_error,
         "tolerance": ANNUAL_TOLERANCE_PCT, "numerical_pass": abs(annual_error) <= ANNUAL_TOLERANCE_PCT},
        {"metric": "berth_share_pct", "official": official_berth_share, "model": model_berth_share,
         "difference": model_berth_share - official_berth_share,
         "difference_pct_or_points": model_berth_share - official_berth_share,
         "tolerance": MODE_SHARE_TOLERANCE_POINTS,
         "numerical_pass": abs(model_berth_share - official_berth_share) <= MODE_SHARE_TOLERANCE_POINTS},
    ]
    out = pd.DataFrame(rows)
    out["formal_gate_fired"] = False
    out["formal_gate_blocker"] = "official all-OGV/CO2e versus AIS cargo-tanker/CO2 population mismatch; Pillar B unresolved"
    out.to_csv(OUT, index=False, float_format="%.3f", lineterminator="\n")
    print(out.to_string(index=False))
    return out


if __name__ == "__main__":
    validate()
