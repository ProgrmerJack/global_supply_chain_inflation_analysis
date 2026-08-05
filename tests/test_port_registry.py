"""Tests for the frozen 2017–2019 national port-complex rule."""

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))
import port_registry as registry  # noqa: E402
from port_registry import (  # noqa: E402
    MAX_COMPLEXES,
    RANKING_YEARS,
    TOP_COMPLEXES,
    aggregate_port_complexes,
    build_crosswalk,
    is_contiguous_seaport,
    select_complexes,
)


def test_containerized_port_totals_do_not_apply_a_commodity_level_filter(monkeypatch):
    """Census supplies aggregate port totals when no commodity predicate is set."""

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                ["PORT", "PORT_NAME", "CNT_VAL_YR", "time"],
                ["-", "TOTAL FOR ALL PORTS", "1120", "2017-12"],
                ["0401", "BOSTON, MA", "120", "2017-12"],
                ["6000", "VESSELS UNDER OWN POWER", "0", "2017-12"],
            ]

    requests = []

    def fake_get(_url, *, params, timeout):
        requests.append(params)
        assert timeout == 120
        return Response()

    monkeypatch.setattr(registry.requests, "get", fake_get)

    result = registry.fetch_containerized_by_port(key="test-key")

    assert len(requests) == len(RANKING_YEARS)
    assert all("COMM_LVL" not in request for request in requests)
    assert result.port_code.tolist() == ["0401"]
    assert result.loc[0, "cnt_val_annual_usd"] == 120.0


def test_monthly_port_activity_fetches_physical_vessel_shipping_weight(monkeypatch):
    """The existing Census client must expose physical monthly cargo measures without a second client."""

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                ["PORT", "PORT_NAME", "VES_WGT_MO", "time"],
                ["-", "TOTAL FOR ALL PORTS", "0", "2021-01"],
                ["0401", "BOSTON, MA", "120", "2021-01"],
                ["6000", "VESSELS UNDER OWN POWER", "0", "2021-01"],
            ]

    requests = []

    def fake_get(_url, *, params, timeout):
        requests.append(params)
        assert timeout == 120
        return Response()

    monkeypatch.setattr(registry.requests, "get", fake_get)

    result = registry.fetch_monthly_vessel_activity_by_port(["2021-01"], measure="VES_WGT_MO", key="test-key")

    assert requests == [{"get": "PORT,PORT_NAME,VES_WGT_MO", "time": "2021-01", "key": "test-key"}]
    assert result.to_dict("records") == [
        {"port_code": "0401", "port_name": "BOSTON, MA", "year_month": "2021-01", "ves_wgt_mo": 120.0}
    ]


def test_monthly_port_activity_retains_a_hashed_raw_response_and_manifest(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                ["PORT", "PORT_NAME", "VES_WGT_MO", "time"],
                ["0401", "BOSTON, MA", "120", "2021-01"],
            ]

    monkeypatch.setattr(registry.requests, "get", lambda *_args, **_kwargs: Response())

    registry.fetch_monthly_vessel_activity_by_port(
        ["2021-01"], measure="VES_WGT_MO", key="test-key", raw_dir=tmp_path
    )

    raw = tmp_path / "imports_porths_VES_WGT_MO_2021-01.json"
    manifest = pd.read_csv(tmp_path / "requests_manifest.csv")
    assert raw.exists()
    assert manifest.loc[0, "source_file"] == raw.name
    assert manifest.loc[0, "source_url"].startswith(registry.BASE)
    assert len(manifest.loc[0, "sha256"]) == 64
    assert manifest.loc[0, "raw_row_count"] == 1


def test_national_rule_keeps_top_twenty_even_when_coverage_is_early():
    values = [100] * 10 + [1] * 20

    keep, _, reached_coverage = select_complexes(values)

    assert keep.sum() == 20
    assert reached_coverage


def test_candidate_universe_excludes_noncontiguous_and_great_lakes_ports():
    assert is_contiguous_seaport("2704", "LOS ANGELES, CA")
    assert is_contiguous_seaport("2002", "NEW ORLEANS, LA")
    assert not is_contiguous_seaport("4909", "SAN JUAN, PR")
    assert not is_contiguous_seaport("3901", "CHICAGO, IL")
    assert not is_contiguous_seaport("0901", "BUFFALO-NIAGARA FALLS, NY")


