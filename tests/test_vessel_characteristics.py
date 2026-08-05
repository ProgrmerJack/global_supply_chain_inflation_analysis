"""Vessel-characteristics recovery (build_vessel_characteristics.py) — per-MMSI aggregation + date sampling."""

import os
import sys
from datetime import date

import pandas as pd
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def _write_sample(sample_dir, rows):
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["_y"] = df.timestamp.dt.strftime("%Y")
    df["_m"] = df.timestamp.dt.strftime("%m")
    for (y, m), part in df.groupby(["_y", "_m"]):
        out = sample_dir / f"year={y}" / f"month={m}"
        out.mkdir(parents=True, exist_ok=True)
        part.drop(columns=["_y", "_m"]).to_parquet(out / f"pings_{y}-{m}.parquet", index=False)


def test_sample_static_dates_one_varied_day_per_month():
    from process_ais.build_vessel_characteristics import sample_static_dates

    dates = sample_static_dates([2015, 2016])
    assert len(dates) == 24                                   # one per month, 2 years
    assert all(isinstance(d, date) for d in dates)
    assert len({(d.year, d.month) for d in dates}) == 24      # exactly one per (year, month)
    assert len({d.day for d in dates}) > 3                    # varied days-of-month (not all day 1)


def test_build_characteristics_table(tmp_path):
    from process_ais.build_vessel_characteristics import build_characteristics_table

    rows = [
        # MMSI 111: cargo, size ~constant (one bad 0 length ignored), draft median of [10,12]=11
        {"mmsi": 111, "timestamp": "2016-03-08T00:00:00Z", "length": 200.0, "width": 30.0, "draft": 10.0, "imo": 9111111, "vessel_type": 70.0},
        {"mmsi": 111, "timestamp": "2016-04-08T00:00:00Z", "length": 200.0, "width": 30.0, "draft": 12.0, "imo": 9111111, "vessel_type": 70.0},
        {"mmsi": 111, "timestamp": "2017-05-08T00:00:00Z", "length": 0.0,   "width": 30.0, "draft": 11.0, "imo": 9111111, "vessel_type": 70.0},
        # MMSI 222: tanker, no IMO (0 -> filtered to null)
        {"mmsi": 222, "timestamp": "2016-03-08T00:00:00Z", "length": 150.0, "width": 25.0, "draft": 8.0, "imo": 0, "vessel_type": 80.0},
    ]
    _write_sample(tmp_path, rows)
    t = build_characteristics_table(tmp_path, tmp_path / "vessel_characteristics.csv").set_index("mmsi")

    assert t.loc[111, "length_m"] == pytest.approx(200.0)     # the 0 is excluded by the FILTER
    assert t.loc[111, "draft_m"] == pytest.approx(11.0)       # median of [10, 12, 11]
    assert int(t.loc[111, "vessel_type"]) == 70
    assert int(t.loc[111, "imo"]) == 9111111
    assert t.loc[111, "first_year"] == "2016" and t.loc[111, "last_year"] == "2017"
    assert t.loc[222, "length_m"] == pytest.approx(150.0)
    assert pd.isna(t.loc[222, "imo"])                          # imo 0 -> filtered -> null


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
