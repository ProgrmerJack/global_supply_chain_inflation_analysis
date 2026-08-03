import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))


def test_v21_refuses_to_label_without_its_own_external_receipt(tmp_path, monkeypatch):
    import pillar_b_route_a_v21 as v21

    monkeypatch.setattr(v21, "verify_local_freeze", lambda: {"sha256": {"candidate_manifest": "manifest", "model_prompt": "prompt"}})
    missing = tmp_path / "missing.json"
    with pytest.raises(RuntimeError, match="not externally timestamped"):
        v21.require_external_timestamp(missing)
