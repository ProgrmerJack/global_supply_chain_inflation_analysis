"""Synthetic and frozen-input tests for the CARB At-Berth tanker blind gate."""

from __future__ import annotations

import json
import os
import sys

import pandas as pd
import pytest
import geopandas as gpd
from shapely.geometry import box


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_tanker_population_is_static_first_and_excludes_binary_disagreement():
    from analysis.atberth_tanker_event import classify_tanker_population

    static = pd.DataFrame({"mmsi": [1, 2, 3], "vessel_type": [80, 70, float("nan")]})
    ping = pd.DataFrame({"mmsi": [1, 2, 3, 4], "vessel_type": [81, 89, 84, 70]})
    ledger = classify_tanker_population(static, ping).set_index("mmsi")

    assert bool(ledger.loc[1, "is_tanker"])
    assert not bool(ledger.loc[2, "is_tanker"])
    assert bool(ledger.loc[2, "tanker_status_disagreement"])
    assert bool(ledger.loc[3, "is_tanker"])
    assert ledger.loc[3, "type_source"] == "census_modal"
    assert not bool(ledger.loc[4, "is_tanker"])


def test_regulatory_tanker_population_uses_observed_400ft_rule_and_keeps_sensitivity():
    from analysis.atberth_tanker_event import classify_regulatory_tanker_population

    static = pd.DataFrame({
        "mmsi": [1, 2, 3, 4],
        "vessel_type": [80, 84, 81, 70],
        "length_m": [50.0, 500.0, 500.0, 500.0],
    })
    ping = pd.DataFrame({
        "mmsi": [1, 2, 3, 4],
        "vessel_type": [80, 84, 81, 70],
        "length_m": [121.92, 100.0, None, 200.0],
    })
    ledger = classify_regulatory_tanker_population(static, ping).set_index("mmsi")

    assert bool(ledger.loc[1, "regulatory_eligible_tanker"])
    assert not bool(ledger.loc[2, "regulatory_eligible_tanker"])
    assert bool(ledger.loc[2, "nmea_tanker_sensitivity"])
    assert ledger.loc[2, "regulatory_exclusion_reason"] == "below_400ft_observable_rule"
    assert ledger.loc[3, "regulatory_exclusion_reason"] == "missing_regulatory_length"
    assert not bool(ledger.loc[4, "nmea_tanker_sensitivity"])


def _synthetic_spb_terminals():
    return gpd.GeoDataFrame(
        {
            "terminal_id": ["pola_test", "polb_test"],
            "port": ["Los Angeles", "Long Beach"],
        },
        geometry=gpd.points_from_xy([-118.27, -118.20], [33.75, 33.77]),
        crs="EPSG:4326",
    )


def test_recovery_zone_and_terminal_assignment_use_only_frozen_geometry():
    from analysis.atberth_tanker_event import (
        mark_recovery_trajectory_zones,
        terminal_contact_geometry,
    )

    terminals = _synthetic_spb_terminals()
    pings = pd.DataFrame(
        {"lon": [-118.45, -118.35, -118.27], "lat": [33.75, 33.75, 33.75]}
    )
    zones = mark_recovery_trajectory_zones(
        pings,
        inner_geometry=box(-118.40, 33.60, -118.10, 33.90),
        outer_geometry=box(-118.50, 33.50, -118.00, 34.00),
        contact_geometry=terminal_contact_geometry(terminals, buffer_m=750),
    )

    assert zones.tolist() == ["outside", "coastal", "port_contact"]


def test_recovery_zone_matches_native_ingestion_boundary():
    from analysis.atberth_tanker_event import (
        mark_recovery_trajectory_zones,
        recovery_domain_geometries,
    )

    domains = recovery_domain_geometries()["baltimore_md"]
    zones = mark_recovery_trajectory_zones(
        pd.DataFrame({"lon": [-76.43479], "lat": [38.73107]}),
        inner_geometry=domains["coastal_inner"],
        outer_geometry=domains["coastal_outer"],
        contact_geometry=box(-77, 38, -76.9, 38.1),
        contact_geometry_crs="EPSG:4326",
    )

    assert zones.iloc[0] in {"outside", "coastal"}


