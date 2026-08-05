from src.acquire.ab617_observations import parse_options
from src.acquire.ab617_metadata import assess_aqview_history
from src.acquire.nature_recovery_metadata import summarize_sources
from src.acquire.aqview_history import parse_download_filename, query_headers


def test_parse_options_is_effect_blind_and_deduplicates() -> None:
    html = b"""
    <button class="average-chart" data-parameter-id="12" data-duration-id="3"
            data-parameter-name="NO2">plot</button>
    <button class="average-chart extra" data-parameter-id="12" data-duration-id="3"
            data-parameter-name="NO2">plot again</button>
    <button class="average-chart" data-parameter-id="8" data-duration-id="1"
            data-parameter-name="Black Carbon">plot</button>
    <div data-average-values="999,1000"></div>
    """
    assert parse_options(html) == [
        {"parameter-id": "12", "duration-id": "3", "parameter-name": "NO2"},
        {"parameter-id": "8", "duration-id": "1", "parameter-name": "Black Carbon"},
    ]


def test_parse_options_ignores_current_values_without_request_metadata() -> None:
    assert parse_options(b'<div data-average-values="1,2,3"></div>') == []


def test_aqview_history_distinguishes_historical_metadata_from_latest_chart() -> None:
    communities = [{
        "CommunityId": 9,
        "CommunityNameShort": "Wilmington, West Long Beach, Carson",
    }]
    parameters = [
        {"ParameterType": "Nitrogen Dioxide (NO2)"},
        {"ParameterType": "Black Carbon (BC)"},
        {"ParameterType": "PM2.5"},
    ]
    availability = [
        {
            "parameter": "Nitrogen Dioxide (NO2)",
            "earliest": "September-2019",
            "latest": "July-2026",
            "hourly_records": 35_085,
        }
    ]
    inventory = [{
        "AB 617 Community": "Wilmington, West Long Beach, Carson",
        "Site": "West 710",
        "Parameter Type": "Nitrogen Dioxide (NO2)",
    }]

    decision = assess_aqview_history(communities, parameters, availability, inventory)

    assert decision["historical_window_feasible"] is True
    assert decision["no2_hourly_records_in_window"] == 35_085
    assert "does not retrieve" in decision["scope"]


def test_recovery_metadata_keeps_tempo_pixels_and_ogv_workbook_closed() -> None:
    service = {
        "name": "TEMPO_NO2_L3",
        "timeInfo": {"timeExtent": [1, 2]},
        "pixelSizeX": 0.02,
        "pixelSizeY": 0.02,
        "bandCount": 1,
    }
    html = (
        '<a href="/sites/default/files/2025-04/'
        'Final_OGV2025_Emissions_Inventory.xlsx">workbook</a>'
    )

    summary = summarize_sources(service, service, html)

    assert summary["carb_ogv2025"]["workbook_declared"] is True
    assert summary["carb_ogv2025"]["workbook_opened"] is False
    assert "No TEMPO pixel" in summary["outcome_firewall"]


def test_aqview_history_request_matches_the_public_download_contract() -> None:
    headers = query_headers(
        "Nitrogen Dioxide (NO2)",
        start_date="2019-09-01",
        end_date="2025-12-31",
        subhourly_count=0,
        hourly_count=42,
    )

    assert headers["id"] == "9"
    assert headers["geo"] == "Community"
    assert headers["parameter"] == "Nitrogen Dioxide (NO2)"
    assert headers["subhourlycount"] == "0"
    assert headers["hourlycount"] == "42"


def test_aqview_history_filename_parser_rejects_path_traversal() -> None:
    assert parse_download_filename({"FileName": "aqview_export.zip"}) == "aqview_export.zip"

    import pytest

    with pytest.raises(ValueError, match="unsafe"):
        parse_download_filename("../private.csv")
