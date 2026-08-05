import numpy as np
import pandas as pd

from src.analysis import h6_labour_spatial_replication as h6
from src.acquire import labour_disruption_sources as sources


def test_frozen_hac_model_detects_disruption_and_recovery():
    rng = np.random.default_rng(20260723)
    dates = pd.date_range("2012-01-01", "2015-12-31", freq="D")
    event = dates.to_series(index=range(len(dates))).between(*h6.EVENT).to_numpy()
    recovery = dates.to_series(index=range(len(dates))).between(*h6.RECOVERY).to_numpy()
    outcome = pd.Series(
        2 + np.sin(2 * np.pi * np.arange(len(dates)) / 365.25)
        + 0.8 * event + 0.05 * recovery + rng.normal(0, 0.15, len(dates))
    )
    result, terms = h6.fit_effect(pd.DataFrame({"date": dates}), outcome)
    indexed = terms.set_index("term")
    assert indexed.loc["disruption", "ci_low"] > 0
    assert h6._contrast(result, "disruption", "recovery")["ci_low"] > 0


def test_daily_builder_preserves_hours_across_date_index():
    rows = []
    for year in range(2012, 2016):
        for speed in h6.gfw.SPEED_BINS:
            rows.append({
                "date": f"{year}-01-15",
                "lat": 33.72,
                "lon": -118.20,
                "speed_bin": speed,
                "hours": 3.0 if speed == "<2" else 1.0,
            })
    daily = h6.build_daily_panel(pd.DataFrame(rows))
    assert daily["date"].dtype.kind == "M"
    assert daily["low_0-50nm"].notna().all()
    assert daily["low_0-50nm"].sum() == 12.0
    assert daily["low_total_0_300"].sum() == 12.0


def test_chronology_sources_are_hash_resumable(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "OUT", tmp_path)
    calls = []
    sources.acquire(fetch=lambda url: calls.append(url) or b"<!doctype html><html>official</html>")
    sources.acquire(fetch=lambda _url: (_ for _ in ()).throw(AssertionError("redownloaded")))
    assert len(calls) == 3
    assert len(pd.read_csv(tmp_path / "manifest.csv")) == 3