def test_spb_recovery_visit_requires_observed_entry_exit_and_terminal_contact():
    from analysis.atberth_tanker_event import build_spb_recovery_visits

    pings = pd.DataFrame({
        "mmsi": [111] * 6,
        "port_complex_id": ["san_pedro_bay"] * 6,
        "timestamp": pd.to_datetime([
            "2024-01-01T00:00Z", "2024-01-01T00:10Z",
            "2024-01-01T00:20Z", "2024-01-01T00:30Z",
            "2024-01-01T00:40Z", "2024-01-01T00:50Z",
        ], utc=True),
        "trajectory_zone": [
            "outside", "coastal", "port_contact", "port_contact", "outside", "outside",
        ],
        "lon": [-118.45, -118.35, -118.27, -118.27, -118.42, -118.45],
        "lat": [33.75] * 6,
    })

    visits = build_spb_recovery_visits(pings, _synthetic_spb_terminals())

    assert len(visits) == 1
    assert bool(visits.iloc[0].complete_regulatory_visit)
    assert visits.iloc[0].terminal_id == "pola_test"
    assert visits.iloc[0].terminal_port == "Los Angeles"


def test_interval_metrics_cap_gaps_keep_singletons_and_separate_missing_sog():
    from analysis.atberth_tanker_event import call_interval_metrics

    pings = pd.DataFrame(
        {
            "mmsi": [1, 1, 1, 2],
            "port_complex_id": ["p"] * 4,
            "timestamp": pd.to_datetime(
                ["2024-01-01T00:00Z", "2024-01-01T01:00Z", "2024-01-01T05:00Z", "2024-01-02T00:00Z"],
                utc=True,
            ),
            "sog": [0.1, None, 12.0, 0.0],
            "berth_inside": [True, False, False, True],
        }
    )
    calls = call_interval_metrics(pings, interval_cap_hours=2).sort_values("mmsi").reset_index(drop=True)

    assert len(calls) == 2
    assert calls.loc[0, "interval_hours"] == pytest.approx(3.0)
    assert calls.loc[0, "berth_stationary_hours"] == pytest.approx(1.0)
    assert calls.loc[0, "unresolved_sog_hours"] == pytest.approx(2.0)
    assert bool(calls.loc[0, "resolved_call"])
    assert not bool(calls.loc[1, "resolved_call"])
    assert calls.loc[1, "n_pings"] == 1


def test_mark_berth_pings_is_boundary_inclusive_and_missing_safe():
    from analysis.atberth_tanker_event import mark_berth_pings

    pings = pd.DataFrame({"lon": [0.5, 1.0, 2.0, None], "lat": [0.5, 0.5, 2.0, 0.0]})
    assert mark_berth_pings(pings, box(0, 0, 1, 1)).tolist() == [True, True, False, False]


def test_monthly_panel_preserves_raw_denominators_and_physical_outcomes():
    from analysis.atberth_tanker_event import aggregate_monthly_call_panel

    calls = pd.DataFrame(
        {
            "port_complex_id": ["p", "p", "p"],
            "year_month": ["2024-01"] * 3,
            "mmsi": [1, 2, 2],
            "resolved_call": [True, True, False],
            "interval_hours": [10.0, 20.0, 0.0],
            "berth_stationary_hours": [4.0, 8.0, 0.0],
            "outside_berth_stationary_hours": [2.0, 4.0, 0.0],
            "elapsed_hours": [12.0, 24.0, 0.0],
            "moving_10kt_hours": [1.0, 3.0, 0.0],
            "unresolved_sog_hours": [0.5, 1.0, 0.0],
            "length_m": [200.0, 220.0, 220.0],
            "width_m": [32.0, 34.0, 34.0],
            "draft_m": [8.0, 9.0, 9.0],
            "new_to_port_vessel": [True, True, False],
            "arrival_local_hour": [1.0, 2.0, 3.0],
            "weekend_arrival": [False, True, True],
        }
    )
    panel = aggregate_monthly_call_panel(calls).iloc[0]

    assert panel.tanker_calls == 3
    assert panel.unique_tankers == 2
    assert panel.resolved_tanker_calls == 2
    assert panel.mean_berth_stationary_hours == pytest.approx(6.0)
    assert panel.total_berth_stationary_hours == pytest.approx(12.0)
    assert panel.unresolved_sog_time_share == pytest.approx(0.05)


