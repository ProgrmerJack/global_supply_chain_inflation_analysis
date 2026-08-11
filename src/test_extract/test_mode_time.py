import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.process_ais.mode_time import (  # noqa: E402
    aggregate_monthly_mode_time,
    assign_mode_labels,
    assign_state_labels,
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


def test_compute_mode_intervals_splits_months_without_linking_different_ports():
    """A capped interval conserves hours across a month seam and never spans ports."""
    obs = pd.DataFrame(
        {
            "MMSI": [1, 1, 2, 2],
            "Port": ["A", "A", "B", "C"],
            "BaseDateTime": pd.to_datetime(
                ["2021-01-31 23:00:00", "2021-02-01 01:00:00", "2021-01-31 23:30:00", "2021-02-01 00:30:00"]
            ),
            "mode": ["anchor", "anchor", "berth", "berth"],
        }
    )

    intervals = compute_mode_intervals(obs, gap_cap_hours=2.0)

    assert intervals.loc[intervals["Port"] == "A", ["YearMonth", "interval_hours"]].values.tolist() == [
        ["2021-01", 1.0],
        ["2021-02", 1.0],
    ]
    assert set(intervals["Port"]) == {"A"}


def test_assign_state_labels_resolves_overlap_and_speed_thresholds():
    """Zone priority is explicit while 0.5/1.0/3.0-knot boundaries stay testable."""
    zones = gpd.GeoDataFrame(
        {"Port": ["A", "A"], "zone_type": ["official_anchorage", "berth"]},
        geometry=[
            Polygon([(-118.30, 33.70), (-118.20, 33.70), (-118.20, 33.80), (-118.30, 33.80)]),
            Polygon([(-118.28, 33.72), (-118.18, 33.72), (-118.18, 33.78), (-118.28, 33.78)]),
        ],
        crs="EPSG:4326",
    )
    obs = pd.DataFrame(
        {
            "Port": ["A"] * 4,
            "LAT": [33.75] * 4,
            "LON": [-118.25] * 4,
            "SOG": [0.0, 0.5, 1.0, 3.0],
        }
    )

    development = assign_state_labels(
        obs,
        zones,
        zone_priority=("berth", "official_anchorage"),
    )
    epa_sensitivity = assign_state_labels(
        obs,
        zones,
        zone_priority=("berth", "official_anchorage"),
        transit_knots=1.0,
    )

    assert development["state"].tolist() == ["berth", "manoeuvre", "manoeuvre", "transit"]
    assert epa_sensitivity["state"].tolist() == ["berth", "manoeuvre", "transit", "transit"]


def test_assign_state_labels_never_uses_an_overlapping_zone_from_another_port():
    """Spatial overlap cannot override the declared port-complex identity."""
    geometry = Polygon([(-118.30, 33.70), (-118.20, 33.70), (-118.20, 33.80), (-118.30, 33.80)])
    zones = gpd.GeoDataFrame(
        {"Port": ["A", "B"], "zone_type": ["official_anchorage", "berth"]},
        geometry=[geometry, geometry],
        crs="EPSG:4326",
    )
    obs = pd.DataFrame({"Port": ["A"], "LAT": [33.75], "LON": [-118.25], "SOG": [0.0]})

    states = assign_state_labels(obs, zones, zone_priority=("berth", "official_anchorage"))

    assert states.state.tolist() == ["official_anchorage"]


def test_repository_mode_zone_file_loads():
    zones = load_mode_zones("config/geometry/port_mode_zones.geojson")
    ports = {"LA_Long_Beach", "NY_NJ", "Houston", "Savannah", "Seattle"}
    assert set(zones["Port"]) == ports
    assert set(zones["zone_type"]) == {"anchor", "berth"}
    assert set(zones.loc[zones["zone_type"] == "berth", "Port"]) == ports
    assert set(zones.loc[zones["zone_type"] == "anchor", "Port"]) == ports - {"Houston"}
    assert len(zones) == 9
