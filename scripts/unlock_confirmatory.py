#!/usr/bin/env python3
"""Create a local confirmatory unlock only for a matching OSF receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    if not args.receipt.exists():
        print("ERROR: receipt does not exist")
        return 1

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    required = {"registration_url", "registered_at_utc", "registration_id", "manifest_sha256"}
    missing = sorted(required - receipt.keys())
    if missing:
        print(f"ERROR: receipt missing fields: {', '.join(missing)}")
        return 1

    parsed = urlparse(receipt["registration_url"])
    if parsed.scheme != "https" or "osf.io" not in parsed.netloc:
        print("ERROR: registration_url must be an HTTPS OSF URL")
        return 1

    try:
        datetime.fromisoformat(receipt["registered_at_utc"].replace("Z", "+00:00"))
    except ValueError:
        print("ERROR: invalid registered_at_utc")
        return 1

    manifest = ROOT / "prereg/governance/osf_manifest.csv"
    if not manifest.exists():
        print("ERROR: protocol/osf_manifest.csv is missing")
        return 1
    actual = file_sha256(manifest)
    if actual != receipt["manifest_sha256"]:
        print("ERROR: manifest hash mismatch")
        return 1

    unlock = {
        "registration_id": receipt["registration_id"],
        "registration_url": receipt["registration_url"],
        "registered_at_utc": receipt["registered_at_utc"],
        "manifest_sha256": actual,
        "unlocked_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path = ROOT / "prereg/governance/CONFIRMATORY_UNLOCK.json"
    path.write_text(json.dumps(unlock, indent=2) + "\n", encoding="utf-8")
    print("CONFIRMATORY ANALYSIS UNLOCKED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