def _gate_calls() -> pd.DataFrame:
    rows = []
    for port, n in [("san_pedro_bay", 60), *[(f"donor_{i}", 25) for i in range(6)]]:
        for year in (2024, 2025):
            for index in range(n):
                rows.append(
                    {
                        "port_complex_id": port,
                        "year": year,
                        "resolved_call": True,
                        "interval_hours": 10.0,
                        "unresolved_sog_hours": 0.5,
                        "has_berth_stationary_interval": port != "san_pedro_bay" or index < 54,
                    }
                )
    # Add unresolved singletons so AIS call coverage can match the 634 official arrivals.
    rows.extend(
        {
            "port_complex_id": "san_pedro_bay",
            "year": 2024,
            "resolved_call": False,
            "interval_hours": 0.0,
            "unresolved_sog_hours": 0.0,
            "has_berth_stationary_interval": False,
        }
        for _ in range(574)
    )
    return pd.DataFrame(rows)


def test_blind_gate_passes_only_jointly():
    from analysis.atberth_tanker_event import evaluate_blind_gate

    source = {
        "all_dates_ok": True,
        "months_below_95pct": [],
        "expected_dates": 3287,
        "dates_ok": 3287,
        "minimum_month_coverage": 1.0,
        "prior_non_ok_attempts": 4,
    }
    decision = evaluate_blind_gate(_gate_calls(), source, {"spb_total": 634, "year": 2024})
    assert decision["status"] == "pass"
    assert decision["effect_estimation_authorized"]
    assert decision["official_2024_comparator"]["absolute_fractional_error"] == 0

    failed = _gate_calls()
    failed.loc[failed.port_complex_id.eq("san_pedro_bay"), "unresolved_sog_hours"] = 2.0
    decision = evaluate_blind_gate(failed, source, {"spb_total": 634, "year": 2024})
    assert decision["status"] == "fail"
    assert not decision["effect_estimation_authorized"]


def test_recovery_call_gate_requires_combined_and_port_specific_match():
    from analysis.atberth_tanker_event import evaluate_recovery_call_gate

    timestamps = pd.to_datetime(["2024-06-01T00:00Z"] * 634, utc=True)
    spb = pd.DataFrame({
        "terminal_contact_timestamp": timestamps,
        "terminal_port": ["Los Angeles"] * 143 + ["Long Beach"] * 491,
        "complete_regulatory_visit": True,
    })
    donor_rows = []
    for port in [f"donor_{number}" for number in range(5)]:
        for year in (2024, 2025):
            donor_rows.extend({
                "port_complex_id": port,
                "port_contact_timestamp": pd.Timestamp(f"{year}-06-01", tz="UTC"),
                "complete_regulatory_visit": True,
            } for _ in range(20))
    donor = pd.DataFrame(donor_rows)
    source = {
        "all_dates_ok": True,
        "months_below_95pct": [],
        "expected_dates": 3287,
        "dates_ok": 3287,
    }
    official = {
        "spb_total": 634,
        "port_totals": {"Port of Los Angeles": 143, "Port of Long Beach": 491},
    }
    population = {"regulatory_length_coverage": 0.99}

    decision = evaluate_recovery_call_gate(
        spb,
        donor,
        source_summary=source,
        official=official,
        population_summary=population,
    )

    assert decision["status"] == "fail"
    assert not decision["conditions"]["spb_at_least_50_complete_visits_in_2025"]

    spb_2025 = spb.iloc[:50].copy()
    spb_2025["terminal_contact_timestamp"] = pd.Timestamp("2025-06-01", tz="UTC")
    passed = evaluate_recovery_call_gate(
        pd.concat([spb, spb_2025], ignore_index=True),
        donor,
        source_summary=source,
        official=official,
        population_summary=population,
    )
    assert passed["status"] == "pass"


