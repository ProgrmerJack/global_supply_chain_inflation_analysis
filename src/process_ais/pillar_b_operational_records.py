"""Pillar-B-OR: create a classifier-blind request packet after separate registration.

Operational returns are intentionally not ingested here until a source-specific
data contract has been frozen.  This module only creates the narrow request and
private linkage files needed to ask record holders about the frozen 96 episodes.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

import pillar_b_route_a as route_a

ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "prereg/studies/operational_records/pillar_b_or_freeze_receipt.json"
EXTERNAL = ROOT / "prereg/studies/operational_records/pillar_b_or_external_timestamp.json"
PROTOCOL = ROOT / "prereg/studies/operational_records/pillar_b_or_operational_record_validation.md"
REQUESTS = ROOT / "docs/pillar_b_or_operational_record_requests.md"
REGISTRATION_PAYLOAD = ROOT / "prereg/studies/operational_records/pillar_b_or_osf_registration_payload.json"
OSF_MATERIALS_MANIFEST = ROOT / "prereg/studies/operational_records/pillar_b_or_osf_materials_manifest.json"
IMPLEMENTATION_CORRECTION = ROOT / "prereg/studies/operational_records/pillar_b_or_implementation_correction.json"
TITLE = "San Pedro Bay Pillar-B-OR operational-record state validation"
WINDOW_MARGIN_H = 24
REQUEST_COLUMNS = ("request_id", "mmsi", "episode_date_utc", "window_start_utc", "window_end_utc",
                   "requested_fields")


def _sha256(path: Path) -> str:
    return route_a.sha256(path)


def _unescape_response(value):
    """Normalize OSF's HTML escaping before comparing frozen form answers."""
    if isinstance(value, str):
        return html.unescape(value)
    if isinstance(value, list):
        return [_unescape_response(item) for item in value]
    if isinstance(value, dict):
        return {key: _unescape_response(item) for key, item in value.items()}
    return value


def verify_local_freeze() -> dict:
    """Verify the unlabelled 96-episode source and every frozen OR artifact."""
    packet = route_a.source_packet()
    receipt = json.loads(FREEZE.read_text(encoding="utf-8"))
    paths = {
        "source_annotator_packet": route_a.SOURCE_PACKET,
        "source_packet_freeze": route_a.SOURCE_RECEIPT,
        "or_runner": Path(__file__),
        "or_protocol": PROTOCOL,
        "request_templates": REQUESTS,
        "osf_registration_payload": REGISTRATION_PAYLOAD,
        "osf_materials_manifest": OSF_MATERIALS_MANIFEST,
        "parent_deep_case_preregistration": ROOT / "prereg/studies/deep_case_spb/deep_case_SPB_preregistration.md",
        "state_scoring": ROOT / "src/process_ais/pillar_b_scoring.py",
    }
    for name, path in paths.items():
        expected = receipt.get("sha256", {}).get(name)
        if name == "or_runner" and _sha256(path) != expected and IMPLEMENTATION_CORRECTION.exists():
            correction = json.loads(IMPLEMENTATION_CORRECTION.read_text(encoding="utf-8"))
            if (correction.get("status") == "POST_REGISTRATION_IMPLEMENTATION_CORRECTION"
                    and correction.get("registered_or_runner_sha256") == expected
                    and correction.get("replacement_or_runner_sha256") == _sha256(path)):
                continue
        if expected != _sha256(path):
            raise RuntimeError(f"Pillar-B-OR local freeze mismatch: {name}")
    if len(packet) != 96 or packet["episode_id"].duplicated().any():
        raise RuntimeError("Pillar-B-OR source is not the frozen 96-episode packet")
    return receipt


