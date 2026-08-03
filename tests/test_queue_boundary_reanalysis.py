"""Synthetic checks for the post-outcome-known queue-boundary reanalysis."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_supported_dates_use_half_open_ranges_and_exclude_smoke_day():
    from analysis.queue_boundary_reanalysis import SMOKE_EXCLUSION, supported_dates

    manifest = pd.DataFrame({"date_range": ["2020-01-01,2020-12-31", "2021-01-01,2021-12-31"]})
    dates = supported_dates(manifest)
    assert pd.Timestamp("2020-12-30") in dates
    assert pd.Timestamp("2020-12-31") not in dates
    assert SMOKE_EXCLUSION not in dates


def test_geometry_separates_radial_bands_and_west_sector():
    from analysis.queue_boundary_reanalysis import add_geometry

    # Points due west of SPB at approximately 140 and 160 nautical miles.
    cells = pd.DataFrame({
        "lat": [33.72, 33.72],
        "lon": [-121.0, -121.4],
        "speed_bin": ["<2", "10-15"],
    })
    result = add_geometry(cells)
    assert result["sector"].tolist() == ["west", "west"]
    assert result["band"].tolist() == ["inner", "outer"]
    assert result["speed_group"].tolist() == ["low", "movement"]


def test_weekly_share_is_ratio_of_aggregated_hours_not_mean_daily_ratios():
    from analysis.queue_boundary_reanalysis import build_weekly_panel

    dates = pd.date_range("2021-01-04", periods=7, freq="D")
    daily = pd.DataFrame({"date": dates})
    for sector in ("west", "north", "south"):
        daily[f"low_inner_{sector}_hours"] = [9, 0, 0, 0, 0, 0, 0]
        daily[f"low_outer_{sector}_hours"] = [1, 100, 0, 0, 0, 0, 0]
        for speed in ("low", "low4", "movement"):
            for band in ("inner", "outer"):
                daily[f"{speed}_{band}_{sector}_density"] = 1.0
        daily[f"low_outer_share_{sector}"] = daily[f"low_outer_{sector}_hours"] / (
            daily[f"low_inner_{sector}_hours"] + daily[f"low_outer_{sector}_hours"]
        ).replace(0, np.nan)
        daily[f"ddd_{sector}"] = 0.0
        daily[f"ddd4_{sector}"] = 0.0
    daily["low_50-150nm"] = 1.0
    daily["low_150-300nm"] = 1.0
    daily["low_total_0_300"] = 3.0
    daily["low_offshore_share"] = 2 / 3
    weekly = build_weekly_panel(daily)
    assert weekly.loc[0, "low_outer_share_west"] == (101 / 7) / ((9 / 7) + (101 / 7))


def test_level_shift_and_gate_recover_synthetic_redistribution():
    from analysis.queue_boundary_reanalysis import EVENT, evaluate_gate

    weeks = pd.date_range("2019-01-07", "2023-12-25", freq="W-MON")
    post = weeks >= EVENT + pd.Timedelta(weeks=12)
    rng = np.random.default_rng(11)
    weekly = pd.DataFrame({"week_start": weeks, "days_included": 7})
    weekly["ddd_west"] = rng.normal(0, 0.03, len(weeks)) + post * 1.5
    weekly["ddd4_west"] = rng.normal(0, 0.03, len(weeks)) + post * 1.4
    weekly["low_outer_share_west"] = 0.25 + rng.normal(0, 0.005, len(weeks)) + post * 0.25
    weekly["ddd_north"] = rng.normal(0, 0.03, len(weeks))
    weekly["ddd_south"] = rng.normal(0, 0.03, len(weeks))
    weekly["low_0-50nm"] = 100 + rng.normal(0, 1, len(weeks)) - post * 30
    weekly["low_150-300nm"] = 40 + rng.normal(0, 1, len(weeks)) + post * 30
    weekly["low_total_0_300"] = 200 + rng.normal(0, 1, len(weeks))
    coverage = {"artifact_count": 35, "all_hashes_valid": True}
    decision, _ = evaluate_gate(weekly, coverage)
    assert decision["primary_ddd"]["ci_low"] > 0
    assert decision["primary_low_speed_outer_share"]["ci_low"] > 0
    assert decision["broad_absolute_changes"]["near_0_50nm"]["ci_high"] < 0
    assert decision["broad_absolute_changes"]["far_150_300nm"]["ci_low"] > 0


def test_sparse_primary_share_fails_closed_without_changing_threshold():
    from analysis.queue_boundary_reanalysis import EVENT, fit_or_unestimable

    weeks = pd.date_range(EVENT - pd.Timedelta(weeks=52), EVENT + pd.Timedelta(weeks=52), freq="W-MON")
    weekly = pd.DataFrame({"week_start": weeks, "days_included": 7, "share": np.nan})
    pre = weekly["week_start"] < EVENT
    post = weekly["week_start"] >= EVENT + pd.Timedelta(weeks=12)
    weekly.loc[pre, "share"] = np.linspace(0.2, 0.3, pre.sum())
    weekly.loc[post, "share"] = np.linspace(0.4, 0.5, post.sum())
    # Leave only 38 mature observations: the frozen 39-week threshold must not be relaxed.
    mature_indices = weekly.index[post]
    weekly.loc[mature_indices[38:], "share"] = np.nan
    result = fit_or_unestimable(weekly, "share")
    assert not result["estimable"]
    assert result["n_mature_weeks"] == 38
    assert result["estimate"] is None
