"""Route A: blinded computational silver labels for Pillar B.

This is deliberately *not* a human-reference benchmark and cannot unlock the
human Pillar-B gate.  It builds blinded AIS evidence, locks deterministic rule
outputs and accepts a silver label only under strict cross-channel agreement.
Classifier predictions and policy-period labels are never read by this module.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import duckdb
import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PACKET = ROOT / "data/interim/pillar_b_benchmark/annotator_packet.csv"
SOURCE_RECEIPT = ROOT / "data/interim/pillar_b_benchmark/annotator_packet_freeze.json"
LOCAL_FREEZE_RECEIPT = ROOT / "prereg/studies/route_a/pillar_b_route_a_freeze_receipt.json"
MODEL_PROMPT = ROOT / "prereg/studies/route_a/pillar_b_route_a_model_prompt.md"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PINGS_ROOT = ROOT / "data/interim/national_pings"
ZONES = ROOT / "data/processed/state_zones_derived.geojson"
LABELS = {"moving", "manoeuvre", "anchor", "berth", "uncertain"}
ROUTE_A_TITLE = "San Pedro Bay Route-A computational silver-label protocol"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OSF_ID = re.compile(r"^[a-z0-9]{5}$")
_MODEL_RECORD_FIELDS = {
    "blind_id", "run_id", "model_id", "prompt_sha256", "primary_class",
    "state_start_h", "state_end_h", "confidence", "evidence", "counterevidence",
    "model_version", "model_parameters", "response_timestamp_utc", "raw_response", "raw_response_sha256",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value) -> pd.Timestamp:
    return pd.Timestamp(value).tz_convert("UTC") if pd.Timestamp(value).tzinfo else pd.Timestamp(value, tz="UTC")


def source_packet() -> pd.DataFrame:
    receipt = json.loads(SOURCE_RECEIPT.read_text(encoding="utf-8"))
    actual = sha256(SOURCE_PACKET)
    if actual != receipt["sha256"]:
        raise RuntimeError("original annotator packet hash mismatch; do not create Route-A evidence")
    packet = pd.read_csv(SOURCE_PACKET)
    if len(packet) != 96 or packet["episode_id"].duplicated().any():
        raise RuntimeError("original annotator packet is not the frozen 96-episode set")
    return packet


def _haversine_km(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    dlat, dlon = np.diff(lat), np.diff(lon)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def episode_features(track: pd.DataFrame, start_h: float, end_h: float) -> dict:
    target = track.loc[track.relative_h.between(start_h, end_h)].copy()
    if target.empty:
        raise ValueError("candidate window has no retained AIS pings")
    gaps = track.relative_h.sort_values().diff().dropna() * 60
    path = _haversine_km(target.lat.to_numpy(), target.lon.to_numpy()) if len(target) > 1 else np.array([])
    headings = np.radians(target.cog.dropna().to_numpy())
    resultant = abs(np.mean(np.exp(1j * headings))) if len(headings) else 0.0
    return {
        "candidate_start_h": round(float(start_h), 4), "candidate_end_h": round(float(end_h), 4),
        "candidate_duration_h": round(float(end_h - start_h), 4), "n_context_pings": int(len(track)),
        "n_candidate_pings": int(len(target)), "max_gap_min": round(float(gaps.max()) if len(gaps) else 0.0, 3),
        "median_sog": round(float(target.sog.median()), 3), "p90_sog": round(float(target.sog.quantile(.9)), 3),
        "stationary_share": round(float(target.sog.lt(.5).mean()), 3), "moving_share": round(float(target.sog.ge(3).mean()), 3),
        "path_km": round(float(path.sum()), 3), "net_displacement_km": round(float(_haversine_km(target.lat.iloc[[0, -1]].to_numpy(), target.lon.iloc[[0, -1]].to_numpy()).sum()) if len(target) > 1 else 0.0, 3),
        "heading_variation": round(float(1 - resultant), 3),
    }


def _zone_fractions(track: pd.DataFrame, zones: gpd.GeoDataFrame) -> dict:
    points = gpd.GeoDataFrame(track, geometry=gpd.points_from_xy(track.lon, track.lat), crs="EPSG:4326")
    joined = gpd.sjoin(points, zones[["zone_type", "geometry"]], how="left", predicate="within")
    joined["priority"] = joined.zone_type.map({"berth": 0, "anchor": 1}).fillna(99)
    labels = joined.sort_values("priority").groupby(level=0).zone_type.first().reindex(track.index)
    return {f"{state}_fraction": round(float(labels.eq(state).mean()), 3) for state in ("berth", "anchor")}


def rule_outputs(features: dict) -> dict:
    """Return independent physical support sets; uncertainty is preferred to a forced label.

    The channels intentionally measure complementary constructs.  A kinematic
    signal can establish stationary versus moving, but cannot by itself
    distinguish a berth from an anchorage.  Requiring identical four-class
    labels from all channels would therefore make the protocol structurally
    incapable of accepting any stationary episode.  We instead require every
    channel to support one *same* final state, without borrowing evidence
    between channels.
    """
    bad_coverage = features["n_candidate_pings"] < 5 or features["max_gap_min"] > 60 or features["candidate_duration_h"] <= 0
    kinematic = ("moving",) if features["moving_share"] >= .8 and features["path_km"] >= .5 else (
        ("manoeuvre",) if features["median_sog"] >= .5 else
        (("anchor", "berth") if features["stationary_share"] >= .8 else ()))
    geometry = (("berth",) if features["berth_fraction"] >= .8 else
                (("anchor",) if features["anchor_fraction"] >= .8 else
                 (("moving", "manoeuvre") if features["berth_fraction"] == 0 and features["anchor_fraction"] == 0 else ())))
    trajectory_shape = (("moving",) if features["path_km"] >= .5 and features["moving_share"] >= .6 else
                        (("anchor",) if features["stationary_share"] >= .8 and features["heading_variation"] >= .25 else
                         (("berth",) if features["stationary_share"] >= .8 and features["heading_variation"] < .25 else ())))
    supports = (set(kinematic), set(geometry), set(trajectory_shape))
    compatible = set.intersection(*supports) if all(supports) else set()
    return {"kinematic": list(kinematic), "geometry": list(geometry), "trajectory_shape": list(trajectory_shape),
            "sceptical_uncertain": bool(bad_coverage or len(compatible) != 1)}


def strict_consensus(physical: dict, model_a: list[dict], model_b: list[dict], sceptical_uncertain: bool, *, tolerance_h: float) -> dict:
    """No voting: every physical channel must support one state and every model run must select it."""
    all_runs = model_a + model_b
    try:
        support_sets = [set(values) for values in physical.values()]
    except TypeError:
        support_sets = []
    compatible = set.intersection(*support_sets) if len(support_sets) == 3 and all(support_sets) else set()
    physical_label = next(iter(compatible)) if len(compatible) == 1 else "uncertain"
    labels = [physical_label] + [r["primary_class"] for r in all_runs]
    valid = all(label in LABELS for label in labels)
    stable_a = len(model_a) >= 3 and len({r["primary_class"] for r in model_a}) == 1
    stable_b = len(model_b) >= 3 and len({r["primary_class"] for r in model_b}) == 1
    bounds = [(r["state_start_h"], r["state_end_h"]) for r in all_runs]
    bounds_ok = bool(bounds) and max(x[0] for x in bounds) - min(x[0] for x in bounds) <= tolerance_h and max(x[1] for x in bounds) - min(x[1] for x in bounds) <= tolerance_h
    accepted = (valid and labels[0] != "uncertain" and not sceptical_uncertain and stable_a
                and stable_b and len(set(labels)) == 1 and bounds_ok)
    return {"status": "accepted_silver" if accepted else "uncertain", "primary_class": physical_label if accepted else "uncertain",
            "model_a_stable": stable_a, "model_b_stable": stable_b, "bounds_agree": bounds_ok,
            "physical_support": sorted(compatible),
            "reason": "strict unanimity" if accepted else "insufficient independent computational agreement"}


def _month_paths(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    periods = pd.period_range(start.tz_localize(None).to_period("M"), end.tz_localize(None).to_period("M"), freq="M")
    paths = []
    for period in periods:
        folder = PINGS_ROOT / f"year={period.year}" / f"month={period.month:02d}"
        paths.extend(str(p) for p in folder.glob("*.parquet"))
    return paths


def _read_context(mmsi: int, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    files = _month_paths(start, end)
    if not files:
        raise FileNotFoundError(f"no retained pings for {start:%Y-%m}")
    con = duckdb.connect()
    try:
        return con.execute(
            "SELECT timestamp, lon, lat, sog, cog FROM read_parquet(?) WHERE mmsi = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            [files, mmsi, start.to_pydatetime(), end.to_pydatetime()],
        ).fetchdf()
    finally:
        con.close()


def _plot(track: pd.DataFrame, zones: gpd.GeoDataFrame, feature: dict, blind_id: str, evidence: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 6))
    handles = []
    for state, color in (("berth", "#4c78a8"), ("anchor", "#f58518")):
        if len(zones.loc[zones.zone_type.eq(state)]):
            zones.loc[zones.zone_type.eq(state)].plot(ax=ax, color=color, alpha=.22)
            handles.append(Patch(color=color, alpha=.22, label=state))
    ax.plot(track.lon, track.lat, color="#333333", linewidth=1)
    target = track.loc[track.relative_h.between(feature["candidate_start_h"], feature["candidate_end_h"])]
    ax.scatter(target.lon, target.lat, c=target.relative_h, s=8, cmap="viridis")
    ax.set(title=f"{blind_id}: trajectory", xlabel="longitude", ylabel="latitude")
    if handles: ax.legend(handles=handles, loc="best")
    fig.tight_layout(); fig.savefig(evidence / f"{blind_id}_map.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 3)); ax.plot(track.relative_h, track.sog, color="#333333")
    ax.axvspan(feature["candidate_start_h"], feature["candidate_end_h"], color="#4c78a8", alpha=.2)
    ax.set(title=f"{blind_id}: speed", xlabel="relative hours", ylabel="SOG (kn)")
    fig.tight_layout(); fig.savefig(evidence / f"{blind_id}_speed.png", dpi=150); plt.close(fig)


def prepare(out: Path, private_out: Path, *, context_hours: float = 24.0) -> Path:
    if out.exists() or private_out.exists():
        raise FileExistsError("Route-A evidence exists; never overwrite a blinded bundle")
    packet = source_packet(); evidence = out / "evidence"; evidence.mkdir(parents=True); private_out.mkdir(parents=True)
    zones = gpd.read_file(ZONES).to_crs("EPSG:4326")
    rows, mapping = [], []
    for i, rec in packet.reset_index(drop=True).iterrows():
        blind_id = f"BLIND_{i + 1:03d}"; start, end = _utc(rec.start_utc), _utc(rec.end_utc)
        parts = str(rec.episode_id).split("|")
        track = _read_context(int(parts[1]), start - pd.Timedelta(hours=context_hours), end + pd.Timedelta(hours=context_hours))
        if track.empty: raise RuntimeError(f"no pings for {blind_id}")
        track["timestamp"] = pd.to_datetime(track.timestamp, utc=True); base = start - pd.Timedelta(hours=context_hours)
        track["relative_h"] = (track.timestamp - base).dt.total_seconds() / 3600
        feature = episode_features(track, context_hours, context_hours + (end - start).total_seconds() / 3600)
        port_zones = zones.loc[zones.get("complex_id", pd.Series(index=zones.index, dtype=str)).eq(str(rec.port_zone))]
        feature.update(_zone_fractions(track.loc[track.relative_h.between(feature["candidate_start_h"], feature["candidate_end_h"])], port_zones))
        feature["blind_id"] = blind_id; rows.append(feature)
        track[["relative_h", "lon", "lat", "sog", "cog"]].to_csv(evidence / f"{blind_id}_track.csv", index=False, lineterminator="\n")
        _plot(track, port_zones, feature, blind_id, evidence)
        mapping.append({"blind_id": blind_id, "episode_id": rec.episode_id, "source_vessel_hash": rec.vessel_id_hash,
                        "start_utc": rec.start_utc, "end_utc": rec.end_utc, "regime": rec.regime})
    pd.DataFrame(rows).to_csv(out / "evidence_index.csv", index=False, lineterminator="\n")
    pd.DataFrame(mapping).to_csv(private_out / "blind_mapping.csv", index=False, lineterminator="\n")
    manifest = {"route": "A computational silver benchmark", "status": "PREPARED_NOT_LABELLED", "source_packet_sha256": sha256(SOURCE_PACKET),
                "evidence_index_sha256": sha256(out / "evidence_index.csv"),
                "n_episodes": len(rows), "evidence_files": {p.relative_to(out).as_posix(): sha256(p) for p in sorted(evidence.iterdir())},
                "generated_at": datetime.now(UTC).isoformat()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out / "manifest.json"


def verify_local_freeze(bundle: Path) -> dict:
    """Verify every local input to the computational task, including every blinded asset."""
    receipt = json.loads(LOCAL_FREEZE_RECEIPT.read_text(encoding="utf-8"))
    paths = {"source_annotator_packet": SOURCE_PACKET, "evidence_manifest": bundle / "manifest.json",
             "evidence_index": bundle / "evidence_index.csv", "route_a_runner": Path(__file__),
             "protocol_amendment": ROOT / "prereg/amendments/2026-07-17_deep_case_freeze_integrity_and_route_a.md",
             "model_prompt": MODEL_PROMPT}
    for name, path in paths.items():
        if receipt["sha256"].get(name) != sha256(path):
            raise RuntimeError(f"local Route-A freeze mismatch: {name}")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("source_packet_sha256") != sha256(SOURCE_PACKET) or manifest.get("evidence_index_sha256") != sha256(bundle / "evidence_index.csv"):
        raise RuntimeError("Route-A manifest does not bind its source packet and evidence index")
    evidence_lines = []
    for rel, expected in sorted(manifest.get("evidence_files", {}).items()):
        path = bundle / rel
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Route-A evidence mismatch: {rel}")
        evidence_lines.append(f"{rel}:{expected}\n")
    aggregate_hash = sha256_text("".join(evidence_lines))
    if receipt["sha256"].get("evidence_files_aggregate") != aggregate_hash:
        raise RuntimeError("Route-A evidence aggregate mismatch")
    return receipt


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _osf_registration_attributes(registration_id: str) -> dict:
    """Read the immutable OSF registration record rather than trusting a local URL."""
    if not _OSF_ID.fullmatch(registration_id):
        raise RuntimeError("external receipt has an invalid OSF registration identifier")
    request = Request(
        f"https://api.osf.io/v2/registrations/{registration_id}/",
        headers={"Accept": "application/vnd.api+json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (OSError, URLError, ValueError) as exc:
        raise RuntimeError("could not verify the OSF registration record") from exc
    data = payload.get("data", {})
    attributes = data.get("attributes", {})
    if data.get("type") != "registrations" or not isinstance(attributes, dict):
        raise RuntimeError("OSF did not return a registration record")
    return attributes


def require_external_timestamp(receipt_path: Path, bundle: Path) -> dict:
    """Require a separately recorded, verifiable OSF registration before any label output."""
    local = verify_local_freeze(bundle)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "EXTERNALLY_TIMESTAMPED":
        raise RuntimeError("Route A is not externally timestamped; refusing to create labels")
    if receipt.get("local_freeze_receipt_sha256") != sha256(LOCAL_FREEZE_RECEIPT):
        raise RuntimeError("external receipt does not bind the local Route-A receipt")
    if receipt.get("sha256", {}).get("evidence_manifest") != local["sha256"]["evidence_manifest"]:
        raise RuntimeError("external receipt does not bind this evidence manifest")
    registration_id = str(receipt.get("registration_id", ""))
    if not registration_id or receipt.get("registration_url") != f"https://osf.io/{registration_id}/":
        raise RuntimeError("external receipt lacks a canonical OSF registration URL")
    model_a, model_b = receipt.get("model_a"), receipt.get("model_b")
    prompt_a, prompt_b = receipt.get("prompt_a_sha256"), receipt.get("prompt_b_sha256")
    model_fields = ("model_a_version", "model_b_version", "model_a_parameters", "model_b_parameters")
    if (receipt.get("registration_title") != ROUTE_A_TITLE or not isinstance(model_a, str) or not model_a
            or not isinstance(model_b, str) or not model_b or model_a == model_b
            or not isinstance(prompt_a, str) or not _SHA256.fullmatch(prompt_a)
            or not isinstance(prompt_b, str) or not _SHA256.fullmatch(prompt_b)
            or any(field not in receipt for field in model_fields)
            or not isinstance(receipt["model_a_version"], str) or not isinstance(receipt["model_b_version"], str)
            or not isinstance(receipt["model_a_parameters"], dict) or not isinstance(receipt["model_b_parameters"], dict)
            or prompt_a != local["sha256"].get("model_prompt") or prompt_b != local["sha256"].get("model_prompt")):
        raise RuntimeError("external receipt does not bind two distinct frozen model families")
    attributes = _osf_registration_attributes(registration_id)
    if attributes.get("title") != ROUTE_A_TITLE or not attributes.get("date_registered"):
        raise RuntimeError("OSF registration title or immutable registration date does not match the receipt")
    return receipt


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _openrouter_key() -> str:
    """Read the existing local key convention without exposing the secret."""
    for name in ("OPENROUTER_API_KEY", "Open-Router"):
        if os.environ.get(name):
            return os.environ[name]
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() in {"OPENROUTER_API_KEY", "Open-Router"}:
                return value.strip().strip('"').strip("'")
    raise RuntimeError("OpenRouter API key is not configured")


def _episode_message(bundle: Path, feature: dict) -> list[dict]:
    """Build the full frozen, redacted evidence packet for one external model call."""
    blind_id = feature["blind_id"]
    evidence = bundle / "evidence"
    track = (evidence / f"{blind_id}_track.csv").read_text(encoding="utf-8")
    text = (
        MODEL_PROMPT.read_text(encoding="utf-8")
        + "\n\nStructured physical features:\n```json\n"
        + json.dumps(feature, sort_keys=True)
        + "\n```\n\nFull relative-time AIS track CSV:\n```csv\n"
        + track
        + "```"
    )
    content = [{"type": "text", "text": text}]
    for suffix in ("map", "speed"):
        image = (evidence / f"{blind_id}_{suffix}.png").read_bytes()
        content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode("ascii")}})
    return content


def _openrouter_response(payload: dict) -> tuple[str, dict]:
    request = Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {_openrouter_key()}", "Content-Type": "application/json",
                 "Accept": "application/json", "X-OpenRouter-Title": "San Pedro Bay Route-A computational silver benchmark"},
        method="POST",
    )
    try:
        raw = urlopen(request, timeout=300).read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"OpenRouter request failed with HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise RuntimeError("OpenRouter request failed") from exc
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenRouter returned invalid JSON") from exc
    if response.get("error") or not response.get("choices"):
        raise RuntimeError(f"OpenRouter provider error: {response.get('error', {}).get('code', 'unknown')}")
    return raw, response


def _model_record(raw: str, response: dict, *, blind_id: str, replica: int, model_id: str,
                  model_version: str, model_parameters: dict, prompt_sha256: str) -> dict:
    if response.get("model") != model_id or not response.get("id"):
        raise RuntimeError("OpenRouter response does not identify the frozen model and generation")
    content = response["choices"][0].get("message", {}).get("content")
    try:
        label = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{blind_id} model response is not valid JSON") from exc
    if not isinstance(label, dict):
        raise RuntimeError(f"{blind_id} model response must be a JSON object")
    required = {"primary_class", "state_start_h", "state_end_h", "confidence", "evidence", "counterevidence"}
    if required.difference(label):
        raise RuntimeError(f"{blind_id} model response lacks required labelling fields")
    return {
        **{key: label[key] for key in required}, "blind_id": blind_id, "replica": replica,
        "run_id": response["id"], "model_id": model_id, "model_version": model_version,
        "model_parameters": model_parameters, "prompt_sha256": prompt_sha256,
        "response_timestamp_utc": datetime.now(UTC).isoformat(), "raw_response": raw,
        "raw_response_sha256": sha256_text(raw), "usage": response.get("usage", {}),
    }


def write_openrouter_first_pass(bundle: Path, receipt: Path, out: Path, *, channel: str) -> Path:
    """Run one frozen external-model channel; append-only partial output makes outages resumable."""
    if channel not in {"a", "b"}:
        raise ValueError("channel must be 'a' or 'b'")
    external = require_external_timestamp(receipt, bundle)
    if out.exists():
        raise FileExistsError("model first pass already exists")
    model_id, model_version = external[f"model_{channel}"], external[f"model_{channel}_version"]
    parameters, prompt_hash = external[f"model_{channel}_parameters"], external[f"prompt_{channel}_sha256"]
    reserved = {"model", "messages", "stream", "provider"}
    if reserved.intersection(parameters):
        raise RuntimeError("frozen model parameters may not override the Route-A request envelope")
    partial = out.with_suffix(out.suffix + ".partial")
    records = _read_jsonl(partial) if partial.exists() else []
    completed = {(row.get("blind_id"), row.get("replica")) for row in records}
    for feature in pd.read_csv(bundle / "evidence_index.csv").to_dict("records"):
        for replica in range(1, 4):
            if (feature["blind_id"], replica) in completed:
                continue
            payload = {"model": model_id, "stream": False, "messages": [{"role": "user", "content": _episode_message(bundle, feature)}],
                       "provider": {"require_parameters": True}, **parameters}
            raw, response = _openrouter_response(payload)
            record = _model_record(raw, response, blind_id=feature["blind_id"], replica=replica,
                                   model_id=model_id, model_version=model_version, model_parameters=parameters,
                                   prompt_sha256=prompt_hash)
            with partial.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            records.append(record)
    if len(records) != 288:
        raise RuntimeError("Route-A model first pass is incomplete")
    partial.replace(out)
    return out


def _validated_model_runs(rows: list[dict], blind_id: str, *, model_id: str, model_version: str,
                          model_parameters: dict, prompt_sha256: str) -> list[dict]:
    """Reject incomplete, duplicated, or cross-family responses before consensus."""
    if len(rows) < 3:
        raise RuntimeError(f"{blind_id} has fewer than three model runs")
    run_ids = set()
    for row in rows:
        missing = _MODEL_RECORD_FIELDS.difference(row)
        if missing:
            raise RuntimeError(f"{blind_id} model output lacks required fields: {sorted(missing)}")
        if (row["blind_id"] != blind_id or row["model_id"] != model_id or row["model_version"] != model_version
                or row["model_parameters"] != model_parameters or row["prompt_sha256"] != prompt_sha256):
            raise RuntimeError(f"{blind_id} model output is not from the frozen model/prompt channel")
        if row["run_id"] in run_ids or not isinstance(row["run_id"], str) or not row["run_id"]:
            raise RuntimeError(f"{blind_id} model runs are not independently identified")
        run_ids.add(row["run_id"])
        if row["primary_class"] not in LABELS:
            raise RuntimeError(f"{blind_id} model output has an invalid class")
        try:
            start, end, confidence = float(row["state_start_h"]), float(row["state_end_h"]), float(row["confidence"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{blind_id} model output has nonnumeric boundaries or confidence") from exc
        if not (np.isfinite(start) and np.isfinite(end) and start < end and 0 <= confidence <= 1):
            raise RuntimeError(f"{blind_id} model output has invalid boundaries or confidence")
        if not isinstance(row["evidence"], list) or not isinstance(row["counterevidence"], list):
            raise RuntimeError(f"{blind_id} model output must preserve evidence and counterevidence")
        if not isinstance(row["raw_response"], str) or sha256_text(row["raw_response"]) != row["raw_response_sha256"]:
            raise RuntimeError(f"{blind_id} model output does not retain its unhashed raw response")
        try:
            timestamp = pd.Timestamp(row["response_timestamp_utc"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{blind_id} model output has an invalid response timestamp") from exc
        if timestamp.tzinfo is None:
            raise RuntimeError(f"{blind_id} model output timestamp must be UTC-aware")
    return rows


def write_physical_first_pass(bundle: Path, receipt: Path, out: Path) -> Path:
    """Lock deterministic physical channels after timestamping; never overwrite an initial pass."""
    require_external_timestamp(receipt, bundle)
    if out.exists(): raise FileExistsError("physical first pass already exists")
    records = []
    for feature in pd.read_csv(bundle / "evidence_index.csv").to_dict("records"):
        rules = rule_outputs(feature)
        records.append({"blind_id": feature["blind_id"], "physical": {k: rules[k] for k in ("kinematic", "geometry", "trajectory_shape")},
                        "sceptical_uncertain": rules["sceptical_uncertain"], "state_start_h": feature["candidate_start_h"],
                        "state_end_h": feature["candidate_end_h"], "evidence": ["deterministic physical features"], "counterevidence": []})
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    return out


def aggregate(bundle: Path, receipt: Path, physical_path: Path, model_a_path: Path, model_b_path: Path, out: Path) -> Path:
    """Write strict computational consensus and blind class-count precision only; never classifier performance."""
    external = require_external_timestamp(receipt, bundle)
    if out.exists(): raise FileExistsError("consensus output already exists")
    physical = {r["blind_id"]: r for r in _read_jsonl(physical_path)}
    a, b = _read_jsonl(model_a_path), _read_jsonl(model_b_path)
    by_a, by_b = {}, {}
    for row in a: by_a.setdefault(row["blind_id"], []).append(row)
    for row in b: by_b.setdefault(row["blind_id"], []).append(row)
    rows = []
    for feature in pd.read_csv(bundle / "evidence_index.csv").to_dict("records"):
        blind_id = feature["blind_id"]
        if blind_id not in physical or blind_id not in by_a or blind_id not in by_b:
            raise RuntimeError(f"missing first-pass channel for {blind_id}")
        runs_a = _validated_model_runs(by_a[blind_id], blind_id, model_id=external["model_a"],
                                       model_version=external["model_a_version"], model_parameters=external["model_a_parameters"],
                                       prompt_sha256=external["prompt_a_sha256"])
        runs_b = _validated_model_runs(by_b[blind_id], blind_id, model_id=external["model_b"],
                                       model_version=external["model_b_version"], model_parameters=external["model_b_parameters"],
                                       prompt_sha256=external["prompt_b_sha256"])
        decision = strict_consensus(physical[blind_id]["physical"], runs_a, runs_b,
                                    physical[blind_id]["sceptical_uncertain"], tolerance_h=max(.5, .1 * feature["candidate_duration_h"]))
        rows.append({"blind_id": blind_id, **decision})
    frame = pd.DataFrame(rows)
    counts = frame.loc[frame.status.eq("accepted_silver"), "primary_class"].value_counts().to_dict()
    power = {label: round(1.96 * np.sqrt(.85 * .15 / n), 3) for label, n in counts.items() if n}
    payload = {"route": "A computational silver benchmark", "status": "NOT_CLASSIFIER_VALIDATION",
               "consensus": rows, "accepted_class_counts": counts, "ci_halfwidth_at_p0.85": power,
               "sparse_classes_lt20": [label for label, n in counts.items() if n < 20],
               "input_sha256": {p.name: sha256(p) for p in (physical_path, model_a_path, model_b_path)}}
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare blinded Route-A AIS evidence; does not create labels.")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--out", type=Path, required=True); prep.add_argument("--private-out", type=Path, required=True); prep.add_argument("--context-hours", type=float, default=24.0)
    physical = sub.add_parser("physical-first-pass"); physical.add_argument("--bundle", type=Path, required=True); physical.add_argument("--receipt", type=Path, required=True); physical.add_argument("--out", type=Path, required=True)
    consensus = sub.add_parser("aggregate"); consensus.add_argument("--bundle", type=Path, required=True); consensus.add_argument("--receipt", type=Path, required=True); consensus.add_argument("--physical", type=Path, required=True); consensus.add_argument("--model-a", type=Path, required=True); consensus.add_argument("--model-b", type=Path, required=True); consensus.add_argument("--out", type=Path, required=True)
    model = sub.add_parser("model-first-pass"); model.add_argument("--bundle", type=Path, required=True); model.add_argument("--receipt", type=Path, required=True); model.add_argument("--out", type=Path, required=True); model.add_argument("--channel", choices=("a", "b"), required=True)
    args = parser.parse_args()
    if args.command == "prepare": print(prepare(args.out, args.private_out, context_hours=args.context_hours))
    elif args.command == "physical-first-pass": print(write_physical_first_pass(args.bundle, args.receipt, args.out))
    elif args.command == "model-first-pass": print(write_openrouter_first_pass(args.bundle, args.receipt, args.out, channel=args.channel))
    else: print(aggregate(args.bundle, args.receipt, args.physical, args.model_a, args.model_b, args.out))


if __name__ == "__main__":
    main()
