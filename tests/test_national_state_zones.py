"""Outcome-blind construction checks for national AIS state-zone geometry."""

from __future__ import annotations

import os
import sys

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon, box


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _features(records: list[dict]) -> gpd.GeoDataFrame:
    if not records:
        return gpd.GeoDataFrame(columns=["port_complex_id", "geometry"], geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def test_dock_buffer_classification_uses_only_declared_usace_metadata():
    """The primary berth-buffer width must not depend on AIS outcomes."""

    from process_ais.national_state_zones import (
        CONTAINER_RORO_BUFFER_M,
        LIQUID_BUFFER_M,
        MISCELLANEOUS_BUFFER_M,
        dock_buffer_metres,
    )

    docks = pd.DataFrame(
        {
            "COMMODITIES": ["Containerized freight", "Fuel oil; chemical products", None],
            "PURPOSE": ["", "", "general cargo"],
            "NAV_UNIT_NAME": ["A", "B", "C"],
        }
    )

    assert dock_buffer_metres(docks).tolist() == [
        CONTAINER_RORO_BUFFER_M,
        LIQUID_BUFFER_M,
        MISCELLANEOUS_BUFFER_M,
    ]


def test_build_state_zones_is_water_side_and_mutually_exclusive():
    """Land, anchorage and channel geometry cannot silently double-label a ping."""

    from process_ais.national_state_zones import build_state_zones

    port_areas = _features([{"port_complex_id": "alpha", "geometry": box(-1, -1, 1, 1)}])
    anchors = _features(
        [{"port_complex_id": "alpha", "geometry": box(0.20, 0.20, 0.30, 0.30)}]
    )
    berth_points = _features([{"port_complex_id": "alpha", "geometry": Point(0.40, 0.0)}])
    docks = _features(
        [
            {
                "port_complex_id": "alpha",
                "COMMODITIES": "Containerized freight",
                "PURPOSE": "",
                "NAV_UNIT_NAME": "Container terminal",
                "geometry": Point(-0.05, 0.0),
            }
        ]
    )
    channels = _features([{"port_complex_id": "alpha", "geometry": box(-0.5, -0.5, 0.5, 0.5)}])
    land = _features([{"port_complex_id": "alpha", "geometry": box(-1, -1, -0.05, 1)}])

    zones = build_state_zones(
        port_areas,
        anchors=anchors,
        berth_points=berth_points,
        docks=docks,
        channels=channels,
        land=land,
        eligible_port_ids=["alpha"],
    )

    assert set(zones.state) == {"official_anchorage", "berth", "approach_channel"}
    berth = zones.loc[zones.state.eq("berth"), "geometry"].iloc[0]
    assert berth.area > 0
    assert berth.intersection(land.geometry.iloc[0]).area < 1e-12

    geometries = zones.geometry.tolist()
    for left_index, left in enumerate(geometries):
        for right in geometries[left_index + 1 :]:
            assert left.intersection(right).area < 1e-12


def test_state_zone_coverage_requires_berth_and_channel_but_not_an_anchorage():
    """Ship-channel ports remain eligible when no official anchorage is charted."""

    from process_ais.national_state_zones import assess_state_zone_coverage

    zones = _features(
        [
            {"port_complex_id": "alpha", "state": "berth", "geometry": box(0, 0, 1, 1)},
            {"port_complex_id": "alpha", "state": "approach_channel", "geometry": box(1, 0, 2, 1)},
        ]
    )

    coverage = assess_state_zone_coverage(["alpha", "bravo"], zones)

    assert coverage.set_index("port_complex_id").loc["alpha", "state_geometry_status"] == "ready"
    assert coverage.set_index("port_complex_id").loc["alpha", "official_anchorage_available"] == 0
    assert coverage.set_index("port_complex_id").loc["bravo", "state_geometry_status"] == "unavailable"


def test_build_state_zones_repairs_invalid_chart_geometry_before_overlay():
    """A malformed public chart feature must fail safe or be validly repaired before use."""

    from process_ais.national_state_zones import build_state_zones

    port_areas = _features([{"port_complex_id": "alpha", "geometry": box(-1, -1, 1, 1)}])
    empty = _features([])
    docks = _features(
        [
            {
                "port_complex_id": "alpha",
                "COMMODITIES": "general cargo",
                "PURPOSE": "",
                "NAV_UNIT_NAME": "Dock",
                "geometry": Point(0.0, 0.0),
            }
        ]
    )
    invalid_land = _features(
        [
            {
                "port_complex_id": "alpha",
                "geometry": Polygon([(-0.4, -0.4), (0.4, 0.4), (-0.4, 0.4), (0.4, -0.4)]),
            }
        ]
    )
    channels = _features([{"port_complex_id": "alpha", "geometry": box(-0.5, -0.5, 0.5, 0.5)}])

    zones = build_state_zones(
        port_areas,
        anchors=empty,
        berth_points=empty,
        docks=docks,
        channels=channels,
        land=invalid_land,
        eligible_port_ids=["alpha"],
    )

    assert zones.geometry.is_valid.all()


def test_fetch_arcgis_features_paginates_and_keeps_the_declared_port_assignment():
    """A service page boundary cannot drop geometry or detach it from its input port."""

    from process_ais.national_state_zones import fetch_arcgis_features

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    responses = [
        {
            "type": "FeatureCollection",
            "exceededTransferLimit": True,
            "features": [
                {
                    "type": "Feature",
                    "properties": {"source_id": "first"},
                    "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                }
            ],
        },
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"source_id": "second"},
                    "geometry": {"type": "Point", "coordinates": [0.1, 0.1]},
                }
            ],
        },
    ]
    seen_offsets: list[int] = []

    def get(url, *, params, timeout):
        assert url == "https://example.test/layer/query"
        assert timeout == 120
        seen_offsets.append(params["resultOffset"])
        return Response(responses.pop(0))

    port_areas = _features([{"port_complex_id": "alpha", "geometry": box(-1, -1, 1, 1)}])
    features = fetch_arcgis_features(
        "https://example.test/layer/query",
        port_areas,
        eligible_port_ids=["alpha"],
        source_layer="test_layer",
        get=get,
    )

    assert seen_offsets == [0, 1]
    assert features.port_complex_id.tolist() == ["alpha", "alpha"]
    assert features.source_layer.tolist() == ["test_layer", "test_layer"]
    assert features.source_id.tolist() == ["first", "second"]


