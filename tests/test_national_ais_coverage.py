"""Metadata-only national NOAA AIS coverage checks."""

import os
import sys

import pandas as pd


ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def test_port_geometry_coverage_keeps_safe_zeroes_distinct_from_unresolved_ports():
    from process_ais.national_ais_coverage import build_port_geometry_coverage

    pings = pd.DataFrame({"port_complex_id": ["alpha", "alpha"]})
    assignment_coverage = pd.DataFrame(
        {
            "port_complex_id": ["alpha", "bravo", "charlie", "delta"],
            "port_area_status": ["available", "available", "available", "unavailable"],
            "spatial_assignment_status": [
                "assignable",
                "assignable",
                "requires_finer_geometry",
                "unavailable",
            ],
        }
    )

    coverage = build_port_geometry_coverage(
        pings,
        assignment_coverage,
        source_date="2025-01-15",
        source_file="ais-2025-01-15.csv.zst",
    )

    assert coverage.columns.tolist() == [
        "source_date",
        "source_file",
        "port_complex_id",
        "port_area_status",
        "spatial_assignment_status",
        "assigned_ping_count",
    ]
    assert coverage.loc[coverage.port_complex_id.eq("alpha"), "assigned_ping_count"].tolist() == [2]
    assert coverage.loc[coverage.port_complex_id.eq("bravo"), "assigned_ping_count"].tolist() == [0]
    assert pd.isna(coverage.loc[coverage.port_complex_id.eq("charlie"), "assigned_ping_count"].iloc[0])
    assert pd.isna(coverage.loc[coverage.port_complex_id.eq("delta"), "assigned_ping_count"].iloc[0])
