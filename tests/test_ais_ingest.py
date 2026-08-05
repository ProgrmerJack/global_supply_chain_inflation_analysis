"""Ingestion-contract tests for the national AIS extension."""

import os
import sys
import hashlib

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box


ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def test_deduplicate_pings_keeps_a_deterministic_source_record():
    """Exact repeated pings must not depend on chunk or source-file order."""

    from process_ais.extract_port_observations import deduplicate_pings

    pings = pd.DataFrame(
        {
            "mmsi": pd.Series([366123456, 366123456, 366123457], dtype="Int64"),
            "timestamp": pd.to_datetime(
                ["2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z"],
                utc=True,
            ),
            "lon": [-118.20, -118.20, -118.19],
            "lat": [33.75, 33.75, 33.76],
            "sog": [0.4, 0.4, 0.5],
            "cog": [180.0, 180.0, 181.0],
            "vessel_type": [70, 70, 70],
            "source_file": ["ais-b.csv", "ais-a.csv", "ais-c.csv"],
            "port_complex_id": ["san_pedro_bay"] * 3,
        }
    )

    deduplicated = deduplicate_pings(pings)

    assert deduplicated.source_file.tolist() == ["ais-a.csv", "ais-c.csv"]


def test_source_manifest_record_captures_file_and_parse_provenance(tmp_path):
    """A discarded raw file still leaves enough evidence to reproduce its parse."""

    from process_ais.source_manifest import build_file_manifest_record

    raw_path = tmp_path / "ais-2020-01-01.csv.zst"
    raw_bytes = b"raw fixture bytes\n"
    raw_path.write_bytes(raw_bytes)
    accepted = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z"], utc=True
            )
        }
    )
    rejected = pd.DataFrame({"reason": ["invalid_timestamp", "invalid_timestamp", "invalid_mmsi"]})

    record = build_file_manifest_record(
        raw_path,
        source_url="https://example.test/ais-2020-01-01.csv.zst",
        retrieved_at="2026-07-13T12:00:00Z",
        raw_row_count=5,
        accepted=accepted,
        rejected=rejected,
        parser_version="national-ais-v1",
        port_complex_id="san_pedro_bay",
    )

    assert record["sha256"] == hashlib.sha256(raw_bytes).hexdigest()
    assert record["file_size_bytes"] == len(raw_bytes)
    assert record["raw_row_count"] == 5
    assert record["accepted_row_count"] == 2
    assert record["rejected_row_count"] == 3
    assert record["rejection_counts"] == '{"invalid_mmsi":1,"invalid_timestamp":2}'
    assert record["first_timestamp"] == "2020-01-01T00:00:00+00:00"
    assert record["last_timestamp"] == "2020-01-01T01:00:00+00:00"


def test_source_manifest_count_record_preserves_disk_light_parse_accounting(tmp_path):
    from process_ais.source_manifest import build_file_manifest_record_from_counts

    raw_path = tmp_path / "ais-2020-01-01.csv.zst"
    raw_path.write_bytes(b"raw fixture bytes\n")

    record = build_file_manifest_record_from_counts(
        raw_path,
        source_url="https://example.test/ais-2020-01-01.csv.zst",
        retrieved_at="2026-07-13T12:00:00Z",
        raw_row_count=5,
        accepted_row_count=2,
        rejected_row_count=3,
        rejection_counts={"invalid_timestamp": 2, "invalid_mmsi": 1},
        first_timestamp="2020-01-01T00:00:00Z",
        last_timestamp="2020-01-01T01:00:00Z",
        parser_version="national-ais-v1",
        port_complex_id="__national_source__",
    )

    assert record["raw_row_count"] == 5
    assert record["accepted_row_count"] == 2
    assert record["rejected_row_count"] == 3
    assert record["rejection_counts"] == '{"invalid_mmsi":1,"invalid_timestamp":2}'
    assert record["first_timestamp"] == "2020-01-01T00:00:00+00:00"
    assert record["last_timestamp"] == "2020-01-01T01:00:00+00:00"


def test_file_manifest_order_is_stable_across_record_order(tmp_path):
    """The manifest has one reproducible row order regardless of worker completion order."""

    from process_ais.source_manifest import build_file_manifest_record, normalise_file_manifest

    accepted = pd.DataFrame({"timestamp": pd.to_datetime(["2020-01-01T00:00:00Z"], utc=True)})
    rejected = pd.DataFrame({"reason": pd.Series(dtype="string")})
    first_path = tmp_path / "ais-b.csv"
    second_path = tmp_path / "ais-a.csv"
    first_path.write_bytes(b"b")
    second_path.write_bytes(b"a")
    common = {
        "source_url": "https://example.test/",
        "retrieved_at": "2026-07-13T12:00:00Z",
        "raw_row_count": 1,
        "accepted": accepted,
        "rejected": rejected,
        "parser_version": "national-ais-v1",
        "port_complex_id": "san_pedro_bay",
    }

    manifest = normalise_file_manifest(
        [build_file_manifest_record(first_path, **common), build_file_manifest_record(second_path, **common)]
    )

    assert manifest.source_file.tolist() == ["ais-a.csv", "ais-b.csv"]


