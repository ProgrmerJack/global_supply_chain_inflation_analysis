"""Route-A-v2.1: re-registered output-budget repair for the eight blind candidates."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

import pillar_b_route_a as route_a
import pillar_b_route_a_v2 as v2

ROOT = Path(__file__).resolve().parents[2]
PHYSICAL = ROOT / "data/processed/pillar_b_route_a/physical_first_pass.jsonl"
FREEZE = ROOT / "prereg/studies/route_a/pillar_b_route_a_v21_freeze_receipt.json"
EXTERNAL = ROOT / "prereg/studies/route_a/pillar_b_route_a_v21_external_timestamp.json"
PROTOCOL = ROOT / "prereg/amendments/2026-07-17_route_a_v21_output_budget_repair.md"
TITLE = "San Pedro Bay Route-A-v2.1 exploratory post-screened computational confirmation"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_local_freeze() -> dict:
    """Bind v2.1 to the unchanged, already-public v2 selection and v1 evidence."""
    v2.require_external_timestamp()
    receipt = json.loads(FREEZE.read_text(encoding="utf-8"))
    paths = {
        "candidate_manifest": v2.CANDIDATES, "physical_first_pass": PHYSICAL, "v21_runner": Path(__file__),
        "v21_protocol": PROTOCOL, "model_prompt": route_a.MODEL_PROMPT, "v2_external_receipt": v2.EXTERNAL,
    }
    for name, path in paths.items():
        if receipt.get("sha256", {}).get(name) != route_a.sha256(path):
            raise RuntimeError(f"Route-A-v2.1 local freeze mismatch: {name}")
    v2._candidate_manifest()
    return receipt


def require_external_timestamp(receipt_path: Path = EXTERNAL) -> dict:
    """Refuse v2.1 labels until its separate public registration is verifiable."""
    local = verify_local_freeze()
    if not receipt_path.exists():
        raise RuntimeError("Route-A-v2.1 is not externally timestamped; refusing to create labels")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "EXTERNALLY_TIMESTAMPED":
        raise RuntimeError("Route-A-v2.1 is not externally timestamped; refusing to create labels")
    if receipt.get("local_freeze_receipt_sha256") != route_a.sha256(FREEZE):
        raise RuntimeError("Route-A-v2.1 external receipt does not bind its local freeze receipt")
    if receipt.get("sha256", {}).get("candidate_manifest") != local["sha256"]["candidate_manifest"]:
        raise RuntimeError("Route-A-v2.1 external receipt does not bind the candidate subset")
    registration_id = str(receipt.get("registration_id", ""))
    if receipt.get("registration_url") != f"https://osf.io/{registration_id}/":
        raise RuntimeError("Route-A-v2.1 external receipt lacks a canonical OSF registration URL")
    attributes = route_a._osf_registration_attributes(registration_id)
    if receipt.get("registration_title") != TITLE or attributes.get("title") != TITLE or not attributes.get("date_registered"):
        raise RuntimeError("Route-A-v2.1 OSF registration does not match the frozen protocol")
    required = ("model_kimi", "model_kimi_version", "model_kimi_parameters", "model_claude",
                "model_claude_version", "model_claude_parameters", "prompt_sha256", "claude_cli_version")
    if any(field not in receipt for field in required) or receipt["model_kimi"] == receipt["model_claude"]:
        raise RuntimeError("Route-A-v2.1 external receipt does not bind two distinct model channels")
    if receipt["prompt_sha256"] != local["sha256"]["model_prompt"]:
        raise RuntimeError("Route-A-v2.1 external receipt does not bind the frozen prompt")
    return receipt


def _appendable_records(out: Path) -> tuple[Path, list[dict]]:
    if out.exists():
        raise FileExistsError("Route-A-v2.1 first pass already exists")
    partial = out.with_suffix(out.suffix + ".partial")
    records = _rows(partial) if partial.exists() else []
    if len({(row.get("blind_id"), row.get("replica")) for row in records}) != len(records):
        raise RuntimeError("Route-A-v2.1 partial output contains duplicate runs")
    return partial, records


def write_kimi_first_pass(out: Path) -> Path:
    external = require_external_timestamp(); partial, records = _appendable_records(out)
    completed = {(row["blind_id"], row["replica"]) for row in records}
    for feature in v2._features():
        for replica in range(1, 4):
            if (feature["blind_id"], replica) in completed:
                continue
            payload = {"model": external["model_kimi"], "stream": False,
                       "messages": [{"role": "user", "content": route_a._episode_message(v2.BUNDLE, feature)}],
                       "provider": {"require_parameters": True}, **external["model_kimi_parameters"]}
            raw, response = route_a._openrouter_response(payload)
            record = route_a._model_record(raw, response, blind_id=feature["blind_id"], replica=replica,
                                           model_id=external["model_kimi"], model_version=external["model_kimi_version"],
                                           model_parameters=external["model_kimi_parameters"], prompt_sha256=external["prompt_sha256"])
            with partial.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            records.append(record)
    if len(records) != 24:
        raise RuntimeError("Route-A-v2.1 Kimi first pass is incomplete")
    partial.replace(out)
    return out


def write_claude_first_pass(out: Path) -> Path:
    external = require_external_timestamp(); partial, records = _appendable_records(out)
    completed = {(row["blind_id"], row["replica"]) for row in records}
    for feature in v2._features():
        for replica in range(1, 4):
            if (feature["blind_id"], replica) not in completed:
                record = v2._claude_record(feature, replica, external)
                with partial.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
                records.append(record)
    if len(records) != 24:
        raise RuntimeError("Route-A-v2.1 Claude first pass is incomplete")
    partial.replace(out)
    return out


def aggregate(kimi: Path, claude: Path, out: Path) -> Path:
    external = require_external_timestamp()
    if out.exists():
        raise FileExistsError("Route-A-v2.1 consensus already exists")
    physical = {row["blind_id"]: row for row in _rows(PHYSICAL)}
    by_kimi, by_claude = {}, {}
    for row in _rows(kimi): by_kimi.setdefault(row["blind_id"], []).append(row)
    for row in _rows(claude): by_claude.setdefault(row["blind_id"], []).append(row)
    decisions = []
    for feature in v2._features():
        blind_id = feature["blind_id"]
        k = route_a._validated_model_runs(by_kimi.get(blind_id, []), blind_id, model_id=external["model_kimi"], model_version=external["model_kimi_version"], model_parameters=external["model_kimi_parameters"], prompt_sha256=external["prompt_sha256"])
        c = route_a._validated_model_runs(by_claude.get(blind_id, []), blind_id, model_id=external["model_claude"], model_version=external["model_claude_version"], model_parameters=external["model_claude_parameters"], prompt_sha256=external["prompt_sha256"])
        row = physical.get(blind_id)
        if not row: raise RuntimeError(f"Route-A-v2.1 candidate {blind_id} lacks its physical first pass")
        decisions.append({"blind_id": blind_id, **route_a.strict_consensus(row["physical"], k, c, row["sceptical_uncertain"], tolerance_h=max(.5, .1 * feature["candidate_duration_h"]))})
    payload = {"route": "Route-A-v2.1 exploratory post-screened computational confirmation",
               "status": "NOT_HUMAN_VALIDATION_NOT_CLASSIFIER_VALIDATION_NOT_PILLAR_B_GATE",
               "denominator": "eight deterministic physical candidates only; not the original 96-episode packet",
               "consensus": decisions,
               "accepted_class_counts": pd.Series([row["primary_class"] for row in decisions if row["status"] == "accepted_silver"]).value_counts().to_dict(),
               "input_sha256": {path.name: route_a.sha256(path) for path in (PHYSICAL, kimi, claude)}}
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run only the public Route-A-v2.1 output-budget repair.")
    sub = parser.add_subparsers(dest="command", required=True)
    kimi = sub.add_parser("kimi-first-pass"); kimi.add_argument("--out", type=Path, required=True)
    claude = sub.add_parser("claude-first-pass"); claude.add_argument("--out", type=Path, required=True)
    summary = sub.add_parser("aggregate"); summary.add_argument("--kimi", type=Path, required=True); summary.add_argument("--claude", type=Path, required=True); summary.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "kimi-first-pass": print(write_kimi_first_pass(args.out))
    elif args.command == "claude-first-pass": print(write_claude_first_pass(args.out))
    else: print(aggregate(args.kimi, args.claude, args.out))


if __name__ == "__main__":
    main()
