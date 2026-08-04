"""Every path named by an immutable record must still resolve.

Large parts of this repository cannot be reorganised: prereg receipts and claim ledgers name exact
paths beside a SHA-256, and `src/governance/access.py` keys a fail-closed confirmatory lock on literal
roots. This test is the tripwire — `data/processed/ais_dwell_census/` was once staged for deletion while
live code still read it, and nothing noticed.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _guard():
    spec = spec_from_file_location("check_pinned_paths", ROOT / "scripts/check_pinned_paths.py")
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_every_pinned_path_resolves() -> None:
    guard = _guard()
    missing = []
    for pins in (guard.prereg_pins(), guard.ledger_pins()):
        for path in pins:
            if path.startswith(guard.EXPECTED_ABSENT):
                continue
            if path in guard.PROSPECTIVE:
                # named as a future requirement, not an existing artifact; the guard asserts the
                # converse (that it has NOT quietly appeared) — see test below
                continue
            if path in guard.RELOCATIONS:
                assert guard.check_relocation(path) is None, f"declared relocation broken: {path}"
                continue
            if not (ROOT / path).exists():
                missing.append(path)
    assert not missing, f"pinned paths no longer resolve: {sorted(missing)}"


def test_prospective_paths_have_not_silently_appeared() -> None:
    """A prospective path that now exists must be promoted to a real pin, not left unchecked.

    Without this, PROSPECTIVE would be a place to permanently hide a missing file.
    """
    guard = _guard()
    appeared = [p for p in guard.PROSPECTIVE if (ROOT / p).exists()]
    assert not appeared, (
        f"these are listed as prospective but now exist: {appeared}. "
        "Remove them from PROSPECTIVE so they are checked as ordinary pins.")


def test_governance_roots_are_directories_when_present() -> None:
    """The confirmatory lock matches by path ancestry; a root that became a file stops protecting."""
    guard = _guard()
    for root in guard.governance_roots():
        target = ROOT / root
        if target.exists():
            assert target.is_dir(), f"governance root is not a directory: {root}"


def test_guard_detects_a_broken_pin(tmp_path) -> None:
    """The tripwire must be able to trip: a relocation pointing at nothing must be reported."""
    guard = _guard()
    guard.RELOCATIONS["fake/recorded/path.csv"] = (
        "config/does_not_exist_probe.csv", "0" * 64,
        "prereg/amendments/2026-08-05_port_universe_receipt_path_correction.md",
    )
    try:
        assert guard.check_relocation("fake/recorded/path.csv") is not None
    finally:
        del guard.RELOCATIONS["fake/recorded/path.csv"]