def test_national_rule_continues_to_ninety_percent_but_stops_at_thirty():
    values = [1] * 35

    keep, cumulative_share, reached_coverage = select_complexes(values)

    assert keep.sum() == MAX_COMPLEXES
    assert not reached_coverage
    assert cumulative_share[keep].max() == MAX_COMPLEXES / len(values)


def test_complexes_are_aggregated_before_ranking():
    ports = pd.DataFrame(
        {
            "port_code": ["1001", "1002", "2001"],
            "port_name": ["Harbor A", "Harbor B", "Harbor C"],
            "cnt_val_annual_usd": [60.0, 40.0, 90.0],
        }
    )
    crosswalk = pd.DataFrame(
        {
            "port_complex_id": ["A_B", "C"],
            "port_complex_name": ["Harbor A/B", "Harbor C"],
            "coast": ["Pacific", "Atlantic"],
            "component_port_codes": ["1001;1002", "2001"],
            "geometry_version": ["v1", "v1"],
            "source_vintage": ["2026-07-13", "2026-07-13"],
        }
    )

    complexes = aggregate_port_complexes(ports, crosswalk)

    assert complexes.set_index("port_complex_id").loc["A_B", "ranking_value_2017_2019"] == 100.0
    assert complexes.sort_values("ranking_value_2017_2019", ascending=False).iloc[0].port_complex_id == "A_B"


def test_crosswalk_uses_only_registered_operational_merges_and_preserves_geographic_holdouts():
    ports = pd.DataFrame(
        {
            "port_code": ["2704", "2709", "1001", "1003", "3001", "3002", "1703"],
            "port_name": [
                "LOS ANGELES, CA",
                "LONG BEACH, CA",
                "NEW YORK, NY",
                "NEWARK, NJ",
                "SEATTLE, WA",
                "TACOMA, WA",
                "SAVANNAH, GA",
            ],
            "cnt_val_annual_usd": [1.0] * 7,
        }
    )

    crosswalk = build_crosswalk(ports)

    assert crosswalk.set_index("port_complex_id").loc["san_pedro_bay", "component_port_codes"] == "2704;2709"
    assert crosswalk.set_index("port_complex_id").loc["new_york_new_jersey", "component_port_codes"] == "1001;1003"
    assert crosswalk.set_index("port_complex_id").loc["seattle_wa", "component_port_codes"] == "3001"
    assert crosswalk.set_index("port_complex_id").loc["tacoma_wa", "component_port_codes"] == "3002"
    assert crosswalk.set_index("port_complex_id").loc["savannah_ga", "operational_rule"] == "single_census_customs_port"


def test_registry_keeps_excluded_complexes_and_writes_a_receipt(monkeypatch, tmp_path):
    ports = pd.DataFrame(
        {
            "port_code": [f"{9000 + index}" for index in range(35)],
            "port_name": [f"PORT {index}, CA" for index in range(35)],
            "cnt_val_annual_usd": [1.0] * 35,
        }
    )
    crosswalk_path = tmp_path / "crosswalk.csv"
    output_path = tmp_path / "port_registry.csv"
    receipt_path = tmp_path / "port_universe_receipt.json"
    build_crosswalk(ports).to_csv(crosswalk_path, index=False)
    monkeypatch.setattr(registry, "fetch_containerized_by_port", lambda: ports)

    registry_frame = registry.build_registry(crosswalk_path, output_path, receipt_path)

    assert len(registry_frame) == 35
    assert (registry_frame.inclusion_status == "included").sum() == MAX_COMPLEXES
    assert (registry_frame.inclusion_status == "excluded_by_selection_rule").sum() == 5
    written = pd.read_csv(output_path, dtype={"component_port_codes": str})
    assert len(written) == 35
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["selection"]["included_complexes"] == MAX_COMPLEXES
    assert receipt["registry"]["sha256"]


def test_ranking_window_and_constants_are_frozen():
    assert RANKING_YEARS == ("2017", "2018", "2019")
    assert TOP_COMPLEXES == 20
    assert MAX_COMPLEXES == 30