def test_fetch_arcgis_features_accepts_an_empty_official_layer():
    """An uncharted state, such as a port with no anchorage, is not a parser failure."""

    from process_ais.national_state_zones import fetch_arcgis_features

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"type": "FeatureCollection", "features": []}

    port_areas = _features([{"port_complex_id": "alpha", "geometry": box(-1, -1, 1, 1)}])
    features = fetch_arcgis_features(
        "https://example.test/layer/query",
        port_areas,
        eligible_port_ids=["alpha"],
        source_layer="empty_layer",
        get=lambda *args, **kwargs: Response(),
    )

    assert features.empty
    assert features.crs.to_string() == "EPSG:4326"


def test_stabilise_zone_export_survives_geojson_coordinate_rounding(tmp_path):
    """A valid narrow channel polygon must remain valid after a GeoJSON round trip."""

    from process_ais.national_state_zones import stabilise_zone_export

    narrow_channel = Polygon(
        [
            (0.0, 0.0),
            (2.0, 0.0),
            (2.0, 2.0),
            (1.00000004, 2.0),
            (1.00000004, 0.5),
            (0.99999996, 0.5),
            (0.99999996, 2.0),
            (0.0, 2.0),
        ]
    )
    zones = _features(
        [{"port_complex_id": "alpha", "state": "approach_channel", "geometry": narrow_channel}]
    )

    stable = stabilise_zone_export(zones)
    output = tmp_path / "zones.geojson"
    stable.to_file(output, driver="GeoJSON")

    assert gpd.read_file(output).geometry.is_valid.all()


