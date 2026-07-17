"""Cache official 2018-2024 San Pedro Bay emissions inventories once, with byte provenance.

Run: python src/acquire/spb_emissions_inventories.py
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from _http import get_bytes

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/external/spb_emissions_inventories"
SOURCES = {
    "pola_2018_air_emissions_inventory.pdf": (
        "Port of Los Angeles",
        "https://kentico.portoflosangeles.org/getmedia/0e10199c-173e-4c70-9d1d-c87b9f3738b1/2018_Air_Emissions_Inventory",
    ),
    "polb_2018_air_emissions_inventory.pdf": (
        "Port of Long Beach",
        "https://legistar1.granicus.com/polb/attachments/67f34067-679f-43b8-a62b-5683c684f5d5.pdf",
    ),
    "pola_2019_air_emissions_inventory.pdf": (
        "Port of Los Angeles",
        "https://kentico.portoflosangeles.org/getmedia/4696ff1a-a441-4ee8-95ad-abe1d4cddf5e/2019_Air_Emissions_Inventory",
    ),
    "polb_2019_air_emissions_inventory.pdf": (
        "Port of Long Beach",
        "https://legistar1.granicus.com/polb/attachments/88022271-140f-47bb-bd42-0617e0f152b0.pdf",
    ),
    "pola_2020_air_emissions_inventory.pdf": (
        "Port of Los Angeles",
        "https://kentico.portoflosangeles.org/getmedia/7cb78c76-3c7b-4b8f-8040-b662f4a992b1/2020_Air_Emissions_Inventory",
    ),
    "polb_2020_air_emissions_inventory.pdf": (
        "Port of Long Beach",
        "https://legistar1.granicus.com/polb/attachments/380d1545-5b52-425d-9c4a-96a78c0a2f63.pdf",
    ),
    "pola_2021_air_emissions_inventory.pdf": (
        "Port of Los Angeles",
        "https://kentico.portoflosangeles.org/getmedia/f26839cd-54cd-4da9-92b7-a34094ee75a8/2021_Air_Emissions_Inventory",
    ),
    "polb_2021_air_emissions_inventory.pdf": (
        "Port of Long Beach",
        "https://legistar1.granicus.com/polb/attachments/b1534843-9e85-49b3-b928-4df04a4b09da.pdf",
    ),
    "pola_2022_air_emissions_inventory.pdf": (
        "Port of Los Angeles",
        "https://kentico.portoflosangeles.org/getmedia/409590b5-0e6a-4c15-8d9b-fcdb02624933/2022_Air_Emissions_Inventory",
    ),
    "polb_2022_air_emissions_inventory.pdf": (
        "Port of Long Beach",
        "https://legistar1.granicus.com/polb/attachments/ec40cab4-49ed-4274-85ce-df3117a09a62.pdf",
    ),
    "pola_2023_air_emissions_inventory.pdf": (
        "Port of Los Angeles",
        "https://kentico.portoflosangeles.org/getmedia/3fad9979-f2cb-4b3d-bf82-687434cbd628/2023-Air-Emissions-Inventory",
    ),
    "polb_2023_air_emissions_inventory.pdf": (
        "Port of Long Beach",
        "https://legistar1.granicus.com/daystar.legistar6.sdk.ws/View.ashx?M=F&GovernmentGUID=POLB&LogicalFileName=00d018bb-b848-4bb6-9a72-84257c7392cd.pdf&From=Granicus&Format=pdf",
    ),
    "pola_2024_air_emissions_inventory.pdf": (
        "Port of Los Angeles",
        "https://kentico.portoflosangeles.org/getmedia/d9720ae3-fd18-4b0e-9d32-380df2e475db/2024-air-emissions-inventory",
    ),
    "polb_2024_air_emissions_inventory.pdf": (
        "Port of Long Beach",
        "https://legistar1.granicus.com/daystar.legistar6.sdk.ws/View.ashx?M=F&GovernmentGUID=POLB&LogicalFileName=89faed1e-1433-4672-9bd0-9ac1215c4928.pdf&From=Granicus&Format=pdf",
    ),
    "spbp_2024_inventory_methodology_v5.pdf": (
        "San Pedro Bay Ports",
        "https://legistar1.granicus.com/daystar.legistar6.sdk.ws/View.ashx?M=F&GovernmentGUID=POLB&LogicalFileName=e8653a59-9cde-46ce-b4c0-ed0dc530df22.pdf&From=Granicus&Format=pdf",
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acquire() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, errors = [], []
    for name, (owner, url) in SOURCES.items():
        path = OUT / name
        sidecar = path.with_suffix(path.suffix + ".manifest.json")
        try:
            if path.exists():
                if not sidecar.exists() or json.loads(sidecar.read_text(encoding="utf-8"))["sha256"] != _sha256(path):
                    raise RuntimeError(f"cached inventory provenance mismatch: {name}")
            else:
                content = get_bytes(url, timeout=180)
                if not content.startswith(b"%PDF"):
                    raise RuntimeError(f"official inventory response is not a PDF: {name}")
                partial = path.with_suffix(path.suffix + ".part")
                partial.write_bytes(content)
                partial.replace(path)
                sidecar.write_text(json.dumps({
                    "source_owner": owner,
                    "source_url": url,
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "bytes": len(content),
                    "sha256": _sha256(path),
                    "scope": "official_inventory_or_methodology; acquisition only, no analytic values extracted",
                }, indent=2) + "\n", encoding="utf-8")
            rows.append({"file": name, **json.loads(sidecar.read_text(encoding="utf-8"))})
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    assert len(rows) + len(errors) == len(SOURCES)
    with (OUT / "source_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"verified {len(rows)}/{len(SOURCES)} official inventory documents in {OUT}")
    if errors:
        raise RuntimeError("; ".join(errors))


if __name__ == "__main__":
    acquire()