def require_external_timestamp(receipt_path: Path = EXTERNAL) -> dict:
    """Fail closed until the distinct operational-record protocol is public."""
    local = verify_local_freeze()
    if not receipt_path.exists():
        raise RuntimeError("Pillar-B-OR is not externally timestamped; refusing to create a request packet")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "EXTERNALLY_TIMESTAMPED":
        raise RuntimeError("Pillar-B-OR is not externally timestamped; refusing to create a request packet")
    if receipt.get("local_freeze_receipt_sha256") != _sha256(FREEZE):
        raise RuntimeError("Pillar-B-OR external receipt does not bind its local freeze receipt")
    if receipt.get("sha256", {}).get("source_annotator_packet") != local["sha256"]["source_annotator_packet"]:
        raise RuntimeError("Pillar-B-OR external receipt does not bind the frozen 96-episode source")
    if receipt.get("sha256", {}).get("osf_registration_payload") != local["sha256"]["osf_registration_payload"]:
        raise RuntimeError("Pillar-B-OR external receipt does not bind its OSF response payload")
    registration_id = str(receipt.get("registration_id", ""))
    if receipt.get("registration_url") != f"https://osf.io/{registration_id}/":
        raise RuntimeError("Pillar-B-OR external receipt lacks a canonical OSF registration URL")
    attrs = route_a._osf_registration_attributes(registration_id)
    payload = json.loads(REGISTRATION_PAYLOAD.read_text(encoding="utf-8"))
    if (receipt.get("registration_title") != TITLE or attrs.get("title") != TITLE
            or _unescape_response(attrs.get("registration_responses")) != payload["registration_responses"]
            or not attrs.get("date_registered")):
        raise RuntimeError("Pillar-B-OR OSF registration does not match the frozen protocol")
    return receipt


def _mmsi(episode_id: object) -> str:
    parts = str(episode_id).split("|")
    if len(parts) < 2 or not parts[1].isdigit():
        raise ValueError("frozen episode_id does not contain an MMSI in its second component")
    return parts[1]


def request_rows(packet: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Make holder-facing and private rows without reading a classifier prediction."""
    required = {"episode_id", "vessel_id_hash", "start_utc", "end_utc"}
    if missing := required.difference(packet.columns):
        raise ValueError(f"Pillar-B-OR source packet lacks: {', '.join(sorted(missing))}")
    start = pd.to_datetime(packet["start_utc"], utc=True, errors="raise")
    end = pd.to_datetime(packet["end_utc"], utc=True, errors="raise")
    if (end < start).any():
        raise ValueError("Pillar-B-OR source packet has a negative episode window")
    request_id = [f"PILLAR_B_OR_{i:03d}" for i in range(1, len(packet) + 1)]
    request = pd.DataFrame({
        "request_id": request_id,
        "mmsi": [_mmsi(value) for value in packet["episode_id"]],
        "episode_date_utc": start.dt.strftime("%Y-%m-%d"),
        "window_start_utc": (start - pd.Timedelta(hours=WINDOW_MARGIN_H)).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end_utc": (end + pd.Timedelta(hours=WINDOW_MARGIN_H)).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requested_fields": "; ".join((
            "berth arrival/departure", "berth or terminal identifier", "anchorage arrival/departure",
            "vessel shift or movement timestamps", "record source and time zone",
        )),
    })
    mapping = pd.DataFrame({"request_id": request_id, "episode_id": packet["episode_id"],
                            "vessel_id_hash": packet["vessel_id_hash"]})
    return request.loc[:, REQUEST_COLUMNS], mapping


def write_request_packet(out_dir: Path) -> dict[str, Path]:
    """Write the only holder-facing packet after the separate OSF timestamp."""
    external = require_external_timestamp()
    packet = route_a.source_packet()
    request, mapping = request_rows(packet)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"request": out_dir / "operational_record_request_packet.csv",
             "mapping": out_dir / "request_mapping.csv", "manifest": out_dir / "request_packet_manifest.json"}
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("Pillar-B-OR request packet already exists; never overwrite a contact ledger")
    request.to_csv(paths["request"], index=False, lineterminator="\n")
    mapping.to_csv(paths["mapping"], index=False, lineterminator="\n")
    manifest = {
        "artifact": "Pillar-B-OR classifier-blind operational-record request packet",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "registration_url": external["registration_url"],
        "source_packet_sha256": _sha256(route_a.SOURCE_PACKET),
        "request_packet_sha256": _sha256(paths["request"]),
        "request_mapping_sha256": _sha256(paths["mapping"]),
        "n_requests": len(request),
        "excluded_fields": ["classifier prediction", "AI label", "expected state", "regime", "policy period"],
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze-gated Pillar-B-OR request-packet builder.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify-freeze")
    build = sub.add_parser("build-request-packet")
    build.add_argument("--out-dir", type=Path, default=ROOT / "data/interim/pillar_b_or")
    args = parser.parse_args()
    if args.command == "verify-freeze":
        print(verify_local_freeze()["artifact"])
    else:
        print(json.dumps({key: str(value) for key, value in write_request_packet(args.out_dir).items()}))


if __name__ == "__main__":
    main()
