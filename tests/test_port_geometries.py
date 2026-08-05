"""Tests for outcome-blind national port-area construction."""

from pathlib import Path
import sys

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_geometry_sources_require_every_included_complex_to_be_declared(tmp_path):
    from process_ais.port_geometries import load_port_geometry_sources

    source_path = tmp_path / "port_area_sources.csv"
    source_path.write_text(
        "port_complex_id,status,usace_port_ids,exclusion_reason\n"
        "san_pedro_bay,available,4120;4110,\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing source records: seattle_wa"):
        load_port_geometry_sources(source_path, ["san_pedro_bay", "seattle_wa"])


def test_geometry_sources_require_a_reason_for_an_unavailable_complex(tmp_path):
    from process_ais.port_geometries import load_port_geometry_sources

    source_path = tmp_path / "port_area_sources.csv"
    source_path.write_text(
        "port_complex_id,status,usace_port_ids,exclusion_reason\n"
        "chester_pa,unavailable,,\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires exclusion_reason"):
        load_port_geometry_sources(source_path, ["chester_pa"])


def test_derive_port_geometries_dissolves_declared_component_port_areas():
    from process_ais.port_geometries import derive_port_geometries

    sources = pd.DataFrame(
        {
            "port_complex_id": ["san_pedro_bay"],
            "status": ["available"],
            "usace_port_ids": ["4120;4110"],
            "exclusion_reason": [""],
        }
    )
    features = gpd.GeoDataFrame(
        {
            "PORTIDPK": ["4120", "4110"],
            "FEATURENAME": ["Los Angeles", "Long Beach"],
            "DATA_YEAR": [2020, 2021],
        },
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs="EPSG:4326",
    )

    areas = derive_port_geometries(sources, features)

    assert areas.port_complex_id.tolist() == ["san_pedro_bay"]
    assert areas.source_port_ids.tolist() == ["4110;4120"]
    assert areas.source_data_years.tolist() == ["2020;2021"]
    assert areas.geometry.iloc[0].area == 2.0


def test_derive_port_geometries_rejects_an_absent_declared_source_id():
    from process_ais.port_geometries import derive_port_geometries

    sources = pd.DataFrame(
        {
            "port_complex_id": ["san_pedro_bay"],
            "status": ["available"],
            "usace_port_ids": ["4120;4110"],
            "exclusion_reason": [""],
        }
    )
    features = gpd.GeoDataFrame(
        {"PORTIDPK": ["4120"], "FEATURENAME": ["Los Angeles"], "DATA_YEAR": [2020]},
        geometry=[box(0, 0, 1, 1)],
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="missing declared USACE port IDs: 4110"):
        derive_port_geometries(sources, features)


def test_fetch_usace_port_features_requests_geojson_for_declared_ids():
    from process_ais.port_geometries import fetch_usace_port_features

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"PORTIDPK": "4120", "FEATURENAME": "Los Angeles"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                        },
                    }
                ],
            }

    def get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return Response()

    features = fetch_usace_port_features(["4120"], get=get)

    assert features.PORTIDPK.tolist() == ["4120"]
    assert calls[0][1]["f"] == "geojson"
    assert calls[0][1]["where"] == "PORTIDPK IN ('4120')"


def test_frozen_usace_source_registry_covers_the_selected_port_universe():
    from process_ais.port_geometries import load_port_geometry_sources

    registry = pd.read_csv(ROOT / "data/processed/port_registry.csv")
    included = registry.loc[registry.inclusion_status.eq("included"), "port_complex_id"].tolist()

    sources = load_port_geometry_sources(
        ROOT / "config/registries/port_area_sources.csv",
        included,
    )

    assert sources.status.value_counts().to_dict() == {"available": 19, "unavailable": 1}
    assert sources.loc[sources.status.eq("unavailable"), "port_complex_id"].tolist() == ["chester_pa"]


def test_build_port_areas_writes_an_immutable_provenance_bound_geojson(tmp_path):
    from process_ais.port_geometries import build_port_areas

    registry_path = tmp_path / "port_registry.csv"
    registry_path.write_text(
        "port_complex_id,inclusion_status\n"
        "san_pedro_bay,included\n"
        "chester_pa,included\n",
        encoding="utf-8",
    )
    source_path = tmp_path / "port_area_sources.csv"
    source_path.write_text(
        "port_complex_id,status,usace_port_ids,exclusion_reason\n"
        "san_pedro_bay,available,4120,\n"
        "chester_pa,unavailable,,no matching port polygon\n",
        encoding="utf-8",
    )
    features = gpd.GeoDataFrame(
        {"PORTIDPK": ["4120"], "DATA_YEAR": [2020]},
        geometry=[box(0, 0, 1, 1)],
        crs="EPSG:4326",
    )
    output_path = tmp_path / "port_areas_usace.geojson"

    areas = build_port_areas(
        registry_path,
        source_path,
        output_path,
        retrieved_at_utc="2026-07-13T13:00:00Z",
        fetcher=lambda _: features,
    )

    assert areas.port_complex_id.tolist() == ["san_pedro_bay"]
    saved = gpd.read_file(output_path)
    assert saved.retrieved_at_utc.iloc[0].isoformat() == "2026-07-13T13:00:00+00:00"
    with pytest.raises(FileExistsError):
        build_port_areas(
            registry_path,
            source_path,
            output_path,
            retrieved_at_utc="2026-07-13T13:00:00Z",
            fetcher=lambda _: features,
        )


