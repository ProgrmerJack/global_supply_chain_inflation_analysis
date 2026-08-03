import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))


def test_claude_version_normalisation_accepts_the_documented_banner(monkeypatch):
    import pillar_b_route_a_v22 as v22

    class Result:
        stdout = "2.1.199 (Claude Code)\n"

    monkeypatch.setattr(v22.subprocess, "run", lambda *args, **kwargs: Result())
    assert v22._cli_version("claude") == "2.1.199"
