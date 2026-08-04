import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/acquire"))
SPEC = importlib.util.spec_from_file_location("carb_atberth", ROOT / "src/acquire/carb_atberth.py")
carb_atberth = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(carb_atberth)


def test_acquisition_resumes_and_detects_tampering(monkeypatch, tmp_path):
    monkeypatch.setattr(carb_atberth, "OUT", tmp_path)
    monkeypatch.setattr(carb_atberth, "SOURCES", {
        "regulation.pdf": "https://example.test/regulation.pdf",
        "plans.html": "https://example.test/plans",
    })
    calls = []

    def fetch(url):
        calls.append(url)
        return b"%PDF-1.7 synthetic" if url.endswith(".pdf") else b"<!doctype html><title>plans</title>"

    carb_atberth.acquire(fetch=fetch)
    carb_atberth.acquire(fetch=lambda _: pytest.fail("verified files should resume without fetching"))
    assert len(calls) == 2
    assert len(json.loads((tmp_path / "regulation.pdf.manifest.json").read_text())) > 0

    (tmp_path / "regulation.pdf").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        carb_atberth.acquire(fetch=fetch)
