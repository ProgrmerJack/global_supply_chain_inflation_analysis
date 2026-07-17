"""Acquire official WCWLB AB 617 responses after prospective registration.

The data-display service exposes site metadata and chart fragments through POST
requests. Raw HTML is the immutable source; parsing and analysis are downstream.

Run after external approval: python src/acquire/ab617_observations.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://xappprod.aqmd.gov/AB617CommunityAirMonitoring/"
SITE_ENDPOINT = BASE + "Home/GetMonitoringSiteData/"
CHART_ENDPOINT = BASE + "Home/GetMonitoringSiteChartData/"
SITES = (5, 6, 8, 9, 10, 13, 14, 22, 52)
OUT = ROOT / "data/external/ab617_wcwlb_observations"
RECEIPT = ROOT / "prereg/studies/spb_ab617/spb_ab617_source_aq_external_timestamp.json"
FREEZE = ROOT / "prereg/studies/spb_ab617/spb_ab617_source_aq_freeze_receipt.json"
TITLE = "WCWLB AB 617 source-oriented air-quality design"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _post(url: str, payload: dict) -> bytes:
    request = urllib.request.Request(
        url, data=json.dumps(payload, separators=(",", ":")).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0"},
    )
    return urllib.request.urlopen(request, timeout=180).read()


class OptionParser(HTMLParser):
    """Collect effect-blind chart request options from official site HTML."""
    def __init__(self) -> None:
        super().__init__()
        self.options: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = values.get("class", "").split()
        if "average-chart" not in classes:
            return
        required = ("data-parameter-id", "data-duration-id", "data-parameter-name")
        if all(values.get(key) for key in required):
            self.options.append({key.removeprefix("data-"): values[key] for key in required})


def parse_options(content: bytes) -> list[dict[str, str]]:
    parser = OptionParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    unique = {(row["parameter-id"], row["duration-id"], row["parameter-name"]): row for row in parser.options}
    return [unique[key] for key in sorted(unique)]


def preflight() -> dict:
    if not RECEIPT.exists() or not FREEZE.exists():
        raise RuntimeError("AB 617 outcomes remain firewalled until registration and executable freeze exist")
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if (
        receipt.get("registration_title") != TITLE
        or receipt.get("verified_public") is not True
        or receipt.get("verified_revision_state") != "approved"
    ):
        raise RuntimeError("AB 617 external registration is not public and approved")
    if sha256(Path(__file__)) != freeze.get("acquisition_executable_sha256"):
        raise RuntimeError("AB 617 acquisition executable changed after freeze")
    protocol = ROOT / "prereg/amendments/2026-07-18_spb_ab617_source_oriented_aq.md"
    if sha256(protocol) != freeze.get("protocol_sha256"):
        raise RuntimeError("AB 617 protocol changed after freeze")
    if OUT.exists() and (OUT / "manifest.csv").exists():
        return {"resume": True, "receipt": receipt}
    return {"resume": False, "receipt": receipt}


def _write_once(path: Path, content: bytes) -> None:
    if path.exists():
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if not sidecar.exists() or sidecar.read_text(encoding="ascii").strip() != sha256(path):
            raise RuntimeError(f"cached AB 617 response failed its hash sidecar: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.with_suffix(path.suffix + ".sha256").write_text(sha256_bytes(content) + "\n", encoding="ascii")


def acquire() -> None:
    preflight()
    retrieved = datetime.now(timezone.utc).isoformat()
    raw = OUT / "raw"
    manifest_rows = []
    for site in SITES:
        site_path = raw / f"site_{site}.html"
        if not site_path.exists():
            _write_once(site_path, _post(SITE_ENDPOINT, {"siteId": site}))
        options = parse_options(site_path.read_bytes())
        for option in options:
            parameter = re.sub(r"[^A-Za-z0-9_.-]+", "_", option["parameter-name"]).strip("_")[:80]
            chart_path = raw / (
                f"site_{site}__parameter_{option['parameter-id']}__duration_{option['duration-id']}__{parameter}.html"
            )
            if not chart_path.exists():
                _write_once(chart_path, _post(CHART_ENDPOINT, {
                    "siteId": site,
                    "parameterId": option["parameter-id"],
                    "durationId": option["duration-id"],
                }))
            manifest_rows.append({
                "site_id": site, **option, "source_endpoint": CHART_ENDPOINT,
                "retrieved_at_utc": retrieved, "artifact": chart_path.relative_to(OUT).as_posix(),
                "bytes": chart_path.stat().st_size, "sha256": sha256(chart_path),
            })
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]) if manifest_rows else ["site_id"])
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"retained {len(manifest_rows)} official WCWLB site/parameter/duration responses")


if __name__ == "__main__":
    acquire()
