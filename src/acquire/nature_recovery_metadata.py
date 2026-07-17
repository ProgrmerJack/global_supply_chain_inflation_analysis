"""Archive outcome-blind metadata for the corrected Nature-route design.

This module records TEMPO product/service metadata and the CARB OGV2025 workbook
landing page. It deliberately does not request a TEMPO pixel, an air-quality
observation, or the CARB emissions workbook.

Run: python src/acquire/nature_recovery_metadata.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _http import get_bytes

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/external/nature_recovery_metadata"
TEMPO_V03 = (
    "https://gis.earthdata.nasa.gov/image/rest/services/"
    "C2930763263-LARC_CLOUD/"
    "TEMPO_NO2_L3_V03_HOURLY_TROPOSPHERIC_VERTICAL_COLUMN/ImageServer?f=pjson"
)
TEMPO_V04 = (
    "https://gis.earthdata.nasa.gov/image/rest/services/"
    "C3685896708-LARC_CLOUD/"
    "TEMPO_NO2_L3_V04_HOURLY_TROPOSPHERIC_VERTICAL_COLUMN/ImageServer?f=pjson"
)
TEMPO_GUIDE = (
    "https://asdc.larc.nasa.gov/documents/tempo/guide/"
    "TEMPO_Level-2-3_trace_gas_clouds_user_guide_V2.0.pdf"
)
CARB_OGV_PAGE = (
    "https://ww2.arb.ca.gov/resources/documents/final-ogv2025-emissions-inventory-output"
)
CARB_OGV_WORKBOOK = (
    "https://ww2.arb.ca.gov/sites/default/files/2025-04/"
    "Final_OGV2025_Emissions_Inventory.xlsx"
)
SOURCES = {
    "tempo_no2_v03_service.json": {
        "owner": "NASA Earthdata / ASDC",
        "url": TEMPO_V03,
        "kind": "json",
        "role": "TEMPO V03 hourly Level-3 NO2 service definition and availability metadata",
    },
    "tempo_no2_v04_service.json": {
        "owner": "NASA Earthdata / ASDC",
        "url": TEMPO_V04,
        "kind": "json",
        "role": "TEMPO V04 hourly Level-3 NO2 service definition and availability metadata",
    },
    "tempo_trace_gas_user_guide_v2.pdf": {
        "owner": "NASA ASDC",
        "url": TEMPO_GUIDE,
        "kind": "pdf",
        "role": "TEMPO quality, version and filtering methodology",
    },
    "carb_ogv2025_inventory_landing.html": {
        "owner": "California Air Resources Board",
        "url": CARB_OGV_PAGE,
        "kind": "html",
        "role": "Landing metadata for the unopened Final OGV2025 inventory workbook",
    },
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate(content: bytes, kind: str, name: str) -> None:
    if len(content) < 100:
        raise RuntimeError(f"metadata response is implausibly short: {name}")
    if kind == "json":
        parsed = json.loads(content)
        required = {"name", "timeInfo", "pixelSizeX", "pixelSizeY", "bandCount"}
        if not isinstance(parsed, dict) or not required.issubset(parsed):
            raise RuntimeError(f"unexpected TEMPO service schema: {name}")
    elif kind == "pdf" and not content.startswith(b"%PDF"):
        raise RuntimeError(f"official response is not a PDF: {name}")
    elif kind == "html":
        text = content.decode("utf-8", errors="ignore")
        if "Final OGV2025 Emissions Inventory" not in text or ".xlsx" not in text.lower():
            raise RuntimeError("CARB OGV2025 landing page lacks the declared workbook")


def _verified(path: Path) -> dict[str, object] | None:
    sidecar = path.with_suffix(path.suffix + ".manifest.json")
    if not path.exists():
        return None
    if not sidecar.exists():
        raise RuntimeError(f"missing provenance sidecar: {path.name}")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    if metadata["sha256"] != _sha(path.read_bytes()):
        raise RuntimeError(f"cached metadata hash mismatch: {path.name}")
    return metadata


def summarize_sources(v03: dict, v04: dict, carb_html: str) -> dict[str, object]:
    """Summarize only availability and product metadata, never outcome values."""
    workbook_match = re.search(
        r'href="([^"]*Final_OGV2025_Emissions_Inventory\.xlsx)"',
        carb_html,
        flags=re.IGNORECASE,
    )
    return {
        "tempo_v03": {
            "name": v03["name"],
            "time_extent_epoch_ms": v03["timeInfo"]["timeExtent"],
            "pixel_degrees": [v03["pixelSizeX"], v03["pixelSizeY"]],
            "band_count": v03["bandCount"],
        },
        "tempo_v04": {
            "name": v04["name"],
            "time_extent_epoch_ms": v04["timeInfo"]["timeExtent"],
            "pixel_degrees": [v04["pixelSizeX"], v04["pixelSizeY"]],
            "band_count": v04["bandCount"],
        },
        "carb_ogv2025": {
            "landing_page": CARB_OGV_PAGE,
            "workbook_declared": workbook_match is not None,
            "workbook_url": CARB_OGV_WORKBOOK,
            "workbook_opened": False,
        },
        "outcome_firewall": (
            "No TEMPO pixel, concentration observation, or CARB workbook cell was requested."
        ),
    }


def acquire(fetch=get_bytes) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, source in SOURCES.items():
        path = OUT / name
        metadata = _verified(path)
        if metadata is None:
            content = fetch(source["url"])
            _validate(content, source["kind"], name)
            path.write_bytes(content)
            metadata = {
                "source_owner": source["owner"],
                "source_url": source["url"],
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                "bytes": len(content),
                "sha256": _sha(content),
                "role": source["role"],
                "scope": "metadata_or_method_only; protected outcomes unopened",
            }
            path.with_suffix(path.suffix + ".manifest.json").write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )
        rows.append({"artifact": name, **metadata})

    summary_path = OUT / "source_feasibility.json"
    if not _verified(summary_path):
        summary = summarize_sources(
            json.loads((OUT / "tempo_no2_v03_service.json").read_text(encoding="utf-8")),
            json.loads((OUT / "tempo_no2_v04_service.json").read_text(encoding="utf-8")),
            (OUT / "carb_ogv2025_inventory_landing.html").read_text(
                encoding="utf-8", errors="ignore"
            ),
        )
        content = (json.dumps(summary, indent=2) + "\n").encode("utf-8")
        summary_path.write_bytes(content)
        summary_path.with_suffix(".json.manifest.json").write_text(
            json.dumps({
                "source_owner": "derived from the four official metadata artifacts",
                "source_url": "see source_manifest.csv",
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                "bytes": len(content),
                "sha256": _sha(content),
                "role": "outcome-blind recovery-source feasibility summary",
                "scope": "metadata_only; protected outcomes unopened",
            }, indent=2) + "\n",
            encoding="utf-8",
        )
    rows.append({"artifact": summary_path.name, **_verified(summary_path)})

    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT / "source_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"verified {len(rows)} outcome-blind Nature-recovery metadata artifacts")


if __name__ == "__main__":
    acquire()