def test_stabilise_zone_export_reapplies_state_priority_after_snapping():
    """Independent coordinate rounding cannot reintroduce a double-labelled zone sliver."""

    from process_ais.national_state_zones import stabilise_zone_export

    zones = _features(
        [
            {"port_complex_id": "alpha", "state": "approach_channel", "geometry": box(1, 1, 3, 3)},
            {"port_complex_id": "alpha", "state": "berth", "geometry": box(0.5, 0.5, 2.5, 2.5)},
            {"port_complex_id": "alpha", "state": "official_anchorage", "geometry": box(0, 0, 2, 2)},
        ]
    )

    stable = stabilise_zone_export(zones).set_index("state")

    assert stable.loc["official_anchorage", "geometry"].intersection(
        stable.loc["berth", "geometry"]
    ).area == 0
    assert stable.loc["official_anchorage", "geometry"].intersection(
        stable.loc["approach_channel", "geometry"]
    ).area == 0
    assert stable.loc["berth", "geometry"].intersection(
        stable.loc["approach_channel", "geometry"]
    ).area == 0


def test_build_state_zones_from_frozen_source_snapshot_does_not_requery_services():
    """A corrected derived zone can be reconstructed exactly from retained source geometry."""

    from process_ais.national_state_zones import build_state_zones_from_snapshot

    port_areas = _features([{"port_complex_id": "alpha", "geometry": box(-1, -1, 1, 1)}])
    source_snapshot = _features(
        [
            {
                "port_complex_id": "alpha",
                "source_role": "navigation_facility_dock",
                "COMMODITIES": "general cargo",
                "PURPOSE": "",
                "NAV_UNIT_NAME": "Dock",
                "geometry": Point(0.0, 0.0),
            },
            {
                "port_complex_id": "alpha",
                "source_role": "maintained_channel",
                "geometry": box(-0.5, -0.5, 0.5, 0.5),
            },
        ]
    )

    zones = build_state_zones_from_snapshot(port_areas, source_snapshot, eligible_port_ids=["alpha"])

    assert set(zones.state) == {"berth", "approach_channel"}


def test_rebuild_from_snapshot_writes_valid_immutable_derived_artifacts(tmp_path):
    """A failed derived export can be corrected from frozen inputs without a second download."""

    from process_ais.national_state_zones import rebuild_national_state_zones_from_snapshot

    port_areas = _features([{"port_complex_id": "alpha", "geometry": box(-1, -1, 1, 1)}])
    source_snapshot = _features(
        [
            {
                "port_complex_id": "alpha",
                "source_role": "navigation_facility_dock",
                "COMMODITIES": "general cargo",
                "PURPOSE": "",
                "NAV_UNIT_NAME": "Dock",
                "geometry": Point(0.0, 0.0),
            },
            {
                "port_complex_id": "alpha",
                "source_role": "maintained_channel",
                "geometry": box(-0.5, -0.5, 0.5, 0.5),
            },
        ]
    )
    areas_path = tmp_path / "areas.geojson"
    source_path = tmp_path / "sources.geojson"
    assignment_path = tmp_path / "assignment.csv"
    zones_path = tmp_path / "zones.geojson"
    coverage_path = tmp_path / "coverage.csv"
    provenance_path = tmp_path / "provenance.json"
    port_areas.to_file(areas_path, driver="GeoJSON")
    source_snapshot.to_file(source_path, driver="GeoJSON")
    pd.DataFrame(
        {"port_complex_id": ["alpha"], "spatial_assignment_status": ["assignable"]}
    ).to_csv(assignment_path, index=False)

    paths = rebuild_national_state_zones_from_snapshot(
        source_path,
        port_areas_path=areas_path,
        assignment_coverage_path=assignment_path,
        zones_output_path=zones_path,
        coverage_output_path=coverage_path,
        provenance_output_path=provenance_path,
    )

    assert gpd.read_file(paths["zones"]).geometry.is_valid.all()
    assert pd.read_csv(paths["coverage"]).state_geometry_status.tolist() == ["ready"]
    with pytest.raises(FileExistsError, match="immutable state-geometry artifact"):
        rebuild_national_state_zones_from_snapshot(
            source_path,
            port_areas_path=areas_path,
            assignment_coverage_path=assignment_path,
            zones_output_path=zones_path,
            coverage_output_path=coverage_path,
            provenance_output_path=provenance_path,
        )
