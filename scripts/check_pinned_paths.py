"""Fail if a path that an immutable record names has moved or disappeared.

Large parts of this repository cannot be reorganised, because the *path itself* is part of a record:

  1. `prereg/**` freeze receipts, manifests and OSF submission receipts name exact files next to their
     SHA-256. Several are externally timestamped. Moving a named file invalidates the registration.
  2. `manuscript/<bundle>/claims.csv` binds every headline to an `evidence_path` and a `generator_path`.
  3. `src/governance/access.py` keys a fail-closed confirmatory lock on literal roots
     (`data/interim`, `data/holdout`, `results/confirmatory`). Moving one of those directories does not
     raise anything — it silently removes the protection.

This ran into a real failure: `data/processed/ais_dwell_census/` — written by both census builders and
read by `build_dwell_index.py` — was staged into `_REMOVE/` for deletion, which severed the Paper A
macro chain and went unnoticed because nothing checked. This script is that check.

    python scripts/check_pinned_paths.py            # report and exit non-zero on breakage
    python scripts/check_pinned_paths.py --verbose  # also list what resolved

Exit status 0 means every pinned path still resolves.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]

# A repo-relative path with a file extension. Requiring an extension keeps prose mentions of a
# directory out of the "must exist as a file" set.
PATH_WITH_SUFFIX = re.compile(
    r"^(?:results|outputs|prereg|docs|config|data|src|scripts|tests|manuscript)"
    r"/[A-Za-z0-9_./=-]+\.[A-Za-z0-9]{1,6}$"
)

# Paths a record may legitimately name before they exist: holdout targets are created only on unlock,
# and protected roots are "if present, then locked" rather than "must be present".
EXPECTED_ABSENT = ("data/holdout/",)

# Declared relocations: a registration record names a path that has since moved. The receipt is NOT
# rewritten — that would destroy the audit trail — so the move is declared here and the recorded hash is
# re-verified at the new location. Every entry must cite the amendment that authorises it.
#   recorded path -> (current path, sha256 recorded in the receipt, amendment)
RELOCATIONS: dict[str, tuple[str, str, str]] = {
    # NOTE: the KEY is the path as the receipt recorded it and must never be rewritten — only the
    # target moves. (A bulk path-rewrite briefly mangled this key on 2026-08-06; restored.)
    "docs/port_externalities_phase0/config/port_complex_crosswalk.csv": (
        "config/registries/port_complex_crosswalk.csv",
        "1c3a6389db8c2b4ce53369eb6d99db997047dac8d420f5a4f16b822d553758fd",
        "prereg/amendments/2026-08-05_port_universe_receipt_path_correction.md",
    ),
    # docs/superpowers/ was named after the tooling that generated it, not its contents, and hid the
    # fact that it holds superseded (in places rejected) planning material. Renamed to
    # docs/historical_plans/ on 2026-08-06; contents byte-identical, hash re-verified below.
    "docs/superpowers/plans/2026-07-09-national-port-congestion-observatory.md": (
        "docs/historical_plans/plans/2026-07-09-national-port-congestion-observatory.md",
        "fee89c5df2b0d568cad2f86e194bf11eb44aac1b2b1deefb56043a9c2cf39c7b",
        "prereg/amendments/2026-08-06_docs_historical_plans_rename.md",
    ),
    # --- config/ subfoldering, 2026-08-06 ------------------------------------------
    # Receipts named these at config/<file>; the data was grouped into
    # config/{geometry,registries,protocol}/ for legibility. Contents are byte-identical and
    # each hash below is re-verified at the new path on every run.
    "config/baltimore_infrastructure_shock.json": (
        "config/protocol/baltimore_infrastructure_shock.json",
        "4506a5b8809420c189c6910fcbd9e3b410f390d84524385f5b62c8d0aa865bef",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/carb_atberth_recovery_assignment_coverage.csv": (
        "config/registries/carb_atberth_recovery_assignment_coverage.csv",
        "16a05531dbbfc60a67e46e79d1ee7d5fd53d5a84daf2c83137bd61dffcd1e3ad",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/carb_atberth_recovery_coastal_domains.geojson": (
        "config/geometry/carb_atberth_recovery_coastal_domains.geojson",
        "d2a3e91722e04fce1fc2833e677cebf76bfe0f02cb2cf91102bb63a324530162",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/carb_atberth_spb_tanker_terminals.csv": (
        "config/registries/carb_atberth_spb_tanker_terminals.csv",
        "747ec519194c631dd785237a1a0381b4d43f25d8562b409ab7d8c4fe235089db",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/data_acquisition_registry.csv": (
        "config/registries/data_acquisition_registry.csv",
        "0468fe5ba913525b0ac2abc9f11c3ba7a5dae22775e981ed3147752c71fd0042",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/data_sources.yml": (
        "config/protocol/data_sources.yml",
        "a0ff6bce64c1ade3f5301d3b1f84b4f7152f799dabd4fe6fbb526fa42bcda97e",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/g1_operational_comparator_registry.csv": (
        "config/registries/g1_operational_comparator_registry.csv",
        "95e766a446f72540aec91753298ce0ccd1b1ac8b3b196d8dde5e6eedd962198a",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/g1_v2_comparator_registry_draft.csv": (
        "config/registries/g1_v2_comparator_registry_draft.csv",
        "af88f248591cf42150056748de4e9873bfdd78b4cb82996677a35a118780ba07",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/g1_v2_geometry_source_registry_draft.csv": (
        "config/registries/g1_v2_geometry_source_registry_draft.csv",
        "682f6fbfb663bca8c1778b9b31e55ee1db72d2d126a6b2da3cd28ab6f56a4d48",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/g1_v2_terminal_evidence_registry_draft.csv": (
        "config/registries/g1_v2_terminal_evidence_registry_draft.csv",
        "9be022eb84c8576c4c7d8e8675a0a2fb57d3d79bdceebd69e925eddc0230a1da",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/g1v2_comparator_registry.csv": (
        "config/registries/g1v2_comparator_registry.csv",
        "7fcba738e837d529a1ed3c12456ab2806a30bdf2b57df49f17d66afa414247d3",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/gates.yml": (
        "config/protocol/gates.yml",
        "6ba08dfa97ff92bf4d5decdfa3bedcfb91c07d07b602553900635ed8181108d8",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/national_state_zone_coverage.csv": (
        "config/registries/national_state_zone_coverage.csv",
        "14ab6e9b0e90085bc17807d824b802e702d4a3f4c2a7b1c40badd85909b576db",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/national_state_zone_provenance.json": (
        "config/protocol/national_state_zone_provenance.json",
        "65f0f5ca4ded373228c5a882bbb62d1cc1ff8dd289de85a7cbec2fe4660f44a0",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/national_state_zones.geojson": (
        "config/geometry/national_state_zones.geojson",
        "d3d8fa8f30c42d03656f37a759d70a6fea93f3c383a31db3f715f19caf2d7985",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/port_areas_usace.geojson": (
        "config/geometry/port_areas_usace.geojson",
        "651a7ca775312b7fed37808336854ced4b3b1e90ea4baf47959480cc657b13c0",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/port_complex_crosswalk.csv": (
        "config/registries/port_complex_crosswalk.csv",
        "1c3a6389db8c2b4ce53369eb6d99db997047dac8d420f5a4f16b822d553758fd",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
    "config/ports.schema.yml": (
        "config/protocol/ports.schema.yml",
        "3434af16079731cba4fa0b71f15d0ba6243fb9aaad36a47b21d6a9c5ad661879",
        "prereg/amendments/2026-08-06_config_prereg_subfoldering.md",
    ),
}


# --- prereg/ subfoldering, 2026-08-09 ------------------------------------------------
# prereg/ was flat: 104 files whose names were the only clue to which study they governed. It was
# grouped into protocol/ (cross-cutting registered design), governance/ (locks, registries, OSF
# identity) and studies/<slug>/ (one folder per registered study); amendments/ was left alone.
#
# The receipts, external timestamps, manifests, amendments and result artifacts were NOT rewritten --
# several are third-party timestamped or OSF-registered, so their recorded bytes are an attestation
# and not ours to edit. Instead every path they still name is declared below and its recorded SHA-256
# is re-verified at the new location on every run. Live code, tests and navigational docs WERE
# rewritten to the new paths; those edits are listed with their superseded hashes in the amendment.
#
# 32 entries: the paths that an unrewritten record still names. The other 43 moved files were named
# only by files that were rewritten, so they need no declaration -- and if that is ever wrong, the
# scan below reports them as MISSING rather than passing silently.
_PREREG_SUBFOLDERING = "prereg/amendments/2026-08-09_prereg_subfoldering.md"

PREREG_MOVES: dict[str, tuple[str, str]] = {
    "prereg/ANALYSIS_PLAN.md":
        ("prereg/protocol/ANALYSIS_PLAN.md",
         "07a04f2920eb005ede8d95c2ce86b808af543a6d09497c5e44603b0a37f5c7ba"),
    "prereg/G1v2_freeze_receipt.json":
        ("prereg/studies/g1_v2/G1v2_freeze_receipt.json",
         "785a32bfb06b7d06ea1ffa74d7143044a5bfb1d83750361406523aa05f40b26b"),
    "prereg/G1v2_operational_validation_protocol.md":
        ("prereg/studies/g1_v2/G1v2_operational_validation_protocol.md",
         "f9342d04f9b218f7f827373cd3a89f52496a7117aef932f01ef037e6be7e5730"),
    "prereg/REGISTERED_ANALYSIS_PROTOCOL.md":
        ("prereg/protocol/REGISTERED_ANALYSIS_PROTOCOL.md",
         "87e17a4793b40b854aa6dd869c25192e97be44030ec5749ab86543e9f2f8cc3d"),
    "prereg/analysis_decision_tree.md":
        ("prereg/protocol/analysis_decision_tree.md",
         "39690c56ff3afc89eea1c0d28efea8fba81ae1a0d622ba0312b6c78004aa78f6"),
    "prereg/baltimore_external_timestamp.json":
        ("prereg/studies/baltimore/baltimore_external_timestamp.json",
         "c54ac5d0cc4c47740458bd489018868fec57bf30ff0f67346f8ee90c141ee8f3"),
    "prereg/baltimore_manifest.csv":
        ("prereg/studies/baltimore/baltimore_manifest.csv",
         "52b941af642ecd3f84889b07c38f34ea41e2eabe486a61cef5f1b0aebeb707c4"),
    "prereg/baltimore_unlock.json":
        ("prereg/studies/baltimore/baltimore_unlock.json",
         "b47ab71c2b02e7e152ee91031f0f0fd4f062d00674faf98cf51420ac2d0c8326"),
    "prereg/causal_diagrams.md":
        ("prereg/protocol/causal_diagrams.md",
         "e24208a224bb25953ee56c6b6743737893e2d11558b2763240f296dbf749d2fb"),
    "prereg/deep_case_SPB_freeze_receipt.json":
        ("prereg/studies/deep_case_spb/deep_case_SPB_freeze_receipt.json",
         "98553de2a6d06d5129cb690f9b915294dd5696aeb02db295dbf48d6377075359"),
    "prereg/deep_case_SPB_preregistration.md":
        ("prereg/studies/deep_case_spb/deep_case_SPB_preregistration.md",
         "318ed5d76c6809943e99c67fcef24ad262c0722984fa11b3147675f09ed75d86"),
    "prereg/evidence_status.csv":
        ("prereg/governance/evidence_status.csv",
         "d9bf9e7611bb67fd4320700193a2c85c99e794d7a9e1809b547b50b0fad50776"),
    "prereg/holdout_access_policy.md":
        ("prereg/protocol/holdout_access_policy.md",
         "193a86a3c05ac7d2d1e54f94bae8612fc8157c71bbd7a6eb8cdbacb103f53f01"),
    "prereg/holdout_registry.csv":
        ("prereg/governance/holdout_registry.csv",
         "46dfec5b6b9a605162d999afda9c0cd0560b46c821787e408944101899729b59"),
    "prereg/hypotheses_estimands.md":
        ("prereg/protocol/hypotheses_estimands.md",
         "8780cfa673b5198e488499228af818d5c27e113ea5238cec5ae06e165b7ce4a6"),
    "prereg/nature_recovery_manifest.csv":
        ("prereg/studies/nature_recovery/nature_recovery_manifest.csv",
         "02fbf2bf1bc75be45003290e8a57113d1ae3e83cf645d5d556558532187ae45d"),
    "prereg/nature_recovery_r_g1_length_source_correction_2026-07-28.json":
        ("prereg/studies/nature_recovery/nature_recovery_r_g1_length_source_correction_2026-07-28.json",
         "bdeed6189b0a50e47a103bd2a11d3fbb16cc7efd13843e7de9b2dbb9148e617c"),
    "prereg/nature_recovery_r_g1_technical_correction_2026-07-28.json":
        ("prereg/studies/nature_recovery/nature_recovery_r_g1_technical_correction_2026-07-28.json",
         "ede89639d62f996541d35ca477ade8492b2a29a0d1fa6b78f1e4c4b31c8a80ab"),
    "prereg/pillar_b_route_a_model_prompt.md":
        ("prereg/studies/route_a/pillar_b_route_a_model_prompt.md",
         "252453fe6cbff68c73c053d8b6dc6c0480a537a3f087adb3d37b53d68281d775"),
    "prereg/pillar_b_route_a_v22_completion_receipt.json":
        ("prereg/studies/route_a/pillar_b_route_a_v22_completion_receipt.json",
         "3ac70d8413d723944c18593f762dc58b70f22358484b187c78729fccdd8a39c4"),
    "prereg/pillar_b_route_a_v22_completion_test_output.txt":
        ("prereg/studies/route_a/pillar_b_route_a_v22_completion_test_output.txt",
         "bcf0729e74f697cfe35c302aa6425d5eb9b50fc7c935d8dcf449ddcc279f0544"),
    "prereg/port_selection_rule.md":
        ("prereg/protocol/port_selection_rule.md",
         "fe2f2822450bb4927a3d9b8782541a98f37c4b7a37cad53e7084d24c97fb5bbf"),
    "prereg/port_universe_receipt.json":
        ("prereg/governance/port_universe_receipt.json",
         "3030f36bfbef4a043fcd6cd5b69f14da41a3925a6f43097d9f169546e57debaa"),
    "prereg/preregistration_v1.md":
        ("prereg/protocol/preregistration_v1.md",
         "2209dcb6591e21ce3f9c0451f8ffb57f1116f2fc4a3def3246ca5ab2e63cc306"),
    "prereg/prior_knowledge.md":
        ("prereg/protocol/prior_knowledge.md",
         "641f55335d1a42335181a50522feba8b6a1201119ecab0189587b467554b3fbb"),
    "prereg/spb_direct_measurement_freeze_receipt.json":
        ("prereg/studies/spb_queue_boundary/spb_direct_measurement_freeze_receipt.json",
         "594f294d852ec52385507cb22189c7ee718b34bd73515874f28f16dc7add36d7"),
    "prereg/spb_emissions_component_validation_development_freeze.json":
        ("prereg/studies/spb_emissions/spb_emissions_component_validation_development_freeze.json",
         "3be5782338a970711482af71fdf122bbf3f5bf1e22a12bedc19dec4449bb4dbf"),
    "prereg/spb_emissions_component_validation_freeze_receipt.json":
        ("prereg/studies/spb_emissions/spb_emissions_component_validation_freeze_receipt.json",
         "9b6a17f28ae867af09b1f4a0d95a15d41a7c2918844b91a13dcbfc6ee2e3e43e"),
    "prereg/spb_emissions_component_validation_holdout_execution_freeze.json":
        ("prereg/studies/spb_emissions/spb_emissions_component_validation_holdout_execution_freeze.json",
         "ea98d8a927819f03190ec061d799bf99e8cd49a666409b2144b6ef753a4b72f8"),
    "prereg/spb_labour_spatial_replication_correction_freeze_receipt.json":
        ("prereg/studies/spb_labour/spb_labour_spatial_replication_correction_freeze_receipt.json",
         "8b327f6a6945023dadf55e6dfaccc12c9bd43c9b8b68a6194bd926de3fcadeab"),
    "prereg/spb_labour_spatial_replication_freeze_receipt.json":
        ("prereg/studies/spb_labour/spb_labour_spatial_replication_freeze_receipt.json",
         "fa0e7a59a0aef2ed499abf02083e9e893623c824c7647538a253c608c95e4341"),
    "prereg/spb_queue_boundary_reanalysis_freeze_receipt.json":
        ("prereg/studies/spb_queue_boundary/spb_queue_boundary_reanalysis_freeze_receipt.json",
         "3581b95afcfa4a7299f55136b6c1dabb68fe5f25a0b5684f65d18b712a7f8837"),
}

RELOCATIONS.update(
    {old: (new, sha, _PREREG_SUBFOLDERING) for old, (new, sha) in PREREG_MOVES.items()}
)


# Paths named in a registration as a FUTURE requirement rather than an existing artifact. These are
# not broken pins: the record says "when G1-v2 is executed it must produce this", and G1-v2 has not
# been executed. Each entry must state the guard that enforces the requirement if the work ever runs,
# so this list cannot quietly become a place to hide genuinely missing files.
PROSPECTIVE: dict[str, str] = {
    # prereg/amendments/2026-07-15_g1_v2_preparation_draft.md declares the unlock contract for a G1-v2
    # execution that has not happened: data/interim/g1_v2, data/holdout/g1_v2 and
    # results/confirmatory/g1_v2 do not exist, and no g1_v2_unlock.json has been issued. The manifest
    # becomes mandatory at first execution, enforced fail-closed by
    # src/governance/access.py::assert_g1_v2_unlocked.
    "prereg/amendments/g1_v2_manifest.csv":
        "G1-v2 is unexecuted; required at first run by access.py::assert_g1_v2_unlocked",
}


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_relocation(recorded: str) -> str | None:
    """Return an error string if a declared relocation no longer holds, else None."""
    current, expected_sha, amendment = RELOCATIONS[recorded]
    if not (ROOT / amendment).is_file():
        return (f"  MISSING AMENDMENT  {amendment}\n"
                f"           declares the relocation of {recorded}")
    target = ROOT / current
    if not target.is_file():
        return (f"  MISSING  {current}\n"
                f"           relocated target of {recorded} (see {amendment})")
    actual = _sha256(target)
    if actual != expected_sha:
        return (f"  HASH CHANGED  {current}\n"
                f"           relocated target of {recorded}\n"
                f"           recorded {expected_sha}\n"
                f"           actual   {actual}")
    return None


def _walk(node, out: set[str]) -> None:
    """Collect every path-shaped string value anywhere in a receipt."""
    if isinstance(node, dict):
        for value in node.values():
            _walk(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, out)
    elif isinstance(node, str):
        candidate = node.strip()
        if PATH_WITH_SUFFIX.match(candidate):
            out.add(candidate)


def prereg_pins() -> dict[str, set[str]]:
    """path -> set of prereg records naming it."""
    pins: dict[str, set[str]] = {}
    for record in sorted((ROOT / "prereg").rglob("*.json")):
        rel = str(record.relative_to(ROOT)).replace("\\", "/")
        try:
            payload = json.loads(record.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        found: set[str] = set()
        _walk(payload, found)
        for path in found:
            pins.setdefault(path, set()).add(rel)
    for manifest in sorted((ROOT / "prereg").rglob("*.csv")):
        rel = str(manifest.relative_to(ROOT)).replace("\\", "/")
        try:
            text = manifest.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for cell in re.split(r"[,\r\n\"]+", text):
            candidate = cell.strip()
            if PATH_WITH_SUFFIX.match(candidate):
                pins.setdefault(candidate, set()).add(rel)

    # Markdown protocols and amendments name paths too, and until 2026-08-06 this checker did not read
    # them -- so `prereg/protocol/REGISTERED_ANALYSIS_PROTOCOL.md` could name a file that had been moved or
    # deleted and nothing would notice. The registration is the whole record, not just its JSON.
    # Paths are taken from inline-code spans and bare tokens; prose mentions without a suffix are
    # ignored by PATH_WITH_SUFFIX, and a `?` suffix guards against trailing punctuation.
    md_token = re.compile(r"`([^`\s]+)`|(?<![\w/])((?:prereg|config|docs|src|data|results|outputs|"
                          r"scripts|manuscript|tests)/[\w./-]+)")
    for doc in sorted((ROOT / "prereg").rglob("*.md")):
        rel = str(doc.relative_to(ROOT)).replace("\\", "/")
        try:
            text = doc.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in md_token.finditer(text):
            candidate = (m.group(1) or m.group(2) or "").strip().rstrip(".,;:)")
            if candidate and PATH_WITH_SUFFIX.match(candidate) and "/" in candidate:
                pins.setdefault(candidate, set()).add(rel)
    return pins


def ledger_pins() -> dict[str, set[str]]:
    """path -> set of claim ids requiring it."""
    pins: dict[str, set[str]] = {}
    # Each paper is a self-sufficient bundle: manuscript/<bundle>/claims.csv
    for ledger in sorted((ROOT / "manuscript").glob("*/claims.csv")):
        name = f"{ledger.parent.name}/claims.csv"
        with ledger.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                targets = [row.get("evidence_path"), row.get("generator_path")]
                targets += (row.get("test_paths") or "").split(";")
                targets += (row.get("guard") or "").split(";")
                for target in targets:
                    if target and target.strip():
                        pins.setdefault(target.strip(), set()).add(f"{name}:{row['claim_id']}")
    return pins


def governance_roots() -> list[str]:
    """The literal roots the confirmatory lock is keyed on, read from the guard itself."""
    source = (ROOT / "src/governance/access.py").read_text(encoding="utf-8")
    return sorted({m for m in re.findall(r'ROOT\s*/\s*"([^"]+)"', source)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="also list paths that resolved")
    args = parser.parse_args()

    failures: list[str] = []
    checked = 0

    relocated = 0
    prospective = 0
    for label, pins in (("prereg record", prereg_pins()), ("claim ledger", ledger_pins())):
        for path in sorted(pins):
            if path.startswith(EXPECTED_ABSENT):
                continue
            checked += 1
            if path in PROSPECTIVE:
                if (ROOT / path).exists():
                    failures.append(
                        f"  NOW EXISTS  {path}\n"
                        f"           listed as prospective ({PROSPECTIVE[path]}) but the file is present;\n"
                        f"           remove it from PROSPECTIVE so it is checked as a real pin")
                else:
                    prospective += 1
                    if args.verbose:
                        print(f"  ..  {path} (prospective: {PROSPECTIVE[path]})")
                continue
            if path in RELOCATIONS:
                problem = check_relocation(path)
                if problem:
                    failures.append(problem)
                else:
                    relocated += 1
                    if args.verbose:
                        print(f"  ok  {path} -> {RELOCATIONS[path][0]} (hash re-verified)")
                continue
            if not (ROOT / path).exists():
                sources = ", ".join(sorted(pins[path])[:3])
                failures.append(f"  MISSING  {path}\n           named by {label}: {sources}")
            elif args.verbose:
                print(f"  ok  {path}")

    # Governance roots are "locked if present", so absence is allowed — but a root that exists must be
    # a directory, or the ancestry check in access.py silently stops matching.
    for root in governance_roots():
        target = ROOT / root
        if target.exists() and not target.is_dir():
            failures.append(f"  NOT A DIRECTORY  {root}\n           governance lock keys on this root")

    if failures:
        print(f"{len(failures)} pinned path(s) broken out of {checked} checked:\n")
        print("\n".join(failures))
        print("\nThese paths are named inside immutable records. Restore the file at its recorded path,")
        print("or, if the move was deliberate, amend the naming record and re-verify its hash.")
        return 1

    print(f"all {checked} pinned paths resolve "
          f"({relocated} via declared relocation with hash re-verified; "
          f"{prospective} prospective, not yet created; "
          f"{len(governance_roots())} governance roots checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
