"""Registration-guarded CARB AQview historical-download acquisition.

This is distinct from the closed South Coast AQMD latest-chart route. It uses
the public AQview download-tool contract discovered and archived without
opening concentration values. Raw download bytes are retained once; parsing
and modelling occur only in downstream registered code.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

try:
    from ..governance.access import assert_nature_recovery_unlocked
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from governance.access import assert_nature_recovery_unlocked  # type: ignore


ROOT = Path(__file__).resolve().parents[2]
BASE = "https://aqview.arb.ca.gov/api"
PAGE = "https://aqview.arb.ca.gov/continuous-monitoring-data"
COMMUNITY_ID = "9"
GEOGRAPHY = "Community"
OUT = ROOT / "data/interim/nature_recovery/aqview_history"
WINDOWS = {
    "Nitrogen Dioxide (NO2)": ("2019-09-01", "2025-12-31"),
    "Black Carbon (BC)": ("2019-09-01", "2025-12-31"),
    "PM2.5": ("2022-11-01", "2025-12-31"),
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/138 Safari/537.36"
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def query_headers(
    parameter: str,
    *,
    start_date: str,
    end_date: str,
    subhourly_count: int | None = None,
    hourly_count: int | None = None,
) -> dict[str, str]:
    """Build the exact AQview download-tool headers used by the public client."""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": PAGE,
        "id": COMMUNITY_ID,
        "geo": GEOGRAPHY,
        "parameter": parameter,
        "startdate": start_date,
        "enddate": end_date,
    }
    if subhourly_count is not None:
        headers["subhourlycount"] = str(int(subhourly_count))
    if hourly_count is not None:
        headers["hourlycount"] = str(int(hourly_count))
    return headers


def parse_download_filename(payload: object) -> str:
    """Resolve a safe filename from the small AQview filename response."""
    value = payload
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, dict):
        for key in ("filename", "fileName", "FileName"):
            if value.get(key):
                value = value[key]
                break
    if not isinstance(value, str) or not value.strip():
        raise ValueError("AQview filename response has an unexpected shape")
    filename = value.strip().strip('"')
    if Path(filename).name != filename or filename in {".", ".."}:
        raise ValueError("AQview returned an unsafe download filename")
    return filename


def _get_json(path: str, headers: dict[str, str]) -> tuple[bytes, object]:
    response = requests.get(BASE + path, headers=headers, timeout=180)
    response.raise_for_status()
    try:
        return response.content, response.json()
    except requests.JSONDecodeError as error:
        raise RuntimeError(f"AQview did not return JSON for {path}") from error


def _write_once(path: Path, content: bytes) -> None:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if path.exists():
        if (
            not sidecar.exists()
            or sidecar.read_text(encoding="ascii").strip() != sha256_bytes(path.read_bytes())
        ):
            raise RuntimeError(f"cached AQview artifact failed its hash: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    sidecar.write_text(sha256_bytes(content) + "\n", encoding="ascii")


def acquire() -> Path:
    """Retrieve all frozen historical files once after the recovery unlock."""
    assert_nature_recovery_unlocked(OUT)
    manifest_path = OUT / "manifest.csv"
    if manifest_path.exists():
        rows = list(csv.DictReader(manifest_path.open(encoding="utf-8")))
        for row in rows:
            path = OUT / row["artifact"]
            _write_once(path, path.read_bytes())
        return manifest_path

    retrieved = datetime.now(timezone.utc).isoformat()
    rows = []
    for parameter, (start_date, end_date) in WINDOWS.items():
        base_headers = query_headers(
            parameter, start_date=start_date, end_date=end_date
        )
        counts_bytes, counts = _get_json(
            "/downloadtool/getrecordcounts", base_headers
        )
        if not isinstance(counts, list) or len(counts) != 1:
            raise RuntimeError(f"AQview count response has an unexpected shape: {parameter}")
        subhourly = int(counts[0].get("SubhourlyNumRecords") or 0)
        hourly = int(counts[0].get("HourlyNumRecords") or 0)
        if subhourly + hourly <= 0:
            raise RuntimeError(f"AQview reports no records in the frozen window: {parameter}")
        filename_bytes, filename_payload = _get_json(
            "/downloadtool/getfilename",
            query_headers(
                parameter,
                start_date=start_date,
                end_date=end_date,
                subhourly_count=subhourly,
                hourly_count=hourly,
            ),
        )
        filename = parse_download_filename(filename_payload)
        response = requests.get(
            BASE + "/downloadtool/getdownloadfile?filename=" + quote(filename),
            headers={"User-Agent": USER_AGENT, "Referer": PAGE},
            timeout=600,
        )
        response.raise_for_status()
        if not response.content:
            raise RuntimeError(f"AQview returned an empty file: {parameter}")
        if response.content.lstrip().lower().startswith(b"<html"):
            raise RuntimeError(f"AQview returned HTML instead of a data file: {parameter}")
        artifact = f"{parameter.lower().replace(' ', '_').replace('/', '_')}_{filename}"
        artifact = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in artifact
        )
        _write_once(OUT / artifact, response.content)
        rows.append({
            "parameter": parameter,
            "window_start": start_date,
            "window_end": end_date,
            "subhourly_records_declared": subhourly,
            "hourly_records_declared": hourly,
            "artifact": artifact,
            "bytes": len(response.content),
            "sha256": sha256_bytes(response.content),
            "counts_response_sha256": sha256_bytes(counts_bytes),
            "filename_response_sha256": sha256_bytes(filename_bytes),
            "retrieved_at_utc": retrieved,
            "source": "CARB AQview public historical download tool",
            "concentration_values_summarized_during_acquisition": False,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return manifest_path


if __name__ == "__main__":
    print(acquire())
