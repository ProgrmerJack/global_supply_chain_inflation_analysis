"""Fail closed before any held-out or confirmatory file is opened."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_ROOT = ROOT / "prereg"
# prereg/ was subfoldered on 2026-08-09 (amendments/2026-08-09_prereg_subfoldering.md). These joins
# are built from basenames, so they are invisible to a path search — they were the one place the move
# could have broken the lock silently instead of loudly. Cross-cutting locks live in governance/;
# a study's unlock and manifest live with the rest of that study.
GOVERNANCE_ROOT = PROTOCOL_ROOT / "governance"
UNLOCK_PATH = GOVERNANCE_ROOT / "CONFIRMATORY_UNLOCK.json"
MANIFEST_PATH = GOVERNANCE_ROOT / "osf_manifest.csv"
G1_V2_ROOT = PROTOCOL_ROOT / "amendments"
G1_V2_UNLOCK_PATH = G1_V2_ROOT / "g1_v2_unlock.json"
G1_V2_MANIFEST_PATH = G1_V2_ROOT / "g1_v2_manifest.csv"
NATURE_RECOVERY_ROOT = PROTOCOL_ROOT / "studies/nature_recovery"
NATURE_RECOVERY_UNLOCK_PATH = NATURE_RECOVERY_ROOT / "nature_recovery_unlock.json"
NATURE_RECOVERY_MANIFEST_PATH = NATURE_RECOVERY_ROOT / "nature_recovery_manifest.csv"
BALTIMORE_ROOT = PROTOCOL_ROOT / "studies/baltimore"
BALTIMORE_UNLOCK_PATH = BALTIMORE_ROOT / "baltimore_unlock.json"
BALTIMORE_MANIFEST_PATH = BALTIMORE_ROOT / "baltimore_manifest.csv"
# Confirmatory-protected roots (national ingestion + holdouts + confirmatory results). data/processed is
# deliberately NOT protected: after consolidation it holds both pilot (exploratory) and national artifacts.
PROTECTED_ROOTS = (
    ROOT / "data/holdout",
    ROOT / "data/interim",
    ROOT / "results/confirmatory",
)
G1_V2_PROTECTED_ROOTS = (
    ROOT / "data/interim/g1_v2",
    ROOT / "data/holdout/g1_v2",
    ROOT / "results/confirmatory/g1_v2",
)
NATURE_RECOVERY_PROTECTED_ROOTS = (
    ROOT / "data/interim/nature_recovery",
    ROOT / "data/holdout/nature_recovery",
    ROOT / "results/confirmatory/nature_recovery",
)
NATURE_RECOVERY_ACQUISITION_ROOT = ROOT / "data/interim/nature_recovery/coastal_pings"
BALTIMORE_PROTECTED_ROOTS = (
    ROOT / "data/interim/baltimore_shock",
    ROOT / "data/holdout/baltimore_shock",
    ROOT / "results/confirmatory/baltimore_shock",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_protected(path: Path, protected_roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved == root.resolve() or root.resolve() in resolved.parents for root in protected_roots)


def _locked(scope: str, message: str) -> PermissionError:
    return PermissionError(f"{scope} access is locked: {message}")


def _assert_unlocked(
    path: Path,
    *,
    protected_roots: tuple[Path, ...],
    unlock_path: Path,
    manifest_path: Path,
    scope: str,
) -> dict | None:
    if not _is_protected(path, protected_roots):
        return None
    if not unlock_path.exists():
        raise _locked(scope, f"no {unlock_path.name} is present")
    if not manifest_path.exists():
        raise _locked(scope, f"the registered manifest is absent ({manifest_path.name})")

    try:
        unlock = json.loads(unlock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _locked(scope, f"unlock record is unreadable ({error})") from error

    if not str(unlock.get("registration_url", "")).startswith("https://osf.io/"):
        raise _locked(scope, "unlock record lacks an OSF receipt URL")
    if unlock.get("manifest_sha256") != _sha256(manifest_path):
        raise _locked(scope, "unlock manifest hash does not match the local manifest")
    return unlock


def assert_confirmatory_unlocked(path: Path) -> None:
    """Require a verified registration unlock for protected local paths only."""
    _assert_unlocked(
        Path(path),
        protected_roots=PROTECTED_ROOTS,
        unlock_path=UNLOCK_PATH,
        manifest_path=MANIFEST_PATH,
        scope="confirmatory",
    )


def assert_g1_v2_unlocked(path: Path) -> None:
    """Require a separate G1-v2 receipt before opening its comparator or label data."""
    _assert_unlocked(
        Path(path),
        protected_roots=G1_V2_PROTECTED_ROOTS,
        unlock_path=G1_V2_UNLOCK_PATH,
        manifest_path=G1_V2_MANIFEST_PATH,
        scope="G1-v2",
    )


def assert_nature_recovery_unlocked(path: Path) -> None:
    """Require the independent recovery registration before protected access."""
    path = Path(path)
    unlock = _assert_unlocked(
        Path(path),
        protected_roots=NATURE_RECOVERY_PROTECTED_ROOTS,
        unlock_path=NATURE_RECOVERY_UNLOCK_PATH,
        manifest_path=NATURE_RECOVERY_MANIFEST_PATH,
        scope="Nature recovery",
    )
    if (
        unlock is not None
        and not _is_protected(path, (NATURE_RECOVERY_ACQUISITION_ROOT,))
        and not unlock.get("protected_outcome_analysis_unlocked", False)
    ):
        raise _locked("Nature recovery", "OSF registration is not yet public; acquisition only")


def assert_baltimore_unlocked(path: Path) -> None:
    """Require this study's accepted public timestamp before opening its outcomes."""
    unlock = _assert_unlocked(
        Path(path),
        protected_roots=BALTIMORE_PROTECTED_ROOTS,
        unlock_path=BALTIMORE_UNLOCK_PATH,
        manifest_path=BALTIMORE_MANIFEST_PATH,
        scope="Baltimore shock",
    )
    if unlock is not None and not unlock.get("protected_outcome_analysis_unlocked", False):
        raise _locked("Baltimore shock", "public registration is not accepted")
