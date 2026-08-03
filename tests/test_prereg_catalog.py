"""`prereg/CATALOG.md` is the navigational index over the registration bundle.

A stale index is the exact failure the index exists to prevent: the directory held 104 files whose
names were the only clue to what governed what, and a catalogue that silently stops matching the
directory is worse than none, because it is trusted. `check_pinned_paths.py` catches a file that has
been moved or deleted while still named here; it cannot catch a registration that was *added* and
never listed. This does.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_matches_the_directory():
    result = subprocess.run(
        [sys.executable, "scripts/build_prereg_catalog.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_prereg_file_is_listed():
    catalog = (ROOT / "prereg" / "CATALOG.md").read_text(encoding="utf-8")
    prereg = ROOT / "prereg"
    missing = [
        p.relative_to(prereg).as_posix()
        for p in sorted(prereg.rglob("*"))
        if p.is_file() and p.name not in {"CATALOG.md", "README.md"}
        and p.relative_to(prereg).as_posix() not in catalog
    ]
    assert not missing, f"registrations absent from prereg/CATALOG.md: {missing}"
