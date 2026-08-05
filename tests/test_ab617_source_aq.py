from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ab617_source_aq", ROOT / "src/analysis/ab617_source_aq.py")
aq = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = aq
SPEC.loader.exec_module(aq)


def test_chart_parser_preserves_official_values_and_converts_pacific_time():
    content = b"""
    <div id="pollutantChart" data-average-values="12.5,13.0"
         data-average-date-times="1/2/2024 1:00 AM,1/2/2024 2:00 AM"
         data-average-name="1 Hour Average" data-unit-name="ppb"></div>
    """
    result = aq.parse_chart_html(
        content, site_id=5, parameter_id="7", duration_id="1", parameter_name="NO2"
    )
    assert result["value"].tolist() == [12.5, 13.0]
    assert result["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist() == [
        "2024-01-02T09:00:00Z", "2024-01-02T10:00:00Z"
    ]
    assert set(result["unit"]) == {"ppb"}


def test_chart_parser_rejects_misaligned_official_arrays():
    content = b'<div id="pollutantChart" data-average-values="1,2" data-average-date-times="1/1/2024"></div>'
    with pytest.raises(ValueError, match="unequal lengths"):
        aq.parse_chart_html(content, site_id=5, parameter_id="1", duration_id="1", parameter_name="NO2")


def test_no_data_response_is_retained_as_ineligible_declared_series():
    content = b'<div data-is-error-page="true"><h1>No Data Found!</h1></div>'
    observations = aq.parse_chart_html(
        content, site_id=6, parameter_id="36", duration_id="10", parameter_name="Ultrafine Particles"
    )
    result = aq.screen_site_series(observations)
    assert len(result) == 1
    assert result.loc[0, "observations"] == 0
    assert not bool(result.loc[0, "eligible"])


def test_effect_blind_availability_screen():
    hours = pd.date_range("2020-01-01", "2021-01-02", freq="h", tz="UTC")
    observations = pd.DataFrame({
        "site_id": 5,
        "parameter_id": "7",
        "duration_id": "1",
        "parameter_name": "Nitrogen Dioxide (NO2)",
        "average_name": "1 Hour Average",
        "unit": "ppb",
        "timestamp_utc": hours,
        "value": 10.0,
    })
    result = aq.screen_site_series(observations)
    assert len(result) == 1
    assert bool(result.loc[0, "eligible"])
    assert result.loc[0, "pollutant_family"] == "NO2"
    assert result.loc[0, "active_span_coverage"] == pytest.approx(1.0)


def test_plume_weight_uses_wind_from_receptor_back_to_source():
    panel = pd.DataFrame({
        "latitude": [33.82, 33.82],
        "longitude": [-118.20, -118.20],
        "wind_dir_deg": [180.0, 0.0],
    })
    result = aq.add_plume_weight(panel)
    assert result.loc[0, "plume_weight"] > 0
    assert result.loc[1, "plume_weight"] == pytest.approx(0.0, abs=1e-12)


def test_hourly_activity_streams_interval_caps(tmp_path):
    frame = pd.DataFrame({
        "mmsi": [1, 1, 1, 2, 2],
        "timestamp": pd.to_datetime([
            "2020-01-01T00:15:00Z", "2020-01-01T01:15:00Z", "2020-01-01T03:30:00Z",
            "2020-01-01T00:00:00Z", "2020-01-01T00:30:00Z",
        ]),
        "lon": -118.2,
        "lat": 33.72,
        "sog": [0.2, 0.2, 0.2, 3.5, 3.5],
        "cog": 0.0,
        "vessel_type": [70, 70, 70, 80, 80],
        "source_file": "synthetic.csv",
        "port_complex_id": "san_pedro_bay",
        "year": 2020,
    })
    source = tmp_path / "pings.parquet"
    frame.to_parquet(source, index=False)
    result = aq.build_hourly_activity(source, output=None, memory_limit="1GB", threads=1)
    primary = result.loc[result["stationary_sog_threshold"].eq(0.5)]
    assert primary.loc[primary["cap_hours"].eq(1), "stationary_hours"].sum() == pytest.approx(2.0)
    assert primary.loc[primary["cap_hours"].eq(2), "stationary_hours"].sum() == pytest.approx(3.0)
    assert primary.loc[primary["cap_hours"].eq(2), "moving_hours"].sum() == pytest.approx(0.5)


def test_two_way_fe_estimator_recovers_source_slope():
    rng = np.random.default_rng(4)
    hours = pd.date_range("2022-01-01", periods=240, freq="h", tz="UTC")
    rows = []
    weights = {5: 0.1, 6: 0.3, 8: 0.6, 9: 0.9}
    activity = rng.normal(size=len(hours))
    hour_shock = rng.normal(scale=2, size=len(hours))
    for site, weight in weights.items():
        site_effect = site / 10
        for index, hour in enumerate(hours):
            exposure = activity[index] * weight
            outcome = 0.7 * exposure + site_effect + hour_shock[index] + rng.normal(scale=0.03)
            rows.append({"site_id": site, "hour_utc": hour, "outcome": outcome, "exposure": exposure})
    result = aq.fit_source_model(pd.DataFrame(rows))
    assert result.beta == pytest.approx(0.7, abs=0.03)
    assert result.sites == 4
    assert result.observations == 960


def test_holm_adjustment_is_order_preserving_and_bounded():
    assert aq.holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
