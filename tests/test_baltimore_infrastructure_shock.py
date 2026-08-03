"""One compact synthetic check for the frozen Baltimore design helpers."""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiPoint

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analysis.baltimore_infrastructure_shock import (  # noqa: E402
    PROJECTED_CRS,
    inland_side_from_berths,
    load_bridge,
    load_design,
    presence_intervals,
    randomization_p,
    receiver_weights,
    track_crossings,
    triple_difference,
)


def test_frozen_baltimore_design_and_measurement_helpers():
    design = load_design()
    bridge = load_bridge(design)
    (x1, y1), (x2, y2) = bridge.coords[0], bridge.coords[-1]
    midpoint = bridge.interpolate(0.5, normalized=True)
    length = np.hypot(x2 - x1, y2 - y1)
    nx, ny = -(y2 - y1) / length, (x2 - x1) / length
    points = MultiPoint(
        [
            (midpoint.x + 500 * nx, midpoint.y + 500 * ny),
            (midpoint.x + 600 * nx, midpoint.y + 600 * ny),
            (midpoint.x - 500 * nx, midpoint.y - 500 * ny),
        ]
    )
    inland = inland_side_from_berths(bridge, points)
    endpoints = gpd.GeoSeries(
        [points.geoms[0], points.geoms[2]], crs=PROJECTED_CRS
    ).to_crs("EPSG:4326")
    pings = pd.DataFrame(
        {
            "mmsi": [1, 1],
            "timestamp": ["2024-01-01T00:00:00Z", "2024-01-01T00:20:00Z"],
            "lon": [point.x for point in endpoints],
            "lat": [point.y for point in endpoints],
        }
    )
    crossings = track_crossings(pings, bridge, inland)
    assert len(crossings) == 1
    assert crossings.direction.iloc[0] in {"inbound", "outbound"}

    intervals = presence_intervals(
        pd.DataFrame(
            {
                "mmsi": [1, 1, 1],
                "port_complex_id": ["p", "p", "p"],
                "timestamp": ["2024-01-01T00:00Z", "2024-01-01T00:10Z", "2024-01-01T02:00Z"],
            }
        )
    )
    assert intervals.presence_hours.tolist() == pytest.approx([1 / 6, 1 / 2])

    episodes = pd.DataFrame(
        {
            "mmsi": np.repeat(np.arange(10), 2),
            "port_complex_id": [value for _ in range(10) for value in ["baltimore_md", "receiver"]],
            "start": pd.date_range("2023-01-01", periods=20, freq="D", tz="UTC"),
        }
    )
    weights = receiver_weights(episodes, ["receiver"])
    assert weights.to_dict("records") == [{"port_complex_id": "receiver", "transitions": 10, "weight": 1.0}]

    rows = []
    for year, event_effect in [(2023, 0), (2024, 4)]:
        for linked in [False, True]:
            for post in [False, True]:
                value = 10 + (event_effect if linked and post else 0)
                rows.append([year, "receiver", linked, post, value, 100])
    panel = pd.DataFrame(rows, columns=["year", "port_complex_id", "linked", "post", "value", "fleet_size"])
    assert triple_difference(panel, weights, event_year=2024, design_years=[2023]) == pytest.approx(4)
    assert randomization_p(2, np.array([0, 1, 2])) == pytest.approx(0.5)
