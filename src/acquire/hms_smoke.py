"""Retrieve NOAA HMS annual smoke-polygon bundles once."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _http import get_bytes
from env_util import ROOT

OUT = ROOT / "data/external/hms_smoke"
BASE = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/Shapefile/Annual_Bundles"


def acquire(years: tuple[int, ...] = (2023, 2024, 2025), out: Path = OUT) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for year in years:
        destination = out / f"hms_smoke{year}.zip"
        url = f"{BASE}/{destination.name}"
        if not destination.exists():
            destination.write_bytes(get_bytes(url, timeout=600))
        rows.append({
            "year": year,
            "url": url,
            "bytes": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        })
    manifest = out / "manifest.json"
    manifest.write_text(json.dumps({
        "dataset": "NOAA HMS annual smoke-polygon bundles",
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "sources": rows,
    }, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(acquire())
