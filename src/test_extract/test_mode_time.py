import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.process_ais.mode_time import (  # noqa: E402
    aggregate_monthly_mode_time,
    assign_mode_labels,
    compute_mode_intervals,
    load_mode_zones,
)


def _zones():
    return gpd.GeoDataFrame(
        {
            "Port": ["LA_Long_Beach", "LA_Long_Beach"],
            "zone_type": ["anchor", "berth"],
        },
        geometry=[
            Polygon([(-118.30, 33.70), (-118.25, 33.70), (-118.25, 33.75), (-118.30, 33.75)]),
            Polygon([(-118.22, 33.72), (-118.18, 33.72), (-118.18, 33.76), (-118.22, 33.76)]),
        ],
        crs="EPSG:4326",
    )


def test_assign_mode_labels_uses_polygon_and_speed_precedence():
    obs = pd.DataFrame(
        {
            "MMSI": [1, 2, 3, 4, 5],
            "BaseDateTime": pd.to_datetime(["2021-01-01 00:00:00"] * 5),
            "LAT": [33.73, 33.74, 33.73, 33.73, 33.90],
            "LON": [-118.27, -118.20, -118.27, -118.27, -118.20],
            "SOG": [0.0, 0.0, 1.5, 5.0, 0.0],
            "Port": ["LA_Long_Beach"] * 5,
        }
    )
    out = assign_mode_labels(obs, _zones())
    assert out["mode"].tolist() == ["anchor", "berth", "manoeuvre", "transit", "unknown_hoteling"]


def test_compute_mode_intervals_caps_gaps_and_aggregates_monthly():
    obs = pd.DataFrame(
        {
            "MMSI": [1, 1, 1, 1],
            "Port": ["LA_Long_Beach"] * 4,
            "BaseDateTime": pd.to_datetime(
                ["2021-01-01 00:00:00", "2021-01-01 01:00:00", "2021-01-01 06:00:00", "2021-01-01 07:00:00"]
            ),
            "mode": ["anchor", "anchor", "berth", "berth"],
            "VesselCategory": ["Cargo"] * 4,
            "VesselType": [70] * 4,
            "Length": [300.0] * 4,
            "Width": [40.0] * 4,
        }
    )
    intervals = compute_mode_intervals(obs, gap_cap_hours=2.0)
    monthly = aggregate_monthly_mode_time(intervals)
    row = monthly.iloc[0]
    assert row["anchor_hours"] == 3.0
    assert row["berth_hours"] == 1.0
    assert row["total_mode_hours"] == 4.0


def test_repository_mode_zone_file_loads():
    zones = load_mode_zones("config/port_mode_zones.geojson")
    assert set(zones["Port"]) == {"LA_Long_Beach", "NY_NJ", "Houston", "Savannah", "Seattle"}
    assert set(zones["zone_type"]) == {"anchor", "berth"}
    assert len(zones) == 10
