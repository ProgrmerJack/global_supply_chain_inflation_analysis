from src.emissions.spb_freight_boundary import parse_summary_page


def test_parse_summary_reproduces_all_pollutant_totals_and_uses_units() -> None:
    text = """Table 8.1: 2024 Emissions by Source Category
Ocean-going vessels 1 2 3 4 5 6 7 8
Harbor craft 2 3 4 5 6 7 8 9
Cargo handling equipment 3 4 5 6 7 8 9 10
Locomotives 4 5 6 7 8 9 10 11
Heavy-duty vehicles 5 6 7 8 9 10 11 12
Total 15 20 25 30 35 40 45 50
"""
    rows, checks = parse_summary_page(
        text, port="POLA", year=2024, page=9, source_file="source.pdf", source_sha256="abc"
    )
    assert len(rows) == 40
    assert len(checks) == 8
    assert checks["pass"].all()
    assert checks.loc[checks.pollutant.eq("CO2e"), "reported_unit"].item() == "metric_tonnes"
    assert checks.loc[checks.pollutant.eq("NOx"), "reported_unit"].item() == "short_tons"


def test_parse_summary_uses_first_table_when_percent_table_repeats_categories() -> None:
    text = """Table 7.1: 2024 Emissions by Source Category
Table 7.2: 2024 Emissions Percent Contributions by Source Category
Ocean going vessels 1 1 1 1 1 1 1 1
Harbor craft 1 1 1 1 1 1 1 1
Cargo handling equipment 1 1 1 1 1 1 1 1
Locomotives 1 1 1 1 1 1 1 1
Heavy-duty vehicles 1 1 1 1 1 1 1 1
Total 5 5 5 5 5 5 5 5
Ocean going vessels 99 99 99 99 99 99 99 99
"""
    rows, _ = parse_summary_page(
        text, port="POLB", year=2024, page=10, source_file="source.pdf", source_sha256="abc"
    )
    assert rows["reported_quantity"].max() == 1
