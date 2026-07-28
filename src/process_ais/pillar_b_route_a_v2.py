"""Route-A-v2: post-screened, blinded computational confirmation.

This is an explicitly exploratory follow-up to the public all-96 Route-A
registration.  It never creates human labels, classifier-validation metrics,
or a Pillar-B decision.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

import pillar_b_route_a as route_a

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "data/interim/pillar_b_route_a"
PHYSICAL = ROOT / "data/processed/pillar_b_route_a/physical_first_pass.jsonl"
CANDIDATES = ROOT / "data/processed/pillar_b_route_a_v2/candidate_manifest.json"
FREEZE = ROOT / "prereg/studies/route_a/pillar_b_route_a_v2_freeze_receipt.json"
EXTERNAL = ROOT / "prereg/studies/route_a/pillar_b_route_a_v2_external_timestamp.json"
PROTOCOL = ROOT / "prereg/amendments/2026-07-17_route_a_v2_exploratory_postscreen.md"
TITLE = "San Pedro Bay Route-A-v2 exploratory post-screened computational confirmation"

_CLAUDE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["primary_class", "state_start_h", "state_end_h", "confidence", "evidence", "counterevidence"],
    "properties": {
        "primary_class": {"type": "string", "enum": sorted(route_a.LABELS)},
        "state_start_h": {"type": "number"}, "state_end_h": {"type": "number"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "counterevidence": {"type": "array", "items": {"type": "string"}},
    },
}


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _physical_support(row: dict) -> list[str]:
    sets = [set(row["physical"][key]) for key in ("kinematic", "geometry", "trajectory_shape")]
    return sorted(set.intersection(*sets)) if all(sets) else []


def _selected(row: dict) -> bool:
    return not row["sceptical_uncertain"] and len(_physical_support(row)) == 1


def prepare_candidates(out: Path = CANDIDATES) -> Path:
    """Derive the fixed v2 subset from the already timestamped physical screen."""
    route_a.require_external_timestamp(route_a.ROOT / "prereg/studies/route_a/pillar_b_route_a_external_timestamp.json", BUNDLE)
    if out.exists():
        raise FileExistsError("Route-A-v2 candidate manifest already exists; never overwrite a selection")
    selected = [row for row in _rows(PHYSICAL) if _selected(row)]
    if len(selected) != 8:
        raise RuntimeError(f"expected eight deterministic physical candidates, found {len(selected)}")
    payload = {
        "route": "Route-A-v2 exploratory post-screened computational confirmation",
        "status": "PREPARED_NOT_MODEL_LABELLED",
        "selection_rule": "sceptical_uncertain is false and all three physical support sets intersect in exactly one state",
        "source_physical_first_pass_sha256": route_a.sha256(PHYSICAL),
        "source_evidence_manifest_sha256": route_a.sha256(BUNDLE / "manifest.json"),
        "n_candidates": len(selected),
        "candidates": [{"blind_id": row["blind_id"], "physical_support": _physical_support(row),
                        "state_start_h": row["state_start_h"], "state_end_h": row["state_end_h"]} for row in selected],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def _candidate_manifest() -> dict:
    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    if data.get("n_candidates") != 8 or len(data.get("candidates", [])) != 8:
        raise RuntimeError("Route-A-v2 candidate manifest is not the fixed eight-episode subset")
    if data.get("source_physical_first_pass_sha256") != route_a.sha256(PHYSICAL):
        raise RuntimeError("Route-A-v2 candidate manifest does not bind the physical first pass")
    if data.get("source_evidence_manifest_sha256") != route_a.sha256(BUNDLE / "manifest.json"):
        raise RuntimeError("Route-A-v2 candidate manifest does not bind the blinded evidence bundle")
    return data


def verify_local_freeze() -> dict:
    """Verify v1 provenance and every v2 local input before external calls."""
    route_a.require_external_timestamp(route_a.ROOT / "prereg/studies/route_a/pillar_b_route_a_external_timestamp.json", BUNDLE)
    receipt = json.loads(FREEZE.read_text(encoding="utf-8"))
    paths = {
        "candidate_manifest": CANDIDATES, "physical_first_pass": PHYSICAL, "v2_runner": Path(__file__),
        "v2_protocol": PROTOCOL, "model_prompt": route_a.MODEL_PROMPT,
        "v1_external_receipt": route_a.ROOT / "prereg/studies/route_a/pillar_b_route_a_external_timestamp.json",
    }
    for name, path in paths.items():
        if receipt.get("sha256", {}).get(name) != route_a.sha256(path):
            raise RuntimeError(f"Route-A-v2 local freeze mismatch: {name}")
    _candidate_manifest()
    return receipt


def require_external_timestamp(receipt_path: Path = EXTERNAL) -> dict:
    """Fail closed until the distinct v2 protocol has a public OSF timestamp."""
    local = verify_local_freeze()
    if not receipt_path.exists():
        raise RuntimeError("Route-A-v2 is not externally timestamped; refusing to create labels")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "EXTERNALLY_TIMESTAMPED":
        raise RuntimeError("Route-A-v2 is not externally timestamped; refusing to create labels")
    if receipt.get("local_freeze_receipt_sha256") != route_a.sha256(FREEZE):
        raise RuntimeError("Route-A-v2 external receipt does not bind its local freeze receipt")
    if receipt.get("sha256", {}).get("candidate_manifest") != local["sha256"]["candidate_manifest"]:
        raise RuntimeError("Route-A-v2 external receipt does not bind the candidate subset")
    registration_id = str(receipt.get("registration_id", ""))
    if receipt.get("registration_url") != f"https://osf.io/{registration_id}/":
        raise RuntimeError("Route-A-v2 external receipt lacks a canonical OSF registration URL")
    attributes = route_a._osf_registration_attributes(registration_id)
    if receipt.get("registration_title") != TITLE or attributes.get("title") != TITLE or not attributes.get("date_registered"):
        raise RuntimeError("Route-A-v2 OSF registration does not match the frozen protocol")
    required = ("model_kimi", "model_kimi_version", "model_kimi_parameters", "model_claude",
                "model_claude_version", "model_claude_parameters", "prompt_sha256", "claude_cli_version")
    if any(field not in receipt for field in required) or receipt["model_kimi"] == receipt["model_claude"]:
        raise RuntimeError("Route-A-v2 external receipt does not bind two distinct model channels")
    if receipt["prompt_sha256"] != local["sha256"]["model_prompt"]:
        raise RuntimeError("Route-A-v2 external receipt does not bind the frozen prompt")
    return receipt


def _features() -> list[dict]:
    candidates = _candidate_manifest()
    wanted = {row["blind_id"] for row in candidates["candidates"]}
    all_features = pd.read_csv(BUNDLE / "evidence_index.csv").to_dict("records")
    selected = [row for row in all_features if row["blind_id"] in wanted]
    if len(selected) != len(wanted):
        raise RuntimeError("Route-A-v2 candidate is absent from the blinded evidence index")
    return selected


def _appendable_records(out: Path) -> tuple[Path, list[dict]]:
    if out.exists():
        raise FileExistsError("Route-A-v2 first pass already exists")
    partial = out.with_suffix(out.suffix + ".partial")
    records = _rows(partial) if partial.exists() else []
    seen = {(row.get("blind_id"), row.get("replica")) for row in records}
    if len(seen) != len(records):
        raise RuntimeError("Route-A-v2 partial output contains duplicate runs")
    return partial, records


def write_kimi_first_pass(out: Path) -> Path:
    """Run the frozen Kimi channel exactly three times for every selected blind ID."""
    external = require_external_timestamp(); partial, records = _appendable_records(out)
    completed = {(row["blind_id"], row["replica"]) for row in records}
    for feature in _features():
        for replica in range(1, 4):
            if (feature["blind_id"], replica) in completed:
                continue
            payload = {"model": external["model_kimi"], "stream": False,
                       "messages": [{"role": "user", "content": route_a._episode_message(BUNDLE, feature)}],
                       "provider": {"require_parameters": True}, **external["model_kimi_parameters"]}
            raw, response = route_a._openrouter_response(payload)
            record = route_a._model_record(raw, response, blind_id=feature["blind_id"], replica=replica,
                                           model_id=external["model_kimi"], model_version=external["model_kimi_version"],
                                           model_parameters=external["model_kimi_parameters"], prompt_sha256=external["prompt_sha256"])
            with partial.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            records.append(record)
    if len(records) != 24:
        raise RuntimeError("Route-A-v2 Kimi first pass is incomplete")
    partial.replace(out)
    return out


def _claude_task(feature: dict) -> str:
    blind_id = feature["blind_id"]
    track = (BUNDLE / "evidence" / f"{blind_id}_track.csv").read_text(encoding="utf-8")
    return (route_a.MODEL_PROMPT.read_text(encoding="utf-8") + "\n\nStructured physical features:\n```json\n"
            + json.dumps(feature, sort_keys=True) + "\n```\n\nFull relative-time AIS track CSV:\n```csv\n" + track
            + "```\n\nThe trajectory map is map.png and the speed-time plot is speed.png. Read all three files before responding.")


def _claude_record(feature: dict, replica: int, external: dict) -> dict:
    """Use an ephemeral, Read-only directory so Claude cannot see the repository or hidden mapping."""
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("Claude Code is not installed")
    version = subprocess.run([claude, "--version"], text=True, capture_output=True, check=True).stdout.strip()
    if version != external["claude_cli_version"]:
        raise RuntimeError("Claude Code version differs from the frozen Route-A-v2 receipt")
    with tempfile.TemporaryDirectory(prefix="route_a_v2_") as temp:
        work = Path(temp); blind_id = feature["blind_id"]
        (work / "task.md").write_text(_claude_task(feature), encoding="utf-8")
        for suffix in ("map", "speed"):
            shutil.copyfile(BUNDLE / "evidence" / f"{blind_id}_{suffix}.png", work / f"{suffix}.png")
        command = [claude, "-p", "--model", external["model_claude_parameters"]["cli_model"],
                   "--output-format", "json", "--json-schema", json.dumps(_CLAUDE_SCHEMA), "--safe-mode",
                   "--no-session-persistence", "--tools", "Read", "--permission-mode", "dontAsk",
                   "--effort", external["model_claude_parameters"]["effort"],
                   "Read task.md, map.png, and speed.png. Follow task.md exactly; return only the required JSON object."]
        result = subprocess.run(command, cwd=work, text=True, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError(f"Claude Code failed with exit code {result.returncode}: {result.stderr.strip()}")
    raw = result.stdout
    try:
        response, label = json.loads(raw), None
        label = response.get("result")
        label = json.loads(label) if isinstance(label, str) else label
    except (AttributeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Claude Code did not return a structured label") from exc
    models = response.get("modelUsage", {})
    if set(models) != {external["model_claude_version"]}:
        raise RuntimeError("Claude Code used a model other than the frozen Route-A-v2 channel")
    required = {"primary_class", "state_start_h", "state_end_h", "confidence", "evidence", "counterevidence"}
    if not isinstance(label, dict) or required.difference(label):
        raise RuntimeError("Claude Code label lacks required fields")
    return {**{key: label[key] for key in required}, "blind_id": feature["blind_id"], "replica": replica,
            "run_id": response.get("session_id"), "model_id": external["model_claude"],
            "model_version": external["model_claude_version"], "model_parameters": external["model_claude_parameters"],
            "prompt_sha256": external["prompt_sha256"], "response_timestamp_utc": datetime.now(UTC).isoformat(),
            "raw_response": raw, "raw_response_sha256": route_a.sha256_text(raw), "usage": models}


def write_claude_first_pass(out: Path) -> Path:
    """Run Claude Sonnet in an isolated temporary directory, three fresh sessions per blind ID."""
    external = require_external_timestamp(); partial, records = _appendable_records(out)
    completed = {(row["blind_id"], row["replica"]) for row in records}
    for feature in _features():
        for replica in range(1, 4):
            if (feature["blind_id"], replica) not in completed:
                record = _claude_record(feature, replica, external)
                with partial.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
                records.append(record)
    if len(records) != 24:
        raise RuntimeError("Route-A-v2 Claude first pass is incomplete")
    partial.replace(out)
    return out


def aggregate(kimi: Path, claude: Path, out: Path) -> Path:
    """Report consensus only within the selected subset; never score a classifier."""
    external = require_external_timestamp()
    if out.exists():
        raise FileExistsError("Route-A-v2 consensus already exists")
    physical = {row["blind_id"]: row for row in _rows(PHYSICAL)}
    by_kimi, by_claude = {}, {}
    for row in _rows(kimi): by_kimi.setdefault(row["blind_id"], []).append(row)
    for row in _rows(claude): by_claude.setdefault(row["blind_id"], []).append(row)
    decisions = []
    for feature in _features():
        blind_id = feature["blind_id"]
        k = route_a._validated_model_runs(by_kimi.get(blind_id, []), blind_id, model_id=external["model_kimi"],
                                          model_version=external["model_kimi_version"], model_parameters=external["model_kimi_parameters"],
                                          prompt_sha256=external["prompt_sha256"])
        c = route_a._validated_model_runs(by_claude.get(blind_id, []), blind_id, model_id=external["model_claude"],
                                          model_version=external["model_claude_version"], model_parameters=external["model_claude_parameters"],
                                          prompt_sha256=external["prompt_sha256"])
        row = physical.get(blind_id)
        if not row:
            raise RuntimeError(f"Route-A-v2 candidate {blind_id} lacks its physical first pass")
        decisions.append({"blind_id": blind_id, **route_a.strict_consensus(row["physical"], k, c, row["sceptical_uncertain"],
                         tolerance_h=max(.5, .1 * feature["candidate_duration_h"]))})
    payload = {"route": "Route-A-v2 exploratory post-screened computational confirmation",
               "status": "NOT_HUMAN_VALIDATION_NOT_CLASSIFIER_VALIDATION_NOT_PILLAR_B_GATE",
               "denominator": "eight deterministic physical candidates only; not the original 96-episode packet",
               "consensus": decisions,
               "accepted_class_counts": pd.Series([row["primary_class"] for row in decisions if row["status"] == "accepted_silver"]).value_counts().to_dict(),
               "input_sha256": {path.name: route_a.sha256(path) for path in (PHYSICAL, kimi, claude)}}
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run only the public, exploratory Route-A-v2 subset.")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare-candidates"); prep.add_argument("--out", type=Path, default=CANDIDATES)
    kimi = sub.add_parser("kimi-first-pass"); kimi.add_argument("--out", type=Path, required=True)
    claude = sub.add_parser("claude-first-pass"); claude.add_argument("--out", type=Path, required=True)
    summary = sub.add_parser("aggregate"); summary.add_argument("--kimi", type=Path, required=True); summary.add_argument("--claude", type=Path, required=True); summary.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare-candidates": print(prepare_candidates(args.out))
    elif args.command == "kimi-first-pass": print(write_kimi_first_pass(args.out))
    elif args.command == "claude-first-pass": print(write_claude_first_pass(args.out))
    else: print(aggregate(args.kimi, args.claude, args.out))


if __name__ == "__main__":
    main()
