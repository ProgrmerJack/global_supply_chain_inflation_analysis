"""G1 development diagnostics (g1_diagnostics.py) — decomposition + metric matching logic on synthetic data."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def _frames(r_target, n_ports=4, years=("2019", "2020", "2021")):
    rng = np.random.default_rng(0)
    ais_rows, off_rows = [], []
    for i in range(n_ports):
        for y in years:
            for mo in range(1, 13):
                base = rng.normal(0, 1)
                off = base
                ais = r_target * base + np.sqrt(max(1 - r_target ** 2, 0)) * rng.normal(0, 1)
                ym = f"{y}-{mo:02d}"
                ais_rows.append({"port_complex_id": f"p{i}", "year_month": ym, "ais_activity": ais})
                off_rows.append({"port_complex_id": f"p{i}", "year_month": ym, "official_activity": off})
    return pd.DataFrame(ais_rows), pd.DataFrame(off_rows)


def test_median_corr_recovers_planted():
    from process_ais.g1_diagnostics import _median_corr

    ais, official = _frames(0.9)
    m = ais.merge(official, on=["port_complex_id", "year_month"])
    r, n = _median_corr(m, "ais_activity", "official_activity")
    assert 0.75 < r < 1.0 and n == 4


def test_decomposition_has_period_keys():
    from process_ais.g1_diagnostics import correlation_decomposition

    ais, official = _frames(0.8)
    out = correlation_decomposition(ais, official)
    for key in ("full", "year_2019", "year_2020", "drop_2020", "drop_2020_2021", "deseasonalized", "yoy_change"):
        assert key in out, f"missing decomposition key {key}"
    assert 0.5 < out["full"][0] <= 1.0


def test_metric_matching_ranks_measures():
    from process_ais.g1_diagnostics import metric_matching

    ais, official = _frames(0.9)
    panel = ais.rename(columns={"ais_activity": "unique_cargo_vessels"})
    panel["unique_vessels"] = panel["unique_cargo_vessels"] + np.random.default_rng(1).normal(0, 3, len(panel))
    panel["freight_port_calls"] = panel["unique_cargo_vessels"]
    out = metric_matching(panel, official)
    assert "unique_cargo_vessels" in out and "unique_vessels" in out and "freight_port_calls" in out
    assert out["unique_cargo_vessels"][0] >= out["unique_vessels"][0] - 0.05  # cleaner measure not worse


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