def test_port_area_assignment_coverage_marks_overlaps_and_preserves_an_immutable_audit(tmp_path):
    from process_ais.port_geometries import (
        assess_port_area_assignment,
        write_port_area_assignment_coverage,
    )

    sources = pd.DataFrame(
        {
            "port_complex_id": ["alpha", "bravo", "charlie", "delta"],
            "status": ["available", "available", "unavailable", "available"],
        }
    )
    areas = gpd.GeoDataFrame(
        {"port_complex_id": ["alpha", "bravo", "delta"]},
        geometry=[box(0, 0, 2, 2), box(1, 1, 3, 3), box(10, 10, 11, 11)],
        crs="EPSG:4326",
    )

    coverage = assess_port_area_assignment(sources, areas)

    assert coverage.set_index("port_complex_id").loc["alpha"].to_dict() == {
        "port_area_status": "available",
        "spatial_assignment_status": "requires_finer_geometry",
        "conflicting_port_complex_ids": "bravo",
    }
    assert coverage.set_index("port_complex_id").loc["charlie"].to_dict() == {
        "port_area_status": "unavailable",
        "spatial_assignment_status": "unavailable",
        "conflicting_port_complex_ids": "",
    }
    assert coverage.set_index("port_complex_id").loc["delta"].to_dict() == {
        "port_area_status": "available",
        "spatial_assignment_status": "assignable",
        "conflicting_port_complex_ids": "",
    }

    audit_path = tmp_path / "port_area_assignment_coverage.csv"
    write_port_area_assignment_coverage(coverage, audit_path)
    assert pd.read_csv(audit_path, keep_default_na=False).equals(coverage)
    with pytest.raises(FileExistsError):
        write_port_area_assignment_coverage(coverage, audit_path)


def test_partitioned_coastal_domains_preserve_cores_without_buffer_overlap():
    from process_ais.port_geometries import derive_partitioned_coastal_domains

    areas = gpd.GeoDataFrame(
        {"port_complex_id": ["alpha", "bravo"]},
        geometry=[box(0, 0, 1_000, 1_000), box(2_000, 0, 3_000, 1_000)],
        crs="EPSG:5070",
    )

    domains = derive_partitioned_coastal_domains(
        areas,
        inner_buffer_m=2_000,
        outer_buffer_m=4_000,
    ).to_crs("EPSG:5070")
    inner = domains.loc[domains.domain.eq("coastal_inner")].set_index("port_complex_id")
    outer = domains.loc[domains.domain.eq("coastal_outer")].set_index("port_complex_id")

    for row in areas.itertuples(index=False):
        assert inner.loc[row.port_complex_id].geometry.covers(row.geometry)
        assert outer.loc[row.port_complex_id].geometry.covers(
            inner.loc[row.port_complex_id].geometry
        )
    assert inner.loc["alpha"].geometry.intersection(inner.loc["bravo"].geometry).area == 0
    assert outer.loc["alpha"].geometry.intersection(outer.loc["bravo"].geometry).area == 0


def test_partitioned_coastal_domains_reject_source_area_overlap():
    from process_ais.port_geometries import derive_partitioned_coastal_domains

    areas = gpd.GeoDataFrame(
        {"port_complex_id": ["alpha", "bravo"]},
        geometry=[box(0, 0, 2, 2), box(1, 1, 3, 3)],
        crs="EPSG:5070",
    )

    with pytest.raises(ValueError, match="source port areas overlap"):
        derive_partitioned_coastal_domains(
            areas,
            inner_buffer_m=2_000,
            outer_buffer_m=4_000,
        )


def test_partitioned_coastal_domain_writer_is_immutable(tmp_path):
    from process_ais.port_geometries import (
        derive_partitioned_coastal_domains,
        write_partitioned_coastal_domains,
    )

    areas = gpd.GeoDataFrame(
        {"port_complex_id": ["alpha"]},
        geometry=[box(0, 0, 1_000, 1_000)],
        crs="EPSG:5070",
    )
    domains = derive_partitioned_coastal_domains(
        areas,
        inner_buffer_m=2_000,
        outer_buffer_m=4_000,
    )
    output = tmp_path / "coastal.geojson"

    write_partitioned_coastal_domains(domains, output)

    assert len(gpd.read_file(output)) == 2
    with pytest.raises(FileExistsError):
        write_partitioned_coastal_domains(domains, output)