def test_compute_state_intervals_assigns_each_split_interval_one_state():
    """The canonical state contract reuses interval conservation without mode aliases."""

    from process_ais.mode_time import compute_state_intervals

    pings = pd.DataFrame(
        {
            "mmsi": pd.Series([366123456, 366123456], dtype="Int64"),
            "timestamp": pd.to_datetime(["2021-01-31T23:00:00Z", "2021-02-01T01:00:00Z"], utc=True),
            "port_complex_id": ["san_pedro_bay", "san_pedro_bay"],
            "state": ["official_anchorage", "official_anchorage"],
        }
    )

    intervals = compute_state_intervals(pings, gap_cap_hours=2.0)

    assert intervals[["year_month", "state", "interval_hours"]].values.tolist() == [
        ["2021-01", "official_anchorage", 1.0],
        ["2021-02", "official_anchorage", 1.0],
    ]


def test_aggregate_state_month_excludes_months_without_required_coverage():
    """A state panel cannot turn an incomplete source month into a zero-valued result."""

    from process_ais.mode_time import aggregate_state_month

    intervals = pd.DataFrame(
        {
            "mmsi": pd.Series([1, 1, 2], dtype="Int64"),
            "port_complex_id": ["san_pedro_bay"] * 3,
            "year_month": ["2021-01", "2021-02", "2021-02"],
            "state": ["berth", "berth", "transit"],
            "interval_hours": [3.0, 2.0, 1.0],
        }
    )
    coverage = pd.DataFrame(
        {
            "port_complex_id": ["san_pedro_bay", "san_pedro_bay"],
            "year_month": ["2021-01", "2021-02"],
            "coverage_ok": [False, True],
            "source_file_count": [1, 2],
        }
    )

    panel = aggregate_state_month(intervals, coverage)

    assert panel.year_month.tolist() == ["2021-02"]
    assert panel.loc[0, "berth_hours"] == 2.0
    assert panel.loc[0, "transit_hours"] == 1.0
    assert panel.loc[0, "total_interval_hours"] == 3.0
    assert panel.loc[0, "source_file_count"] == 2


def test_assign_port_call_ids_uses_the_registered_gap_and_port_boundary():
    """A 24-hour absence stays in one call; a longer one starts a new port-specific call."""

    from process_ais.port_call_segmentation import assign_port_call_ids

    pings = pd.DataFrame(
        {
            "mmsi": pd.Series([366123456] * 4, dtype="Int64"),
            "port_complex_id": ["san_pedro_bay", "san_pedro_bay", "san_pedro_bay", "new_york_new_jersey"],
            "timestamp": pd.to_datetime(
                ["2021-01-03T01:00:00Z", "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z", "2021-01-01T00:00:00Z"],
                utc=True,
            ),
        }
    )

    calls = assign_port_call_ids(pings)

    san_pedro = calls.loc[calls.port_complex_id == "san_pedro_bay", "call_id"].tolist()
    assert san_pedro == ["san_pedro_bay|366123456|1", "san_pedro_bay|366123456|1", "san_pedro_bay|366123456|2"]
    assert calls.loc[calls.port_complex_id == "new_york_new_jersey", "call_id"].tolist() == [
        "new_york_new_jersey|366123456|1"
    ]


def test_compute_state_intervals_does_not_bridge_distinct_port_calls():
    """The gap cap is not a substitute for a registered port-call boundary."""

    from process_ais.mode_time import compute_state_intervals

    pings = pd.DataFrame(
        {
            "mmsi": pd.Series([366123456, 366123456], dtype="Int64"),
            "timestamp": pd.to_datetime(["2021-01-01T00:00:00Z", "2021-01-03T00:00:00Z"], utc=True),
            "port_complex_id": ["san_pedro_bay", "san_pedro_bay"],
            "state": ["berth", "transit"],
            "call_id": ["san_pedro_bay|366123456|1", "san_pedro_bay|366123456|2"],
        }
    )

    intervals = compute_state_intervals(pings)

    assert intervals.empty


def test_evaluate_g1_requires_every_registered_threshold():
    """G1 cannot pass on a preferred metric while macro-F1 or national scope fails."""

    from process_ais.mode_validation import evaluate_g1

    passing = evaluate_g1(
        {"a": 0.80, "b": 0.80, "c": 0.81, "d": 0.82, "e": 0.10},
        blind_macro_f1=0.85,
        validated_complexes=12,
    )
    failed = evaluate_g1(
        {"a": 0.90, "b": 0.90, "c": 0.90, "d": 0.90, "e": 0.10},
        blind_macro_f1=0.84,
        validated_complexes=11,
    )

    assert passing["passed"]
    assert passing["correlation_port_fraction"] == 0.8
    assert not failed["passed"]
    assert failed["correlation_gate_passed"]
    assert not failed["macro_f1_gate_passed"]
    assert not failed["national_scope_gate_passed"]


