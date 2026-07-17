"""Cache the official chronology sources for the 2014-2015 West Coast disruption."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from _http import get_bytes

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/external/policy_documents/labour_disruption_2014_2015"
SOURCES = {
    "senate_report_114_164.html": (
        "U.S. Government Publishing Office",
        "https://www.govinfo.gov/content/pkg/CRPT-114srpt164/html/CRPT-114srpt164.htm",
        "Federal record of the disruption and San Pedro Bay congestion",
    ),
    "ilwu_pma_2014_08_26.html": (
        "International Longshore and Warehouse Union / Pacific Maritime Association",
        "https://www.ilwu.org/pma-and-ilwu-update-on-contract-talks-tentative-agreement-reached-on-health-benefits-negotiations-continue-on-other-issues/",
        "Negotiations began 2014-05-12 and contract expired 2014-07-01",
    ),
    "white_house_2015_02_20.html": (
        "The White House, archived Obama administration",
        "https://obamawhitehouse.archives.gov/the-press-office/2015/02/20/statement-press-secretary-west-coast-ports-agreement",
        "Agreement announcement on 2015-02-20",
    ),
}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def acquire(fetch=get_bytes) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (owner, url, role) in SOURCES.items():
        path = OUT / name
        sidecar = path.with_suffix(path.suffix + ".manifest.json")
        if path.exists():
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            if metadata["sha256"] != sha256(path.read_bytes()):
                raise RuntimeError(f"chronology source hash mismatch: {name}")
        else:
            content = fetch(url)
            if b"<html" not in content[:2000].lower() and b"<!doctype" not in content[:2000].lower():
                raise RuntimeError(f"chronology source is not HTML: {name}")
            path.write_bytes(content)
            metadata = {
                "source_owner": owner,
                "source_url": url,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                "bytes": len(content),
                "sha256": sha256(content),
                "role": role,
            }
            sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        rows.append({"artifact": name, **metadata})
    with (OUT / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"verified {len(rows)} official labour-disruption chronology sources")


if __name__ == "__main__":
    acquire()
