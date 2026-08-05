"""BTS official-TEU ingest: the per-complex aggregation (san_pedro_bay = LA + Long Beach). No network."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))


def test_san_pedro_bay_sums_la_plus_long_beach():
    from ingest_bts_official import complex_teu_series, COMPLEX_TO_BTS_TEU

    df = pd.DataFrame({
        "year_month": ["2021-09", "2021-10"],
        "los_angeles_ca": [900000.0, 850000.0],
        "long_beach_ca": [800000.0, 780000.0],
        "port_of_ny_nj": [600000.0, 610000.0],
    })
    spb = complex_teu_series(df, COMPLEX_TO_BTS_TEU["san_pedro_bay"])
    assert list(spb["value"]) == [1700000.0, 1630000.0]        # LA + LB, month-aligned
    assert list(spb["year_month"]) == ["2021-09", "2021-10"]

    nynj = complex_teu_series(df, COMPLEX_TO_BTS_TEU["new_york_new_jersey"])
    assert list(nynj["value"]) == [600000.0, 610000.0]         # single column, unchanged


def test_registry_complexes_map_to_known_bts_columns():
    from ingest_bts_official import COMPLEX_TO_BTS_TEU
    # the 3 gateways whose registry PRIMARY is TEU must be covered by BTS
    assert {"savannah_ga", "houston_tx", "charleston_sc"} <= set(COMPLEX_TO_BTS_TEU)


def test_annual_container_calls_filters_and_sums_la_plus_lb():
    from ingest_bts_official import annual_container_calls
    df = pd.DataFrame({
        "cargo_type": ["VESSEL CALLS", "VESSEL CALLS", "VESSEL CALLS", "CONTAINER"],
        "trade_type": ["Container", "Container", "Dry Bulk", "TOTAL"],
        "complex_id": ["san_pedro_bay", "san_pedro_bay", "san_pedro_bay", "san_pedro_bay"],
        "year": ["2021", "2021", "2021", "2021"],
        "volume": [876.5, 895.5, 500.0, 7037986.0],   # LA + LB container calls; Dry Bulk + TEU excluded
    })
    s = annual_container_calls(df, "san_pedro_bay")
    assert list(s["year"]) == ["2021"] and list(s["value"]) == [1772]   # round(876.5+895.5)


def test_all_11_gateways_have_a_5rpz_name():
    from ingest_bts_official import PORT_NAME_TO_COMPLEX
    assert len(set(PORT_NAME_TO_COMPLEX.values())) == 11
    assert "norfolk_newport_news_va" in PORT_NAME_TO_COMPLEX.values()   # "Virginia, VA, Port of"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