def test_public_registration_guard_is_exact_and_fail_closed(tmp_path):
    from analysis.atberth_tanker_event import require_public_registration

    receipt = tmp_path / "timestamp.json"
    receipt.write_text(
        json.dumps(
            {
                "registration_id": "w6zsg",
                "osf_state_at_verification": {
                    "public": True,
                    "pending_registration_approval": False,
                },
            }
        ),
        encoding="utf-8",
    )
    assert require_public_registration(receipt)["registration_id"] == "w6zsg"
    receipt.write_text(json.dumps({"registration_id": "w6zsg", "osf_state_at_verification": {}}))
    with pytest.raises(RuntimeError, match="not publicly approved"):
        require_public_registration(receipt)


def test_frozen_official_tanker_arrival_comparator_is_type_matched_and_hashed():
    from analysis.atberth_tanker_event import official_tanker_arrivals

    official = official_tanker_arrivals()
    assert official["port_totals"] == {"Port of Long Beach": 491, "Port of Los Angeles": 143}
    assert official["spb_total"] == 634
    assert official["subtype_rows"] == 10


def test_sea_to_port_visits_do_not_split_short_excursion_or_in_port_shift():
    from process_ais.port_call_segmentation import assign_sea_to_port_visit_ids

    frame = pd.DataFrame({
        "mmsi": [111] * 8,
        "port_complex_id": ["san_pedro_bay"] * 8,
        "timestamp": pd.to_datetime([
            "2024-01-01T00:00Z",  # observed at sea before entry
            "2024-01-01T02:00Z",
            "2024-01-01T04:00Z",
            "2024-01-01T08:00Z",  # short outside excursion
            "2024-01-01T12:00Z",
            "2024-01-01T18:00Z",  # berth shift remains one visit
            "2024-01-02T00:00Z",
            "2024-01-02T14:00Z",  # sustained outbound observation
        ], utc=True),
        "trajectory_zone": [
            "outside", "coastal", "port_contact", "outside",
            "coastal", "port_contact", "outside", "outside",
        ],
    })

    result = assign_sea_to_port_visit_ids(frame, exit_hysteresis_hours=12)
    assigned = result.loc[result.visit_id.notna()]

    assert assigned.visit_id.nunique() == 1
    assert assigned.visit_valid.all()
    assert not assigned.visit_left_censored.any()
    assert not assigned.visit_right_censored.any()


def test_sea_to_port_visits_split_only_after_observed_sustained_exit():
    from process_ais.port_call_segmentation import assign_sea_to_port_visit_ids

    frame = pd.DataFrame({
        "mmsi": [222] * 8,
        "port_complex_id": ["san_pedro_bay"] * 8,
        "timestamp": pd.to_datetime([
            "2024-02-01T00:00Z", "2024-02-01T02:00Z", "2024-02-01T04:00Z",
            "2024-02-01T10:00Z", "2024-02-01T18:00Z",
            "2024-02-02T00:00Z", "2024-02-02T02:00Z", "2024-02-02T16:00Z",
        ], utc=True),
        "trajectory_zone": [
            "outside", "coastal", "port_contact", "outside",
            "outside", "coastal", "port_contact", "outside",
        ],
    })

    result = assign_sea_to_port_visit_ids(frame, exit_hysteresis_hours=12)
    assigned = result.loc[result.visit_id.notna()]

    assert assigned.visit_id.nunique() == 2
    assert assigned.groupby("visit_id").visit_valid.first().all()


def test_sea_to_port_exit_requires_the_frozen_minimum_observation_count():
    from process_ais.port_call_segmentation import assign_sea_to_port_visit_ids

    frame = pd.DataFrame({
        "mmsi": [333] * 7,
        "port_complex_id": ["san_pedro_bay"] * 7,
        "timestamp": pd.to_datetime([
            "2024-03-01T00:00Z", "2024-03-01T00:10Z", "2024-03-01T00:20Z",
            "2024-03-01T01:00Z",  # only one outside observation
            "2024-03-01T02:00Z", "2024-03-01T02:10Z", "2024-03-01T03:00Z",
        ], utc=True),
        "trajectory_zone": [
            "outside", "coastal", "port_contact", "outside",
            "coastal", "port_contact", "outside",
        ],
    })

    result = assign_sea_to_port_visit_ids(
        frame,
        exit_hysteresis_hours=0.25,
        min_exit_observations=2,
    )
    assigned = result.loc[result.visit_id.notna()]

    assert assigned.visit_id.nunique() == 1
    assert assigned.visit_right_censored.all()