def test_ingest_filtered_chunks_reuses_schema_and_deduplicates_across_chunks():
    """Chunk order cannot change canonical rows or hide rejected source records."""

    from process_ais.build_dwell_census import ingest_filtered_chunks

    first = pd.DataFrame(
        {
            "MMSI": [366123456, 366123457],
            "BaseDateTime": ["2020-01-01T00:00:00Z", "not-a-timestamp"],
            "LAT": [33.75, 33.75],
            "LON": [-118.20, -118.20],
            "SOG": [0.4, 0.4],
            "VesselType": [70, 70],
            "Cargo": [70, 70],
        }
    )
    second = pd.DataFrame(
        {
            "mmsi": [366123456],
            "base_datetime": ["2020-01-01T00:00:00Z"],
            "lat": [33.75],
            "lon": [-118.20],
            "sog": [0.4],
            "vessel_type": [70],
            "cargo": [70],
        }
    )

    accepted, rejected, raw_row_count = ingest_filtered_chunks(
        [first, second],
        source_file="ais-2020-01-01.csv.zst",
        port_complex_id="san_pedro_bay",
    )

    assert raw_row_count == 3
    assert accepted.mmsi.tolist() == [366123456]
    assert rejected.reason.tolist() == ["invalid_timestamp"]


def test_ingest_national_chunks_keeps_complete_parse_counts_while_retaining_only_safe_areas():
    from process_ais.build_dwell_census import ingest_national_chunks

    first = pd.DataFrame(
        {
            "MMSI": [366123456, 366123457],
            "BaseDateTime": ["2020-01-01T00:00:00Z", "not-a-timestamp"],
            "LAT": [0.5, 0.5],
            "LON": [0.5, 0.5],
            "SOG": [0.4, 0.4],
            "COG": [180.0, 180.0],
            "VesselType": [70, 70],
            "Cargo": [70, 70],
        }
    )
    second = pd.DataFrame(
        {
            "MMSI": [366123456, 366123458],
            "BaseDateTime": ["2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z"],
            "LAT": [0.5, 4.5],
            "LON": [0.5, 4.5],
            "SOG": [0.4, 0.4],
            "COG": [180.0, 180.0],
            "VesselType": [70, 70],
            "Cargo": [70, 70],
        }
    )
    areas = gpd.GeoDataFrame(
        {"port_complex_id": ["alpha", "charlie"]},
        geometry=[box(0, 0, 1, 1), box(4, 4, 5, 5)],
        crs="EPSG:4326",
    )
    coverage = pd.DataFrame(
        {
            "port_complex_id": ["alpha", "charlie"],
            "spatial_assignment_status": ["assignable", "requires_finer_geometry"],
        }
    )

    pings, summary = ingest_national_chunks(
        [first, second],
        source_file="ais-2020-01-01.csv.zst",
        port_areas=areas,
        assignment_coverage=coverage,
    )

    assert pings.mmsi.tolist() == [366123456]
    assert pings.port_complex_id.tolist() == ["alpha"]
    assert summary == {
        "raw_row_count": 4,
        "accepted_row_count": 3,
        "rejected_row_count": 1,
        "rejection_counts": {"invalid_timestamp": 1},
        "first_timestamp": "2020-01-01T00:00:00+00:00",
        "last_timestamp": "2020-01-01T01:00:00+00:00",
    }


def test_ingest_national_file_binds_streamed_parse_accounting_to_its_raw_source(tmp_path):
    from process_ais.build_dwell_census import ingest_national_file

    raw_path = tmp_path / "temporary-download.csv"
    raw_path.write_text(
        "MMSI,BaseDateTime,LAT,LON,SOG,COG,VesselType,Cargo\n"
        "366123456,2020-01-01T00:00:00Z,0.5,0.5,0.4,180,70,70\n"
        "366123457,not-a-timestamp,0.5,0.5,0.4,180,70,70\n",
        encoding="utf-8",
    )
    areas = gpd.GeoDataFrame(
        {"port_complex_id": ["alpha"]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:4326"
    )
    coverage = pd.DataFrame(
        {"port_complex_id": ["alpha"], "spatial_assignment_status": ["assignable"]}
    )

    pings, manifest = ingest_national_file(
        raw_path,
        source_url="https://example.test/ais-2020-01-01.csv",
        retrieved_at="2026-07-13T13:00:00Z",
        port_areas=areas,
        assignment_coverage=coverage,
        source_file="ais-2020-01-01.csv",
    )

    assert pings.port_complex_id.tolist() == ["alpha"]
    assert manifest["source_file"] == "ais-2020-01-01.csv"
    assert manifest["raw_row_count"] == 2
    assert manifest["accepted_row_count"] == 1
    assert manifest["rejection_counts"] == '{"invalid_timestamp":1}'


def test_write_immutable_parquet_refuses_to_replace_an_existing_artifact(tmp_path):
    """A rerun must not silently overwrite an immutable ingestion artifact."""

    from process_ais.build_dwell_census import write_immutable_parquet

    destination = tmp_path / "pings.parquet"
    pings = pd.DataFrame({"mmsi": pd.Series([366123456], dtype="Int64")})

    write_immutable_parquet(pings, destination)

    assert pd.read_parquet(destination).mmsi.tolist() == [366123456]
    with pytest.raises(FileExistsError):
        write_immutable_parquet(pings, destination)
