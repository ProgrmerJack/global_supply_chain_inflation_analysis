"""
Unit tests for the AIS extraction + dwell pipeline, using small synthetic files.
Run:  .venv/Scripts/python.exe test_extract/test_extraction_layer.py
"""

import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from process_ais.extract_port_observations import extract_file, extract_from_dataframe
from process_ais.compute_dwell_metrics import process_port_observations


def _camelcase_frame() -> pd.DataFrame:
    # LA box ~ (33.65-33.85, -118.30 to -118.10); Houston ~ (29.65-29.85, -95.05..-94.85)
    rows = [
        # cargo in LA, two pings 6h apart -> kept, Cargo, dwell 0.25 day
        dict(MMSI=111, BaseDateTime="2020-03-01T00:00:00", LAT=33.74, LON=-118.20, SOG=0.0, VesselName="A", VesselType=70, Length=300, Width=40, Draft=12, Cargo=70),
        dict(MMSI=111, BaseDateTime="2020-03-01T06:00:00", LAT=33.75, LON=-118.21, SOG=0.1, VesselName="A", VesselType=70, Length=300, Width=40, Draft=12, Cargo=70),
        # tanker in Houston -> kept, Tanker
        dict(MMSI=222, BaseDateTime="2020-03-01T01:00:00", LAT=29.75, LON=-94.95, SOG=1.0, VesselName="B", VesselType=84, Length=200, Width=30, Draft=10, Cargo=84),
        # passenger (type 60) in LA box -> dropped (type filter)
        dict(MMSI=333, BaseDateTime="2020-03-01T02:00:00", LAT=33.74, LON=-118.20, SOG=5.0, VesselName="C", VesselType=60, Length=100, Width=20, Draft=5, Cargo=60),
        # cargo OUTSIDE all boxes -> dropped (port filter)
        dict(MMSI=444, BaseDateTime="2020-03-01T03:00:00", LAT=10.0, LON=-50.0, SOG=12.0, VesselName="D", VesselType=71, Length=250, Width=35, Draft=11, Cargo=71),
    ]
    return pd.DataFrame(rows)


def _snakecase_frame() -> pd.DataFrame:
    # 2025-style snake_case, cargo in NY/NJ box (40.60-40.75, -74.10..-73.95)
    rows = [
        dict(mmsi=555, base_datetime="2025-01-03T00:00:00", lat=40.68, lon=-74.02, sog=0.0, vessel_name="E", vessel_type=74, length=280, width=38, draft=12, cargo=74),
        dict(mmsi=555, base_datetime="2025-01-03T12:00:00", lat=40.69, lon=-74.03, sog=0.0, vessel_name="E", vessel_type=74, length=280, width=38, draft=12, cargo=74),
    ]
    return pd.DataFrame(rows)


def test_camelcase_filtering():
    obs = extract_from_dataframe(_camelcase_frame())
    assert set(obs["MMSI"]) == {111, 222}, f"unexpected MMSIs kept: {set(obs['MMSI'])}"
    la = obs[obs["MMSI"] == 111]
    assert (la["Port"] == "LA_Long_Beach").all()
    assert (la["VesselCategory"] == "Cargo").all()
    assert (obs[obs["MMSI"] == 222]["VesselCategory"] == "Tanker").all()
    assert list(obs.columns) == [
        "MMSI", "BaseDateTime", "Date", "LAT", "LON", "SOG",
        "VesselName", "VesselType", "VesselCategory", "Port", "Length", "Width", "Draft", "Cargo",
    ]
    print("  [ok] camelcase: type+port filters and schema correct")


def test_snakecase_normalization():
    obs = extract_from_dataframe(_snakecase_frame())
    assert set(obs["MMSI"]) == {555}
    assert (obs["Port"] == "NY_NJ").all()
    assert (obs["VesselCategory"] == "Cargo").all()
    print("  [ok] snakecase: 2025 schema normalized and filtered")


def test_file_roundtrip_and_dwell():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "AIS_2020_03_01.csv")
        _camelcase_frame().to_csv(p, index=False)
        obs = extract_file(p, chunksize=2)  # tiny chunksize exercises chunk concat
    assert set(obs["MMSI"]) == {111, 222}

    dwell, monthly = process_port_observations(obs)
    la = dwell[(dwell["MMSI"] == 111) & (dwell["Port"] == "LA_Long_Beach")].iloc[0]
    assert abs(la["DwellDays"] - 0.25) < 1e-9, f"LA dwell wrong: {la['DwellDays']}"
    la_m = monthly[(monthly["Port"] == "LA_Long_Beach") & (monthly["YearMonth"] == "2020-03")].iloc[0]
    assert la_m["UniqueVessels"] == 1
    assert abs(la_m["MeanDwellDays"] - 0.25) < 1e-9
    print("  [ok] file roundtrip + dwell: 6h LA stay -> 0.25 day, monthly aggregation correct")


if __name__ == "__main__":
    print("Testing AIS extraction + dwell pipeline:")
    test_camelcase_filtering()
    test_snakecase_normalization()
    test_file_roundtrip_and_dwell()
    print("ALL TESTS PASSED")
