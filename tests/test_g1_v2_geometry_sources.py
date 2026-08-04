"""Provenance contracts for outcome-free G1-v2 geometry-source preparation."""

import hashlib
import json
import os
import sys

import geopandas as gpd
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def test_cache_immutable_source_document_records_the_exact_download(tmp_path):
    """Static source documentation must be cached once with byte-level provenance."""

    from process_ais.source_manifest import cache_immutable_source_document

    class Response:
        content = b"official geometry documentation\n"

        def raise_for_status(self):
            return None

    destination = tmp_path / "terminal-map.pdf"
    record = cache_immutable_source_document(
        destination,
        source_url="https://example.test/terminal-map.pdf",
        retrieved_at="2026-07-15T12:00:00Z",
        parser_version="g1-v2-geometry-source-cache-v1",
        port_complex_id="savannah_ga",
        get=lambda *args, **kwargs: Response(),
    )

    assert destination.read_bytes() == Response.content
    assert record["source_file"] == "terminal-map.pdf"
    assert record["source_url"] == "https://example.test/terminal-map.pdf"
    assert record["sha256"] == hashlib.sha256(Response.content).hexdigest()
    assert record["raw_row_count"] == 0
    assert record["accepted_row_count"] == 0
    assert record["rejection_counts"] == "{}"


def test_terminal_evidence_registry_stays_outcome_free_and_uses_only_frozen_dock_points():
    """Draft terminal evidence cannot be silently promoted to a final AIS boundary."""

    root = os.path.join(os.path.dirname(__file__), "..")
    registry = pd.read_csv(os.path.join(root, "config", "registries", "g1_v2_terminal_evidence_registry_draft.csv"), dtype=str)
    sources = gpd.read_file(os.path.join(root, "config", "geometry", "national_state_zone_sources.geojson"))

    required = {
        "registry_version",
        "registry_status",
        "gateway_id",
        "candidate_key",
        "candidate_feature_ids",
        "feature_geometry_type",
        "boundary_status",
        "official_terminal_source_url",
        "official_source_access_status",
        "outcome_data_retrieval_status",
    }
    assert required <= set(registry.columns)
    assert registry.gateway_id.tolist() == [
        "san_pedro_bay",
        "san_pedro_bay",
        "savannah_ga",
        "charleston_sc",
        "houston_tx",
    ]
    assert registry.registry_status.eq("draft_not_frozen").all()
    assert registry.feature_geometry_type.eq("Point").all()
    assert registry.boundary_status.eq("not_a_terminal_boundary").all()
    assert registry.outcome_data_retrieval_status.eq("no outcome values retrieved").all()
    assert registry.official_terminal_source_url.str.startswith("https://").all()
    assert set(registry.official_source_access_status) == {
        "public_document_verified",
        "public_endpoint_access_blocked",
    }
    assert not registry.candidate_key.duplicated().any()

    frozen_docks = sources.loc[
        sources.source_role.eq("navigation_facility_dock")
        & sources.source_layer.eq("usace_navigation_facilities")
    ]
    available = set(frozen_docks.NAV_UNIT_ID.astype(str))
    for ids in registry.candidate_feature_ids:
        selected = ids.split(";")
        assert selected == sorted(set(selected))
        assert set(selected) <= available


def test_declared_geometry_sources_resume_from_sidecar_provenance(tmp_path):
    """A restarted cache run must reuse only a byte-verified prior document."""

    from process_ais.g1_v2_geometry_sources import cache_declared_geometry_sources

    registry_path = tmp_path / "sources.csv"
    registry_path.write_text(
        "document_id,gateway_id,source_file,source_url,cache_action\n"
        "garden_city_map,savannah_ga,garden-city-map.pdf,https://example.test/garden-city-map.pdf,cache_now\n",
        encoding="utf-8",
    )
    calls = []

    class Response:
        content = b"official Garden City map\n"

        def raise_for_status(self):
            return None

    def get(url, *, timeout):
        calls.append((url, timeout))
        return Response()

    first = cache_declared_geometry_sources(
        registry_path,
        tmp_path / "cache",
        retrieved_at="2026-07-15T12:00:00Z",
        get=get,
    )
    second = cache_declared_geometry_sources(
        registry_path,
        tmp_path / "cache",
        retrieved_at="2026-07-15T13:00:00Z",
        get=get,
    )

    assert calls == [("https://example.test/garden-city-map.pdf", 120)]
    assert first.to_dict("records") == second.to_dict("records")
    assert (tmp_path / "cache" / "garden-city-map.pdf.manifest.json").is_file()
    assert (tmp_path / "cache" / "source_manifest.csv").is_file()


