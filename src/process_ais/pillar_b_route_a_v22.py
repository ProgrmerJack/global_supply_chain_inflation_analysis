"""Route-A-v2.2: re-registered Claude Code service-contract repair."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

import pillar_b_route_a as route_a
import pillar_b_route_a_v2 as v2
import pillar_b_route_a_v21 as v21

ROOT = Path(__file__).resolve().parents[2]
PHYSICAL = ROOT / "data/processed/pillar_b_route_a/physical_first_pass.jsonl"
FREEZE = ROOT / "prereg/studies/route_a/pillar_b_route_a_v22_freeze_receipt.json"
EXTERNAL = ROOT / "prereg/studies/route_a/pillar_b_route_a_v22_external_timestamp.json"
PROTOCOL = ROOT / "prereg/amendments/2026-07-17_route_a_v22_claude_service_repair.md"
TITLE = "San Pedro Bay Route-A-v2.2 exploratory post-screened computational confirmation"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_local_freeze() -> dict:
    v21.require_external_timestamp()
    receipt = json.loads(FREEZE.read_text(encoding="utf-8"))
    paths = {"candidate_manifest": v2.CANDIDATES, "physical_first_pass": PHYSICAL,
             "v22_runner": Path(__file__), "v22_protocol": PROTOCOL,
             "model_prompt": route_a.MODEL_PROMPT, "v21_external_receipt": v21.EXTERNAL}
    for name, path in paths.items():
        if receipt.get("sha256", {}).get(name) != route_a.sha256(path):
            raise RuntimeError(f"Route-A-v2.2 local freeze mismatch: {name}")
    v2._candidate_manifest()
    return receipt


def require_external_timestamp(receipt_path: Path = EXTERNAL) -> dict:
    local = verify_local_freeze()
    if not receipt_path.exists():
        raise RuntimeError("Route-A-v2.2 is not externally timestamped; refusing to create labels")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "EXTERNALLY_TIMESTAMPED":
        raise RuntimeError("Route-A-v2.2 is not externally timestamped; refusing to create labels")
    if receipt.get("local_freeze_receipt_sha256") != route_a.sha256(FREEZE):
        raise RuntimeError("Route-A-v2.2 external receipt does not bind its local freeze receipt")
    if receipt.get("sha256", {}).get("candidate_manifest") != local["sha256"]["candidate_manifest"]:
        raise RuntimeError("Route-A-v2.2 external receipt does not bind the candidate subset")
    registration_id = str(receipt.get("registration_id", ""))
    if receipt.get("registration_url") != f"https://osf.io/{registration_id}/":
        raise RuntimeError("Route-A-v2.2 external receipt lacks a canonical OSF registration URL")
    attrs = route_a._osf_registration_attributes(registration_id)
    if receipt.get("registration_title") != TITLE or attrs.get("title") != TITLE or not attrs.get("date_registered"):
        raise RuntimeError("Route-A-v2.2 OSF registration does not match the frozen protocol")
    required = ("model_kimi", "model_kimi_version", "model_kimi_parameters", "model_claude",
                "model_claude_version", "model_claude_parameters", "claude_cli_version",
                "claude_model_usage", "prompt_sha256")
    if any(field not in receipt for field in required) or receipt["model_kimi"] == receipt["model_claude"]:
        raise RuntimeError("Route-A-v2.2 external receipt does not bind two distinct model channels")
    if receipt["prompt_sha256"] != local["sha256"]["model_prompt"]:
        raise RuntimeError("Route-A-v2.2 external receipt does not bind the frozen prompt")
    return receipt


def _appendable(out: Path) -> tuple[Path, list[dict]]:
    if out.exists(): raise FileExistsError("Route-A-v2.2 first pass already exists")
    partial = out.with_suffix(out.suffix + ".partial"); rows = _rows(partial) if partial.exists() else []
    if len({(r.get("blind_id"), r.get("replica")) for r in rows}) != len(rows):
        raise RuntimeError("Route-A-v2.2 partial output contains duplicate runs")
    return partial, rows


def _cli_version(claude: str) -> str:
    raw = subprocess.run([claude, "--version"], text=True, capture_output=True, check=True).stdout.strip()
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?: \(Claude Code\))?", raw)
    if not match: raise RuntimeError("Claude Code returned an unrecognised version string")
    return match.group(1)


def _claude_record(feature: dict, replica: int, external: dict) -> dict:
    claude = shutil.which("claude")
    if not claude or _cli_version(claude) != external["claude_cli_version"]:
        raise RuntimeError("Claude Code version differs from the frozen Route-A-v2.2 receipt")
    with tempfile.TemporaryDirectory(prefix="route_a_v22_") as temp:
        work = Path(temp); blind_id = feature["blind_id"]
        (work / "task.md").write_text(v2._claude_task(feature), encoding="utf-8")
        for suffix in ("map", "speed"): shutil.copyfile(v2.BUNDLE / "evidence" / f"{blind_id}_{suffix}.png", work / f"{suffix}.png")
        command = [claude, "-p", "--model", external["model_claude_parameters"]["cli_model"],
                   "--output-format", "json", "--json-schema", json.dumps(v2._CLAUDE_SCHEMA), "--safe-mode",
                   "--no-session-persistence", "--tools", "Read", "--permission-mode", "dontAsk",
                   "--effort", external["model_claude_parameters"]["effort"],
                   "Read task.md, map.png, and speed.png. Follow task.md exactly; return only the required JSON object."]
        result = subprocess.run(command, cwd=work, text=True, capture_output=True, timeout=600)
    if result.returncode: raise RuntimeError(f"Claude Code failed with exit code {result.returncode}: {result.stderr.strip()}")
    raw = result.stdout
    try:
        response = json.loads(raw); label = response.get("result"); label = json.loads(label) if isinstance(label, str) else label
    except (AttributeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Claude Code did not return a structured label") from exc
    models = response.get("modelUsage", {})
    if sorted(models) != sorted(external["claude_model_usage"]):
        raise RuntimeError("Claude Code used a service set other than the frozen Route-A-v2.2 channel")
    required = {"primary_class", "state_start_h", "state_end_h", "confidence", "evidence", "counterevidence"}
    if not isinstance(label, dict) or required.difference(label): raise RuntimeError("Claude Code label lacks required fields")
    return {**{key: label[key] for key in required}, "blind_id": feature["blind_id"], "replica": replica,
            "run_id": response.get("session_id"), "model_id": external["model_claude"],
            "model_version": external["model_claude_version"], "model_parameters": external["model_claude_parameters"],
            "prompt_sha256": external["prompt_sha256"], "response_timestamp_utc": datetime.now(UTC).isoformat(),
            "raw_response": raw, "raw_response_sha256": route_a.sha256_text(raw), "usage": models}


def _write(out: Path, channel: str) -> Path:
    external = require_external_timestamp(); partial, rows = _appendable(out); done = {(r["blind_id"], r["replica"]) for r in rows}
    for feature in v2._features():
        for replica in range(1, 4):
            if (feature["blind_id"], replica) in done: continue
            if channel == "kimi":
                payload = {"model": external["model_kimi"], "stream": False, "messages": [{"role": "user", "content": route_a._episode_message(v2.BUNDLE, feature)}], "provider": {"require_parameters": True}, **external["model_kimi_parameters"]}
                raw, response = route_a._openrouter_response(payload)
                record = route_a._model_record(raw, response, blind_id=feature["blind_id"], replica=replica, model_id=external["model_kimi"], model_version=external["model_kimi_version"], model_parameters=external["model_kimi_parameters"], prompt_sha256=external["prompt_sha256"])
            else:
                record = _claude_record(feature, replica, external)
            with partial.open("a", encoding="utf-8") as handle: handle.write(json.dumps(record, sort_keys=True) + "\n")
            rows.append(record)
    if len(rows) != 24: raise RuntimeError(f"Route-A-v2.2 {channel} first pass is incomplete")
    partial.replace(out); return out


def aggregate(kimi: Path, claude: Path, out: Path) -> Path:
    external = require_external_timestamp()
    if out.exists(): raise FileExistsError("Route-A-v2.2 consensus already exists")
    physical = {r["blind_id"]: r for r in _rows(PHYSICAL)}; a, b = {}, {}
    for row in _rows(kimi): a.setdefault(row["blind_id"], []).append(row)
    for row in _rows(claude): b.setdefault(row["blind_id"], []).append(row)
    decisions = []
    for feature in v2._features():
        blind_id = feature["blind_id"]
        ka = route_a._validated_model_runs(a.get(blind_id, []), blind_id, model_id=external["model_kimi"], model_version=external["model_kimi_version"], model_parameters=external["model_kimi_parameters"], prompt_sha256=external["prompt_sha256"])
        cb = route_a._validated_model_runs(b.get(blind_id, []), blind_id, model_id=external["model_claude"], model_version=external["model_claude_version"], model_parameters=external["model_claude_parameters"], prompt_sha256=external["prompt_sha256"])
        row = physical.get(blind_id)
        if not row: raise RuntimeError(f"Route-A-v2.2 candidate {blind_id} lacks its physical first pass")
        decisions.append({"blind_id": blind_id, **route_a.strict_consensus(row["physical"], ka, cb, row["sceptical_uncertain"], tolerance_h=max(.5, .1 * feature["candidate_duration_h"]))})
    payload = {"route": "Route-A-v2.2 exploratory post-screened computational confirmation", "status": "NOT_HUMAN_VALIDATION_NOT_CLASSIFIER_VALIDATION_NOT_PILLAR_B_GATE", "denominator": "eight deterministic physical candidates only; not the original 96-episode packet", "consensus": decisions, "accepted_class_counts": pd.Series([r["primary_class"] for r in decisions if r["status"] == "accepted_silver"]).value_counts().to_dict(), "input_sha256": {p.name: route_a.sha256(p) for p in (PHYSICAL, kimi, claude)}}
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8"); return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run only the public Route-A-v2.2 service-contract repair.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("kimi", "claude"):
        command = sub.add_parser(f"{name}-first-pass"); command.add_argument("--out", type=Path, required=True)
    summary = sub.add_parser("aggregate"); summary.add_argument("--kimi", type=Path, required=True); summary.add_argument("--claude", type=Path, required=True); summary.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "kimi-first-pass": print(_write(args.out, "kimi"))
    elif args.command == "claude-first-pass": print(_write(args.out, "claude"))
    else: print(aggregate(args.kimi, args.claude, args.out))


if __name__ == "__main__": main()
