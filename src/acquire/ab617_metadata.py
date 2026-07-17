"""Archive WCWLB AB 617 monitor metadata and QA documents without outcome values.

Run: python src/acquire/ab617_metadata.py
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/external/ab617_wcwlb_metadata"
SITE_URL = "http://xappprod.aqmd.gov/AB617CommunityAirMonitoring/Home/Index/WCWLB"
AQVIEW_BASE = "https://aqview.arb.ca.gov/api"
AQVIEW_PAGE = "https://aqview.arb.ca.gov/continuous-monitoring-data"
AQVIEW_COMMUNITY_ID = "9"
AQVIEW_COMMUNITY = "Wilmington, West Long Beach, Carson"
AQVIEW_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Microsoft Windows 10.0.26200; en-US) "
    "PowerShell/7.6.0"
)
AQVIEW_PRIMARY_PARAMETERS = (
    "Nitrogen Dioxide (NO2)",
    "Black Carbon (BC)",
    "PM2.5",
)
AQVIEW_WINDOW = ("2020-01-01", "2024-12-31")
DOCUMENTS = {
    "wcwlb_camp.pdf": "https://www.aqmd.gov/docs/default-source/ab-617-ab-134/camps/wcwlb_camp.pdf?sfvrsn=9c1cd61_6",
    "wcwlb_camp_appendices.pdf": "https://www.aqmd.gov/docs/default-source/ab-617-ab-134/camps/appendix-a-and-b_wcwlb_v4.pdf?sfvrsn=ad78cd61_30",
    "ab617_qapp_2020.pdf": "https://www.aqmd.gov/docs/default-source/ab-617-ab-134/camps/qapp-for-ab-617-community-air-monitoring-program-(100620).pdf?sfvrsn=a8aed761_6",
}
EXPECTED_SITE_IDS = {"5", "6", "8", "9", "10", "13", "14", "22", "52"}
POLLUTANTS = [
    ("PM10", "particulate matter"), ("PM2.5", "particulate matter"),
    ("UFP", "particulate matter"), ("BC", "diesel-combustion indicator"),
    ("NO/NO2/NOx", "nitrogen oxides"), ("VOC/NMHC/BTEX", "volatile organic compounds"),
    ("H2S", "sulfur compound"), ("particulate metals", "air toxics"),
    ("CH4", "other gas"), ("NH3", "other gas"), ("SO2", "criteria pollutant"),
    ("aldehydes/carbonyls", "air toxics"), ("COS", "air toxic"),
    ("HCN", "air toxic"), ("HF", "air toxic"),
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    return urllib.request.urlopen(request, timeout=180).read()


class _SiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag != "input" or "monitoring-site" not in (values.get("class") or "").split():
            return
        community = values.get("data-monitoring-site-community-name") or ""
        if "(WCWLB)" not in community:
            return
        self.rows.append({
            "site_id": values["data-monitoring-site-id"],
            "community": community,
            "station_name": values["data-monitoring-site-banner"],
            "description": values["data-monitoring-site-description"],
            "latitude": values["data-monitoring-site-latitude"],
            "longitude": values["data-monitoring-site-longitude"],
        })


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


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]], metadata: dict[str, object]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    content = buffer.getvalue().encode("utf-8")
    path.write_bytes(content)
    metadata.update({"bytes": len(content), "sha256": _sha(content)})
    path.with_suffix(path.suffix + ".manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def _write_json(path: Path, value: object, metadata: dict[str, object]) -> None:
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(content)
    metadata.update({"bytes": len(content), "sha256": _sha(content)})
    path.with_suffix(path.suffix + ".manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def _aqview_get(path: str, headers: dict[str, str] | None = None) -> tuple[bytes, object]:
    request_headers = {
        "User-Agent": AQVIEW_USER_AGENT,
        "Referer": AQVIEW_PAGE,
        **(headers or {}),
    }
    response = requests.get(AQVIEW_BASE + path, headers=request_headers, timeout=180)
    response.raise_for_status()
    content = response.content
    try:
        return content, json.loads(content)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"CARB AQview metadata endpoint did not return JSON: {path}") from error


def assess_aqview_history(
    communities: list[dict[str, object]],
    parameters: list[dict[str, object]],
    availability: list[dict[str, object]],
    inventory: list[dict[str, object]],
) -> dict[str, object]:
    """Validate historical WCWLB availability without opening concentration values."""
    matching = [
        row for row in communities
        if str(row.get("CommunityId")) == AQVIEW_COMMUNITY_ID
        and row.get("CommunityNameShort") == AQVIEW_COMMUNITY
    ]
    available_parameters = {str(row.get("ParameterType")) for row in parameters}
    primary = {row["parameter"]: row for row in availability}
    inventory_rows = [
        row for row in inventory if row.get("AB 617 Community") == AQVIEW_COMMUNITY
    ]
    no2 = primary.get("Nitrogen Dioxide (NO2)", {})
    return {
        "source": "California Air Resources Board AQview public download metadata API",
        "community_id": AQVIEW_COMMUNITY_ID,
        "community": AQVIEW_COMMUNITY,
        "registered_window": f"{AQVIEW_WINDOW[0]} through {AQVIEW_WINDOW[1]}",
        "community_match": len(matching) == 1,
        "primary_parameters_listed": set(AQVIEW_PRIMARY_PARAMETERS).issubset(available_parameters),
        "wcwlb_inventory_rows": len(inventory_rows),
        "no2_earliest": no2.get("earliest"),
        "no2_latest": no2.get("latest"),
        "no2_hourly_records_in_window": int(no2.get("hourly_records", 0)),
        "historical_window_feasible": (
            len(matching) == 1
            and no2.get("earliest") == "September-2019"
            and int(no2.get("hourly_records", 0)) >= 20_000
            and len(inventory_rows) > 0
        ),
        "scope": (
            "metadata_only; proves public historical availability but does not retrieve, inspect, "
            "model, or summarize any concentration outcome"
        ),
    }


def acquire_aqview_metadata(now: str) -> list[Path]:
    """Archive effect-blind AQview inventory and historical-availability metadata."""
    communities_bytes, communities = _aqview_get("/downloadtool/getcommunities")
    if not isinstance(communities, list):
        raise RuntimeError("CARB AQview communities response has an unexpected shape")
    parameters_bytes, parameters = _aqview_get(
        "/downloadtool/getparameters", {"id": AQVIEW_COMMUNITY_ID, "geo": "Community"}
    )
    if not isinstance(parameters, list):
        raise RuntimeError("CARB AQview parameters response has an unexpected shape")
    inventory_bytes, inventory = _aqview_get("/datainventory/getdatainventory")
    if not isinstance(inventory, list):
        raise RuntimeError("CARB AQview inventory response has an unexpected shape")

    availability = []
    query_hashes: dict[str, dict[str, object]] = {
        "communities": {"bytes": len(communities_bytes), "sha256": _sha(communities_bytes)},
        "parameters": {"bytes": len(parameters_bytes), "sha256": _sha(parameters_bytes)},
        "inventory": {"bytes": len(inventory_bytes), "sha256": _sha(inventory_bytes)},
    }
    for parameter in AQVIEW_PRIMARY_PARAMETERS:
        headers = {"id": AQVIEW_COMMUNITY_ID, "geo": "Community", "parameter": parameter}
        dates_bytes, dates = _aqview_get("/downloadtool/getdates", headers)
        counts_bytes, counts = _aqview_get(
            "/downloadtool/getrecordcounts",
            {**headers, "startdate": AQVIEW_WINDOW[0], "enddate": AQVIEW_WINDOW[1]},
        )
        if not isinstance(dates, list) or len(dates) != 1 or not isinstance(counts, list) or len(counts) != 1:
            raise RuntimeError(f"CARB AQview availability response has an unexpected shape: {parameter}")
        availability.append({
            "parameter": parameter,
            "earliest": dates[0].get("MIN(EarliestRecordTime)"),
            "latest": dates[0].get("MAX(LatestRecordTime)"),
            "subhourly_records": int(counts[0].get("SubhourlyNumRecords") or 0),
            "hourly_records": int(counts[0].get("HourlyNumRecords") or 0),
            "window_start": AQVIEW_WINDOW[0],
            "window_end": AQVIEW_WINDOW[1],
        })
        query_hashes[parameter] = {
            "dates_bytes": len(dates_bytes),
            "dates_sha256": _sha(dates_bytes),
            "counts_bytes": len(counts_bytes),
            "counts_sha256": _sha(counts_bytes),
        }

    wcwlb_inventory = [
        row for row in inventory if row.get("AB 617 Community") == AQVIEW_COMMUNITY
    ]
    if not wcwlb_inventory:
        raise RuntimeError("CARB AQview inventory contains no WCWLB rows")
    artifacts = {
        "aqview_communities.json": communities,
        "aqview_wcwlb_parameters.json": parameters,
        "aqview_wcwlb_inventory.json": wcwlb_inventory,
        "aqview_wcwlb_availability_2020_2024.json": availability,
        "aqview_historical_feasibility.json": assess_aqview_history(
            communities, parameters, availability, inventory
        ),
    }
    paths = []
    for name, value in artifacts.items():
        path = OUT / name
        if not _verified(path):
            _write_json(path, value, {
                "source_owner": "California Air Resources Board",
                "source_url": AQVIEW_PAGE,
                "retrieved_at_utc": now,
                "source_query_response_hashes": query_hashes,
                "scope": "metadata_only; no concentration outcomes",
            })
        paths.append(path)
    return paths


def acquire() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    sites = OUT / "monitor_sites.csv"
    if not _verified(sites):
        response = _get(SITE_URL)
        parser = _SiteParser()
        parser.feed(response.decode("utf-8"))
        rows = sorted(parser.rows, key=lambda row: int(row["site_id"]))
        if {row["site_id"] for row in rows} != EXPECTED_SITE_IDS:
            raise RuntimeError("WCWLB site membership changed; review before freezing a new vintage")
        if any(not (33 <= float(row["latitude"]) <= 34 and -119 <= float(row["longitude"]) <= -117)
               for row in rows):
            raise RuntimeError("WCWLB site coordinate outside the expected Southern California extent")
        for row in rows:
            row.update({"source_url": SITE_URL, "retrieved_at_utc": now})
        _write_csv(sites, list(rows[0]), rows, {
            "source_owner": "South Coast AQMD",
            "source_url": SITE_URL,
            "retrieved_at_utc": now,
            "source_response_bytes": len(response),
            "source_response_sha256": _sha(response),
            "scope": "metadata_only; live wind and concentration fields excluded",
        })

    for name, url in DOCUMENTS.items():
        path = OUT / name
        if _verified(path):
            continue
        content = _get(url)
        if not content.startswith(b"%PDF"):
            raise RuntimeError(f"official AB 617 response is not a PDF: {name}")
        path.write_bytes(content)
        path.with_suffix(path.suffix + ".manifest.json").write_text(json.dumps({
            "source_owner": "South Coast AQMD", "source_url": url, "retrieved_at_utc": now,
            "bytes": len(content), "sha256": _sha(content),
            "scope": "monitoring-plan_or_QA_metadata; no concentration outcomes",
        }, indent=2) + "\n", encoding="utf-8")

    scope = OUT / "pollutant_scope.csv"
    if not _verified(scope):
        rows = [{
            "pollutant_group": pollutant,
            "category": category,
            "scope_kind": "WCWLB CAMP program scope; not station-specific availability",
            "source_document": "wcwlb_camp.pdf",
            "source_section": "Main Air Pollutants of Interest",
        } for pollutant, category in POLLUTANTS]
        _write_csv(scope, list(rows[0]), rows, {
            "source_owner": "South Coast AQMD", "source_url": DOCUMENTS["wcwlb_camp.pdf"],
            "retrieved_at_utc": now, "source_document_sha256": _sha((OUT / "wcwlb_camp.pdf").read_bytes()),
            "scope": "declared pollutant metadata only; no observations",
        })

    aqview_artifacts = acquire_aqview_metadata(now)
    artifacts = [sites, scope, *(OUT / name for name in DOCUMENTS), *aqview_artifacts]
    rows = []
    for path in artifacts:
        metadata = _verified(path)
        rows.append({"artifact": path.name, **metadata})
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT / "source_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"verified {len(EXPECTED_SITE_IDS)} WCWLB sites, {len(POLLUTANTS)} pollutant groups, "
        f"{len(DOCUMENTS)} QA/plan documents, and {len(aqview_artifacts)} AQview metadata artifacts"
    )


if __name__ == "__main__":
    acquire()