def test_authorized_geometry_document_appends_without_rewriting_prior_provenance(tmp_path):
    """An authorized file may extend, but never alter, the declared source manifest."""

    from process_ais.g1_v2_geometry_sources import (
        cache_authorized_geometry_documents,
        cache_declared_geometry_sources,
    )

    registry_path = tmp_path / "sources.csv"
    registry_path.write_text(
        "document_id,gateway_id,source_file,source_url,cache_action\n"
        "public_map,savannah_ga,public-map.pdf,https://example.test/public-map.pdf,cache_now\n"
        "authorized_map,charleston_sc,authorized-map.pdf,https://example.test/authorized-map.pdf,external_access_required\n",
        encoding="utf-8",
    )
    calls = []

    class Response:
        content = b"public map\n"

        def raise_for_status(self):
            return None

    def get(url, *, timeout):
        calls.append((url, timeout))
        return Response()

    cache_dir = tmp_path / "cache"
    cache_declared_geometry_sources(
        registry_path,
        cache_dir,
        retrieved_at="2026-07-15T12:00:00Z",
        get=get,
    )
    delivered = tmp_path / "authority-supplied-map.pdf"
    delivered.write_bytes(b"authorized map\n")

    manifest = cache_authorized_geometry_documents(
        registry_path,
        cache_dir,
        authorized_documents={"authorized_map": delivered},
        retrieved_at="2026-07-16T12:00:00Z",
    )

    assert calls == [("https://example.test/public-map.pdf", 120)]
    assert manifest.source_file.tolist() == ["authorized-map.pdf", "public-map.pdf"]
    assert (cache_dir / "authorized-map.pdf").read_bytes() == delivered.read_bytes()
    sidecar = json.loads((cache_dir / "authorized-map.pdf.manifest.json").read_text(encoding="utf-8"))
    assert sidecar["delivery_method"] == "authorized_external_file"
    assert sidecar["delivered_file_name"] == "authority-supplied-map.pdf"

    resumed = cache_declared_geometry_sources(
        registry_path,
        cache_dir,
        retrieved_at="2026-07-16T13:00:00Z",
        get=get,
    )
    assert resumed.to_dict("records") == manifest.to_dict("records")


def test_geometry_source_registry_caches_only_verified_public_documents():
    """An access-blocked source must be declared but never retried as a silent fallback."""

    root = os.path.join(os.path.dirname(__file__), "..")
    sources = pd.read_csv(os.path.join(root, "config", "registries", "g1_v2_geometry_source_registry_draft.csv"), dtype=str)

    assert sources.document_id.tolist() == [
        "gpa_garden_city_terminal_guide_2020",
        "polb_public_terminal_map",
        "pola_container_terminal_map_2025",
        "port_houston_interactive_terminal_map_2023",
        "scspa_hugh_leatherman_terminal_map",
        "scspa_north_charleston_terminal_map",
        "scspa_wando_welch_terminal_map",
    ]
    assert sources.source_url.str.startswith("https://").all()
    assert sources.source_file.map(lambda value: os.path.basename(value) == value).all()
    external_access = {
        "polb_public_terminal_map",
        "scspa_hugh_leatherman_terminal_map",
        "scspa_north_charleston_terminal_map",
        "scspa_wando_welch_terminal_map",
    }
    assert set(sources.loc[sources.cache_action.eq("external_access_required"), "document_id"]) == external_access
    assert sources.loc[~sources.document_id.isin(external_access), "cache_action"].eq("cache_now").all()
