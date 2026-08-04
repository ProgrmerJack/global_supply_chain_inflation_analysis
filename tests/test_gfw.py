"""One end-to-end check for the registered GFW speed-bin cache."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_speed_bin_cache_excludes_smoke_day_resumes_and_detects_tampering(tmp_path):
    from acquire import gfw

    calls = []

    def fetch(box, date_range, **kwargs):
        calls.append((box, date_range, kwargs))
        return pd.DataFrame(
            [
                {"date": "2021-12-01", "lat": 33.0, "lon": -120.0, "hours": 9, "vesselIDs": 1},
                {"date": "2021-12-02", "lat": 33.0, "lon": -120.0, "hours": 1, "vesselIDs": 1},
                {"date": "2021-12-02", "lat": 33.0, "lon": -120.0, "hours": 2, "vesselIDs": 1},
            ]
        ), {"query_url": "https://example.test/query", "dataset_version": "presence:v4"}

    verify = lambda: {"registration_id": "5sc3v", "registration_url": "https://osf.io/5sc3v/"}
    result = gfw.acquire_spb_speed_bins(
        tmp_path, years=range(2021, 2022), speed_bins=("<2",), verify=verify, fetch=fetch
    )
    artifact = tmp_path / "spb_cargo_speed_lt2_2021.parquet"
    cached = pd.read_parquet(artifact)
    assert calls[0][2]["filters"] == ("vessel_type='cargo' AND speed='<2'",)
    assert cached[["date", "hours", "vessel_positions"]].to_dict("records") == [
        {"date": "2021-12-02", "hours": 3, "vessel_positions": 2}
    ]
    assert result.iloc[0]["sha256"] == gfw._sha256(artifact)

    gfw.acquire_spb_speed_bins(
        tmp_path,
        years=range(2021, 2022),
        speed_bins=("<2",),
        verify=verify,
        fetch=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache was not resumed")),
    )
    artifact.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="unverifiable existing"):
        gfw.acquire_spb_speed_bins(
            tmp_path, years=range(2021, 2022), speed_bins=("<2",), verify=verify, fetch=fetch
        )


def test_direct_gate_requires_direction_timing_and_speed_specificity():
    from analysis.h1_offshore_cargo import evaluate_bts_gate

    rng = np.random.default_rng(7)
    queue = rng.permutation(np.arange(1, 81)).astype(float)
    weekly = pd.DataFrame(
        {
            "los_angeles_long_beach": queue,
            "low_total_0_300": queue * 2,
            "movement_total_0_300": queue.max() - queue,
        }
    )
    decision, _ = evaluate_bts_gate(weekly, draws=200)
    assert decision["status"] == "pass"
    assert decision["best_gfw_shift_observations"] == {"pearson": 0, "spearman": 0}
