"""Cache official CARB At-Berth design documents once, with byte provenance.

This archive contains regulation, reporting-schema, and terminal-plan inputs only. It deliberately does not
download the embedded compliance dashboard or any AIS treatment outcome.

Run: python src/acquire/carb_atberth.py
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from _http import get_bytes

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/external/carb_atberth"
BASE = "https://ww2.arb.ca.gov"

SOURCES = {
    "final_regulation_order_2020.pdf": f"{BASE}/sites/default/files/barcu/regact/2019/ogvatberth2019/fro.pdf",
    "faq_2024-09.pdf": f"{BASE}/sites/default/files/2024-09/Updated%20At%20Berth%20FAQ%20Sept%202024%201.pdf",
    "enforcement_notice_2023-03-30.pdf": f"{BASE}/sites/default/files/2023-03/At%20Berth%20Enforcement%20Notice%20-%20March%2030%202023.pdf",
    "carb_2025_ogv_documentation.pdf": f"{BASE}/sites/default/files/2025-06/CARB_2025_OGV_Documentation_ADA.pdf",
    "terminal_and_port_plan_submissions.html": f"{BASE}/our-work/programs/ocean-going-vessels-berth-regulation/terminal-and-port-plan-submissions",
    "reporting_templates.html": f"{BASE}/our-work/programs/ocean-going-vessels-berth-regulation/berth-reporting-templates",
    "shore_power_enforcement_2024.html": f"{BASE}/es/node/43011",
    "polb_updated_port_plan_2024.pdf": f"{BASE}/sites/default/files/2025-03/Final%20Revised%20POLB%20Port%20Plan%20for%20the%20At%20Berth%20Regulation%20July%202024.pdf",
    "polb_port_plan_carb_response.pdf": f"{BASE}/sites/default/files/2025-03/POLB%20letter%20of%20completeness.pdf",
    "pola_updated_port_plan_2024.pdf": f"{BASE}/sites/default/files/2024-03/POLA%20Updated%20Port%20Plan.pdf",
    "pola_port_plan_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/Confirmation%20of%20completeness%20Port%20plan%20for%20POLA.pdf",
    "polb_olympus_updated_plan.pdf": f"{BASE}/sites/default/files/2024-07/Olympus%20Terminals%20At%20Berth%20Terminal%20Plan%20Updated%205.30.24.pdf",
    "polb_olympus_carb_response.pdf": f"{BASE}/sites/default/files/2024-07/Olympus%20Terminals%20POLB%20-%20Updated%20Terminal%20Plan%20Letter%20of%20Completeness.pdf",
    "polb_tesoro_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/TLO%20POLB%20Revised%20Terminal%20Plans.pdf",
    "polb_tesoro_carb_response.pdf": f"{BASE}/sites/default/files/2024-09/Tesoro%20Letter%20regarding%20Revised%20Terminal%20Plan.pdf",
    "polb_vopak_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/Vopak%20Long%20Beach%20At%20Berth%20Terminal%20Plan%202024_0.pdf",
    "polb_vopak_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/Vopak%20POLB%20-%20Updated%20Terminal%20Plan%20Letter%20of%20Completeness%20ADA.pdf",
    "pola_kinder_morgan_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/Kinder%20Morgan_Port%20%20Terminal%20Plan_2024.pdf",
    "pola_kinder_morgan_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/Kinder%20Morgan%20POLA%20-%20Updated%20Terminal%20Plan%20Letter%20of%20Completeness%20ADA.pdf",
    "pola_pbf_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/PBF_POLA%20Terminal%20Plan_2024%20submitted%20by%20terminal_0.pdf",
    "pola_pbf_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/PBF%20Energy%20POLA%20-%20Updated%20Terminal%20Plan%20Letter%20of%20Completeness%20ADA.pdf",
    "pola_phillips66_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/P66_Port%20%20Terminal%20Plan_2024.pdf",
    "pola_phillips66_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/Phillips%2066%20POLA%20-%20Updated%20Terminal-Port%20Plan%20Letter%20of%20Completeness%20ADA.pdf",
    "pola_shell_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/Shell%20Mormon%20Island%20Terminal%20Plan%20Update%20January%202024.pdf",
    "pola_shell_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/Shell%20POLA%20-%20Updated%20Terminal-Port%20Plan%20Letter%20of%20Completeness%20ADA.pdf",
    "pola_nustar163_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/Shore%20Terminals%20%28NuStar%29_Port%20%20Terminal%20Plan_2024.pdf",
    "pola_nustar163_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/Shore%20Terminals%20LLC%20dba%20NuStar%20163%20-%20Updated%20Terminal-Port%20Plan%20Letter%20of%20Completeness%20ADA.pdf",
    "pola_valero164_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/Valero%20%28Ultramar%29_Port%20%20Terminal%20Plan_2024_0.pdf",
    "pola_valero164_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/Valero%20Wilmington%20164%20-%20Updated%20Terminal-Port%20Plan%20Letter%20of%20Completeness%20ADA.pdf",
    "pola_vopak_updated_plan.pdf": f"{BASE}/sites/default/files/2024-03/Vopak%20Los%20Angeles%20At%20Berth%20Terminal%20Plan%202024_0.pdf",
    "pola_vopak_carb_response.pdf": f"{BASE}/sites/default/files/2024-05/Vopak%20POLA%20-%20Updated%20Terminal-Port%20Plan%20Letter%20of%20Completeness%20ADA.pdf",
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _verified(path: Path) -> dict[str, object] | None:
    sidecar = path.with_suffix(path.suffix + ".manifest.json")
    if not path.exists():
        return None
    if not sidecar.exists():
        raise RuntimeError(f"missing CARB provenance sidecar: {path.name}")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    if metadata["sha256"] != _sha256(path.read_bytes()):
        raise RuntimeError(f"cached CARB document hash mismatch: {path.name}")
    return metadata


def acquire(fetch=get_bytes) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, url in SOURCES.items():
        path = OUT / name
        metadata = _verified(path)
        if metadata is None:
            content = fetch(url)
            expected = b"%PDF" if path.suffix == ".pdf" else b"<"
            if not content.lstrip().startswith(expected):
                raise RuntimeError(f"official CARB response has unexpected format: {name}")
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.write_bytes(content)
            temporary.replace(path)
            metadata = {
                "source_owner": "California Air Resources Board",
                "source_url": url,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "bytes": len(content),
                "sha256": _sha256(content),
                "scope": "regulation_or_design_metadata_only; no AIS or embedded dashboard outcomes",
            }
            path.with_suffix(path.suffix + ".manifest.json").write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )
        rows.append({"artifact": name, **metadata})

    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT / "source_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"verified {len(rows)} official CARB At-Berth design documents in {OUT}")


if __name__ == "__main__":
    acquire()
