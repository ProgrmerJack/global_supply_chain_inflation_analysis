from src.emissions.spb_component_holdout import gate_decision


def test_nonidentifiable_emissions_fail_otherwise_passing_gate() -> None:
    result = gate_decision(
        official_stationary_hours=1000.0,
        official_berth_share=0.60,
        ais_stationary_hours=950.0,
        ais_resolved_berth_share=0.65,
        monthly_coverage_min=1.0,
        unresolved_share=0.05,
        represented_classes=7,
        source_integrity_pass=True,
        emissions_identifiable=False,
    )
    assert result["conditions"]["stationary_freight_hours_abs_error_lte_10pct"] is True
    assert result["conditions"]["stationary_freight_co2e_abs_error_lte_20pct"] is False
    assert result["conditions"]["class_stationary_emissions_spearman_gte_0_80"] is False
    assert result["overall_pass"] is False


def test_activity_subgates_use_absolute_registered_thresholds() -> None:
    result = gate_decision(
        official_stationary_hours=1000.0,
        official_berth_share=0.50,
        ais_stationary_hours=1101.0,
        ais_resolved_berth_share=0.601,
        monthly_coverage_min=0.949,
        unresolved_share=0.101,
        represented_classes=4,
        source_integrity_pass=True,
        emissions_identifiable=False,
    )
    assert result["conditions"]["stationary_freight_hours_abs_error_lte_10pct"] is False
    assert result["conditions"]["resolved_berth_share_abs_error_lte_10pp"] is False
    assert result["conditions"]["monthly_source_date_coverage_gte_95pct"] is False
    assert result["conditions"]["ais_gap_unresolved_share_lte_10pct"] is False
    assert result["conditions"]["at_least_five_official_freight_classes"] is False
