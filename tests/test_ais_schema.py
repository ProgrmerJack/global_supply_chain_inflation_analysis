"""Contract tests for Phase 1's canonical national AIS ping schema."""

import os
import sys

import geopandas as gpd
import pandas as pd
from shapely.geometry import box


ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def test_normalise_pings_uses_legacy_cargo_correction_and_canonical_fields():
    """2015-style service codes must use Cargo as the effective NMEA vessel type."""

    from process_ais.extract_port_observations import CANONICAL_PING_COLUMNS, normalise_pings

    raw = pd.DataFrame(
        {
            "MMSI": [366123456],
            "BaseDateTime": ["2015-01-01T01:02:03Z"],
            "LAT": [33.75],
            "LON": [-118.20],
            "SOG": [0.4],
            "cog": [181.5],
            "VesselType": [1004],
            "Cargo": [70],
        }
    )

    accepted, rejected = normalise_pings(
        raw,
        source_file="AIS_2015_01_01.csv",
        port_complex_id="los_angeles_long_beach",
    )

    assert accepted.columns.tolist() == CANONICAL_PING_COLUMNS
    assert len(accepted) == 1
    assert accepted.loc[0, "mmsi"] == 366123456
    assert accepted.loc[0, "timestamp"] == pd.Timestamp("2015-01-01T01:02:03Z")
    assert accepted.loc[0, "cog"] == 181.5
    assert accepted.loc[0, "vessel_type"] == 70
    assert accepted.loc[0, "source_file"] == "AIS_2015_01_01.csv"
    assert accepted.loc[0, "port_complex_id"] == "los_angeles_long_beach"
    assert rejected.empty


def test_assign_state_labels_accepts_canonical_pings_and_frozen_state_zones():
    """Spatial state priority and the 0.5/3-knot boundaries remain explicit."""

    from process_ais.mode_time import assign_state_labels

    pings = pd.DataFrame(
        {
            "port_complex_id": ["alpha"] * 6,
            "lat": [0.5, 0.5, 0.5, 3.5, 3.5, 3.5],
            "lon": [0.5, 1.5, 2.5, 3.5, 3.5, 3.5],
            "sog": [0.4, 0.4, 5.0, 3.0, 0.5, None],
        }
    )
    zones = gpd.GeoDataFrame(
        {
            "port_complex_id": ["alpha", "alpha", "alpha"],
            "state": ["official_anchorage", "berth", "approach_channel"],
            "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)],
        },
        crs="EPSG:4326",
    )

    labelled = assign_state_labels(
        pings,
        zones,
        zone_priority=("official_anchorage", "berth", "approach_channel"),
    )

    assert labelled.state.tolist() == [
        "official_anchorage",
        "berth",
        "approach_channel",
        "transit",
        "manoeuvre",
        "uncharted_near_port_wait",
    ]


def test_normalise_pings_records_one_reason_for_each_invalid_row():
    """Invalid values are auditable rejections, not silently discarded rows."""

    from process_ais.extract_port_observations import normalise_pings

    raw = pd.DataFrame(
        {
            "MMSI": [366123456, 366123457, 1234, 366123459, 366123460],
            "BaseDateTime": [
                "2019-01-01T00:00:00Z",
                "not-a-timestamp",
                "2019-01-01T00:00:00Z",
                "2019-01-01T00:00:00Z",
                "2019-01-01T00:00:00Z",
            ],
            "LAT": [33.75, 33.75, 33.75, 91.0, 33.75],
            "LON": [-118.20, -118.20, -118.20, -118.20, -118.20],
            "SOG": [0.4, 0.4, 0.4, 0.4, 0.4],
            "VesselType": [70, 70, 70, 70, 60],
            "Cargo": [70, 70, 70, 70, 60],
        }
    )

    accepted, rejected = normalise_pings(
        raw,
        source_file="AIS_2019_01_01.csv",
        port_complex_id="los_angeles_long_beach",
    )

    assert accepted.mmsi.tolist() == [366123456]
    assert dict(zip(rejected.row_number, rejected.reason)) == {
        1: "invalid_timestamp",
        2: "invalid_mmsi",
        3: "coordinate_out_of_range",
        4: "unsupported_vessel_type",
    }
    assert rejected.source_file.eq("AIS_2019_01_01.csv").all()
    assert rejected.port_complex_id.eq("los_angeles_long_beach").all()


def test_normalise_pings_emits_an_integer_mmsi_identifier():
    """A numeric-looking source identifier remains an integer in the contract."""

    from process_ais.extract_port_observations import normalise_pings

    raw = pd.DataFrame(
        {
            "mmsi": [366123456.0],
            "base_datetime": ["2025-01-01T00:00:00Z"],
            "latitude": [33.75],
            "longitude": [-118.20],
            "speed": [0.4],
            "COG": [181.5],
            "vessel_type": [70],
            "cargo": [70],
        }
    )

    accepted, _ = normalise_pings(
        raw,
        source_file="ais-2025-01-01.csv.zst",
        port_complex_id="los_angeles_long_beach",
    )

    assert str(accepted.mmsi.dtype) == "Int64"
    assert accepted.cog.tolist() == [181.5]


def test_assign_pings_to_safe_port_areas_omits_unresolved_complexes_without_reassignment():
    from process_ais.extract_port_observations import assign_pings_to_safe_port_areas

    pings = pd.DataFrame(
        {
            "mmsi": pd.Series([1, 2, 3, 4], dtype="Int64"),
            "timestamp": pd.to_datetime(["2020-01-01T00:00:00Z"] * 4, utc=True),
            "lon": [0.5, 2.5, 4.5, 9.0],
            "lat": [0.5, 0.5, 0.5, 9.0],
            "sog": [0.0] * 4,
            "cog": [0.0] * 4,
            "vessel_type": [70] * 4,
            "length": [200.0] * 4,
            "width": [30.0] * 4,
            "draft": [10.0] * 4,
            "imo": pd.Series([9000001, 9000002, 9000003, 9000004], dtype="Int64"),
            "status": pd.Series([5, 1, 0, 0], dtype="Int64"),
            "source_file": ["ais.csv.zst"] * 4,
            "port_complex_id": ["__national_source__"] * 4,
        }
    )
    areas = gpd.GeoDataFrame(
        {"port_complex_id": ["alpha", "bravo", "charlie"]},
        geometry=[box(0, 0, 1, 1), box(2, 0, 3, 1), box(4, 0, 5, 1)],
        crs="EPSG:4326",
    )
    coverage = pd.DataFrame(
        {
            "port_complex_id": ["alpha", "bravo", "charlie"],
            "spatial_assignment_status": ["assignable", "assignable", "requires_finer_geometry"],
        }
    )

    assigned = assign_pings_to_safe_port_areas(pings, areas, coverage)

    assert assigned.mmsi.tolist() == [1, 2]
    assert assigned.port_complex_id.tolist() == ["alpha", "bravo"]
    assert assigned.columns.tolist() == pings.columns.tolist()
