#!/usr/bin/env python3
"""Validate the outcome-free Phase-0 registration bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT
BUNDLE_FILES = (
    ROOT / "prereg/protocol/preregistration_v1.md",
    ROOT / "prereg/protocol/hypotheses_estimands.md",
    ROOT / "prereg/protocol/port_selection_rule.md",
    ROOT / "prereg/protocol/causal_diagrams.md",
    ROOT / "prereg/protocol/holdout_access_policy.md",
    ROOT / "prereg/protocol/analysis_decision_tree.md",
    ROOT / "prereg/governance/evidence_status.csv",
    ROOT / "prereg/protocol/prior_knowledge.md",
    ROOT / "prereg/governance/port_universe_receipt.json",
    ROOT / "prereg/governance/holdout_registry.csv",
    ROOT / "config/protocol/data_sources.yml",
    ROOT / "config/protocol/gates.yml",
    ROOT / "config/protocol/ports.schema.yml",
    ROOT / "config/registries/port_complex_crosswalk.csv",
    ROOT / "docs/novelty_firewall_2026Q2.md",
    ROOT / "docs/search_log.csv",
    ROOT / "docs/competitor_matrix.csv",
    REPOSITORY_ROOT / "data/processed/port_registry.csv",
)
MANIFEST_PATH = ROOT / "prereg/governance/osf_manifest.csv"
FORBIDDEN = re.compile(r"\b(TBD|TODO|FIXME|implement later|fill in details)\b", re.I)


def validate_gate_configuration(text: str) -> list[str]:
    """Check that the registered scientific gates match the strategic plan."""
    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return [f"invalid gate configuration: {error}"]

    if not isinstance(config, dict) or not isinstance(config.get("gates"), dict):
        return ["gate configuration must contain a gates mapping"]

    gates = config["gates"]
    errors = [f"missing gate: G{i}" for i in range(1, 11) if f"G{i}" not in gates]
    if gates.get("G10", {}).get("name") != "Equity":
        errors.append("G10 must be named Equity")
    if "journal_decision" not in config:
        errors.append("missing separate journal_decision")
    return errors


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_rows() -> list[tuple[str, str]]:
    """Return the deterministic, metadata-only OSF bundle manifest."""
    return [
        (path.relative_to(REPOSITORY_ROOT).as_posix(), sha256(path))
        for path in BUNDLE_FILES
    ]


def validate_manifest(path: Path) -> list[str]:
    """Require exact manifest membership and hashes before registration."""
    if not path.exists():
        return [f"Phase-0 artifact not yet created: {path.relative_to(ROOT)}"]

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    errors: list[str] = []
    if reader.fieldnames != ["path", "sha256"]:
        errors.append("osf manifest header must be path,sha256")
        return errors

    actual = {row.get("path", ""): row.get("sha256", "") for row in rows}
    if len(actual) != len(rows):
        errors.append("osf manifest contains duplicate paths")
    expected = dict(manifest_rows())
    if set(actual) != set(expected):
        errors.append("osf manifest membership does not match the frozen registration bundle")
    for label, digest in expected.items():
        if actual.get(label) != digest:
            errors.append(f"osf manifest hash mismatch: {label}")
    if any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in actual.values()):
        errors.append("osf manifest contains a non-SHA-256 digest")
    return errors


def validate_novelty_access() -> list[str]:
    """Do not freeze a search record that documents unresolved external access."""
    path = ROOT / "docs/search_log.csv"
    if not path.exists():
        return ["missing novelty search log"]
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    blocked = [row["query_id"] for row in rows if row.get("screening_status", "").startswith("blocked-")]
    if blocked:
        return [f"novelty search has unresolved external access: {', '.join(blocked)}"]
    return []


def validate(strict: bool = False) -> list[str]:
    errors: list[str] = []
    for path in BUNDLE_FILES:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(REPOSITORY_ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            errors.append(f"empty required file: {path.relative_to(REPOSITORY_ROOT)}")
        if FORBIDDEN.search(text):
            errors.append(f"placeholder found: {path.relative_to(REPOSITORY_ROOT)}")

    gates = (ROOT / "config/protocol/gates.yml").read_text(encoding="utf-8") if (ROOT / "config/protocol/gates.yml").exists() else ""
    errors.extend(validate_gate_configuration(gates))

    prereg = (ROOT / "prereg/protocol/preregistration_v1.md").read_text(encoding="utf-8") if (ROOT / "prereg/protocol/preregistration_v1.md").exists() else ""
    for phrase in ["exploratory", "holdout", "multiplicity", "deviations", "survival gates"]:
        if phrase.lower() not in prereg.lower():
            errors.append(f"preregistration missing concept: {phrase}")

    if strict:
        errors.extend(validate_novelty_access())
        errors.extend(validate_manifest(MANIFEST_PATH))
    return errors


def write_manifest() -> list[str]:
    """Write a manifest only once all registration prerequisites are complete."""
    errors = validate(strict=False)
    errors.extend(validate_novelty_access())
    if errors:
        return errors
    rows = ["path,sha256", *(f"{label},{digest}" for label, digest in manifest_rows())]
    MANIFEST_PATH.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()

    errors = write_manifest() if args.write_manifest else validate(strict=args.strict)
    if errors:
        print("PROTOCOL VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS protocol completeness")
    print("PROTOCOL READY FOR REGISTRATION" if args.strict else "PHASE-0 SCAFFOLD VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
