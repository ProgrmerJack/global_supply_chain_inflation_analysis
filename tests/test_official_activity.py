"""Official-activity port->complex mapping (official_port_activity.map_ports_to_complexes).

Exercises the pure aggregation on synthetic Census rows; no live Census call.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def _registry():
    return pd.DataFrame(
        {
            "port_complex_id": ["san_pedro_bay", "savannah_ga", "gulfport_ms"],
            "component_port_codes": ["2704;2709", "1703", "1902"],
            "inclusion_status": ["included", "included", "excluded_by_selection_rule"],
        }
    )


def test_sums_component_codes_into_included_complex():
    from process_ais.official_port_activity import map_ports_to_complexes

    monthly = pd.DataFrame(
        {
            "port_code": ["2704", "2709", "1703", "1902", "9999"],
            "year_month": ["2021-01"] * 5,
            "cnt_val_mo": [10.0, 5.0, 7.0, 3.0, 99.0],
        }
    )
    out = map_ports_to_complexes(monthly, _registry()).set_index(["port_complex_id", "year_month"])
    assert out.loc[("san_pedro_bay", "2021-01"), "official_activity"] == pytest.approx(15.0)  # 2704+2709
    assert out.loc[("savannah_ga", "2021-01"), "official_activity"] == pytest.approx(7.0)
    assert "gulfport_ms" not in out.index.get_level_values(0)  # excluded complex dropped
    assert "9999" not in out.reset_index().port_complex_id.tolist()  # unknown port not mapped


def test_unmapped_ports_are_dropped_not_errored():
    from process_ais.official_port_activity import map_ports_to_complexes

    monthly = pd.DataFrame({"port_code": ["9999"], "year_month": ["2021-05"], "cnt_val_mo": [1.0]})
    out = map_ports_to_complexes(monthly, _registry())
    assert out.empty and list(out.columns) == ["port_complex_id", "year_month", "official_activity"]


def test_sums_a_declared_physical_measure_into_complexes():
    from process_ais.official_port_activity import map_ports_to_complexes

    monthly = pd.DataFrame(
        {
            "port_code": ["2704", "2709", "1703"],
            "year_month": ["2021-01"] * 3,
            "ves_wgt_mo": [10.0, 5.0, 7.0],
        }
    )

    out = map_ports_to_complexes(monthly, _registry(), value_column="ves_wgt_mo").set_index(
        ["port_complex_id", "year_month"]
    )
    assert out.loc[("san_pedro_bay", "2021-01"), "official_activity"] == pytest.approx(15.0)
    assert out.loc[("savannah_ga", "2021-01"), "official_activity"] == pytest.approx(7.0)


def test_physical_measure_requires_a_distinct_output_path():
    from process_ais.official_port_activity import build_official_activity

    with pytest.raises(ValueError, match="explicit non-default output path"):
        build_official_activity(["2021-01"], measure="VES_WGT_MO")


def test_physical_measure_uses_a_measure_specific_raw_provenance_directory(monkeypatch, tmp_path):
    import process_ais.official_port_activity as activity

    registry_path = tmp_path / "registry.csv"
    _registry().to_csv(registry_path, index=False)
    seen = {}

    def fake_fetch(months, *, measure, key, raw_dir):
        seen.update(months=months, measure=measure, raw_dir=raw_dir)
        return pd.DataFrame({"port_code": ["1703"], "port_name": ["SAVANNAH, GA"],
                             "year_month": ["2021-01"], "ves_wgt_mo": [10.0]})

    monkeypatch.setattr(activity, "fetch_monthly_vessel_activity_by_port", fake_fetch)
    activity.build_official_activity(
        ["2021-01"], registry_path=registry_path, out_path=tmp_path / "physical.csv", measure="VES_WGT_MO"
    )

    assert seen["measure"] == "VES_WGT_MO"
    assert seen["raw_dir"].name == "ves_wgt_mo"
    assert seen["raw_dir"].parent.name == "official_port_activity"


def test_operational_comparator_registry_covers_every_assignable_complex_once():
    root = Path(__file__).resolve().parents[1]
    comparator = pd.read_csv(root / "config" / "registries" / "g1_operational_comparator_registry.csv", dtype=str)
    panel = pd.read_csv(root / "data" / "processed" / "national_activity_month.csv")
    ports = pd.read_csv(root / "data" / "processed" / "port_registry.csv", dtype={"component_port_codes": str})

    assert comparator.port_complex_id.is_unique
    assert set(comparator.port_complex_id) == set(panel.port_complex_id.unique())
    assert set(comparator.official_measure) == {"VES_WGT_MO"}
    assert set(comparator.ais_measure) == {"freight_port_calls"}
    expected_codes = ports.set_index("port_complex_id").loc[comparator.port_complex_id, "component_port_codes"]
    assert comparator.component_port_codes.tolist() == expected_codes.tolist()


def test_expand_months_range():
    from process_ais.official_port_activity import _expand_months

    assert _expand_months("2021-01:2021-03") == ["2021-01", "2021-02", "2021-03"]
    assert _expand_months("2021-01,2021-06") == ["2021-01", "2021-06"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
