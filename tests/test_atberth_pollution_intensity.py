import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_plume_weight_is_larger_when_wind_comes_from_source():
    from analysis.atberth_pollution_intensity import build_plume_exposure

    cells = pd.DataFrame({
        "hour_utc": pd.to_datetime(["2024-01-01T00:00Z", "2024-01-01T01:00Z"]),
        "source_class": ["terminal_tanker_stationary"] * 2,
        "source_lat": [33.7, 33.7], "source_lon": [-118.2, -118.2], "vessel_hours": [1.0, 1.0],
    })
    monitors = pd.DataFrame({"site_id": ["north"], "latitude": [33.8], "longitude": [-118.2]})
    wind = pd.DataFrame({
        "hour_utc": cells.hour_utc, "wind_dir_deg": [180.0, 0.0], "wind_speed_ms": [3.0, 3.0]
    })
    result = build_plume_exposure(cells, monitors, wind).set_index("hour_utc")
    assert result.iloc[0].terminal_tanker_stationary > result.iloc[1].terminal_tanker_stationary


def test_future_activity_uses_outcome_hour_wind():
    from analysis.atberth_pollution_intensity import build_plume_exposure

    cells = pd.DataFrame({
        "hour_utc": pd.to_datetime(["2024-01-01T06:00Z"]),
        "source_class": ["terminal_tanker_stationary"],
        "source_lat": [33.7], "source_lon": [-118.2], "vessel_hours": [1.0],
    })
    monitors = pd.DataFrame({"site_id": ["north"], "latitude": [33.8], "longitude": [-118.2]})
    wind = pd.DataFrame({
        "hour_utc": pd.to_datetime(["2024-01-01T00:00Z", "2024-01-01T06:00Z"]),
        "wind_dir_deg": [180.0, 0.0], "wind_speed_ms": [3.0, 3.0],
    })
    shifted = build_plume_exposure(cells, monitors, wind, activity_shift_hours=-6)
    assert shifted.hour_utc.iloc[0] == pd.Timestamp("2024-01-01T00:00Z")
    assert shifted.terminal_tanker_stationary.iloc[0] > 0


def test_policy_model_recovers_negative_tanker_relative_change():
    from analysis.atberth_pollution_intensity import fit_policy_model

    rng = np.random.default_rng(8)
    hours = pd.date_range("2023-01-01", "2025-03-31 23:00", freq="h", tz="UTC")
    rows = []
    for hour in hours:
        post = hour.year == 2025
        base_t, base_c = rng.lognormal(0, .5), rng.lognormal(0, .5)
        wind = rng.uniform(0, 360)
        for site, multiplier in (("a", .5), ("b", 1.0), ("c", 1.7)):
            tanker, cargo = base_t * multiplier, base_c * (2 - multiplier / 2)
            value = 10 + .8 * tanker + .3 * cargo - (.5 * tanker if post else 0) + rng.normal(0, .3)
            rows.append((site, hour, value, wind, tanker, cargo, base_t * .1))
    panel = pd.DataFrame(rows, columns=[
        "site_id", "hour_utc", "value", "wind_dir_deg", "terminal_tanker_stationary",
        "cargo_stationary", "offshore_tanker_stationary",
    ])
    result = fit_policy_model(panel, bootstrap_draws=50)
    assert result["relative_policy_effect_ppb"] < 0
    assert result["block7_ci95"][1] < 0
