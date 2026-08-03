from pathlib import Path

import pytest

from src.emissions.spb_component_validation import (
    _published_total_check,
    _table,
    extract_report,
)


def test_development_extractor_refuses_protected_2018_before_reading() -> None:
    protected = Path("pola_2018_air_emissions_inventory.pdf")
    with pytest.raises(RuntimeError, match="refuses protected"):
        extract_report(protected)


def test_type_emissions_table_survives_reordered_pdf_text() -> None:
    page = """Table 2.5: 2022 Ocean-going Vessel Emissions by Vessel Type
Table 2.6: 2022 Ocean-going Vessel Emissions by Mode
Auto Carrier 1 1 1 1 1 1 1 1
Bulk 2 2 2 2 2 2 2 2
General Cargo 3 3 3 3 3 3 3 3
RoRo 4 4 4 4 4 4 4 4
Tanker 5 5 5 5 5 5 5 5
Total 15 15 15 15 15 15 15 15
Mode Engine Type PM10 PM2.5 DPM NOx SOx CO HC CO2e
Total 99 99 99 99 99 99 99 99
"""
    text, page_number = _table([page], "type_emissions")
    assert page_number == 1
    assert "Auto Carrier" in text


def test_published_total_check_delimits_following_table_and_reproduces_grand_total() -> None:
    text = """Table 2.4: 2021 Ocean-going Vessel Emissions by Vessel Type
Auto Carrier 1 2 3 4 5 6 7 8
Ocean Tugboat (ATB/ITB) 2 3 4 5 6 7 8 9
Bulk 3 4 5 6 7 8 9 10
General Cargo 4 5 6 7 8 9 10 11
RoRo 5 6 7 8 9 10 11 12
Total 15 20 25 30 35 40 45 50
Additional loitering/anchorage 1 1 1 1 1 1 1 1
Total 16 21 26 31 36 41 46 51
Table 2.5: 2021 Ocean-going Vessel Emissions by Emissions Source
Engine Type PM10 PM2.5 DPM NOx SOx CO HC CO2e
Total 999 999 999 999 999 999 999 999
"""
    checks = _published_total_check(text, page=4)
    assert len(checks) == 16
    assert all(check["pass"] for check in checks)
    assert {check["component"] for check in checks} == {
        "class_rows",
        "grand_total_with_unallocated_anchorage",
    }
