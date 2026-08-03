"""National AIS activity-panel builder + resumable ingestion ledger (build_national_panel.py).

Exercises the outcome-blind monthly-activity aggregation and the resumable date planning on synthetic
retained pings. Network download and live NOAA ingestion are not exercised here.
"""

import os
import sys
from datetime import date

import pandas as pd
import pytest
import geopandas as gpd
from shapely.geometry import box

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def _write_pings(pings_dir, rows):
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["ts"], utc=True)   # real pings store timestamp[ns, UTC], not strings
    df["_y"] = df.timestamp.dt.strftime("%Y")
    df["_m"] = df.timestamp.dt.strftime("%m")
    for (year, month), part in df.groupby(["_y", "_m"]):
        out = pings_dir / f"year={year}" / f"month={month}"
        out.mkdir(parents=True, exist_ok=True)
        part.drop(columns=["ts", "_y", "_m"]).to_parquet(out / f"pings_{year}-{month}.parquet", index=False)


def test_build_activity_panel(tmp_path):
    from process_ais.build_national_panel import build_activity_panel

    rows = [
        # san_pedro_bay, 2021-01: cargo vessel 111 spans 12h; tanker vessel 222 single ping -> 2 vessels, 1 cargo
        {"mmsi": 111, "ts": "2021-01-05T00:00:00Z", "port_complex_id": "san_pedro_bay", "vessel_type": 70.0},
        {"mmsi": 111, "ts": "2021-01-05T12:00:00Z", "port_complex_id": "san_pedro_bay", "vessel_type": 70.0},
        {"mmsi": 222, "ts": "2021-01-06T03:00:00Z", "port_complex_id": "san_pedro_bay", "vessel_type": 84.0},
        # houston_tx, 2021-02: one cargo vessel, one ping
        {"mmsi": 333, "ts": "2021-02-10T00:00:00Z", "port_complex_id": "houston_tx", "vessel_type": 71.0},
    ]
    _write_pings(tmp_path, rows)
    panel = build_activity_panel(tmp_path, tmp_path / "panel.csv").set_index(["port_complex_id", "year_month"])

    spb = panel.loc[("san_pedro_bay", "2021-01")]
    assert spb.unique_vessels == 2 and spb.n_pings == 3 and spb.days_sampled == 2
    assert spb.unique_cargo_vessels == 1  # only vessel 111 (type 70) is cargo; 222 (type 84) is a tanker
    assert spb.ship_days == pytest.approx(0.5, abs=1e-6)  # only vessel 111 has a span
    hou = panel.loc[("houston_tx", "2021-02")]
    assert hou.unique_vessels == 1 and hou.ship_days == pytest.approx(0.0)
    assert (tmp_path / "panel.csv").exists()


def test_build_activity_panel_counts_calls_across_month_boundaries(tmp_path):
    """Calls use the registered 24-hour absence rule and belong to their start month."""
    from process_ais.build_national_panel import build_activity_panel

    rows = [
        # A cargo call starts in January and remains one call across the month boundary.
        {"mmsi": 111, "ts": "2021-01-31T20:00:00Z", "port_complex_id": "san_pedro_bay", "vessel_type": 70.0},
        {"mmsi": 111, "ts": "2021-02-01T02:00:00Z", "port_complex_id": "san_pedro_bay", "vessel_type": 70.0},
        # A later absence over 24 hours creates a new February cargo call.
        {"mmsi": 111, "ts": "2021-02-03T04:01:00Z", "port_complex_id": "san_pedro_bay", "vessel_type": 70.0},
        # A tanker call is freight but not cargo.
        {"mmsi": 222, "ts": "2021-01-15T00:00:00Z", "port_complex_id": "san_pedro_bay", "vessel_type": 84.0},
    ]
    _write_pings(tmp_path, rows)

    panel = build_activity_panel(tmp_path, tmp_path / "panel.csv").set_index(["port_complex_id", "year_month"])

    january = panel.loc[("san_pedro_bay", "2021-01")]
    february = panel.loc[("san_pedro_bay", "2021-02")]
    assert january.port_calls == 2
    assert january.cargo_port_calls == 1
    assert january.freight_port_calls == 2
    assert february.port_calls == 1
    assert february.cargo_port_calls == 1
    assert february.freight_port_calls == 1


def test_build_activity_panel_streams_call_detection_in_bounded_file_batches(tmp_path, monkeypatch):
    """The call pass must avoid a global census sort while amortising one-file read overhead."""
    import process_ais.build_national_panel as national_panel

    first = tmp_path / "year=2021" / "month=01" / "pings_2021-01-01.parquet"
    second = tmp_path / "year=2021" / "month=01" / "pings_2021-01-02.parquet"
    first.parent.mkdir(parents=True)
    for path, timestamp in ((first, "2021-01-01T00:00:00Z"), (second, "2021-01-02T00:00:00Z")):
        pd.DataFrame(
            {"mmsi": [111], "timestamp": pd.to_datetime([timestamp], utc=True),
             "port_complex_id": ["san_pedro_bay"], "vessel_type": [70.0]}
        ).to_parquet(path, index=False)

    requested = []
    original_dataset = national_panel.ds.dataset

    def traced_dataset(paths, *args, **kwargs):
        requested.append([str(path) for path in paths])
        assert len(paths) <= national_panel.PORT_CALL_FILES_PER_BATCH
        return original_dataset(paths, *args, **kwargs)

    monkeypatch.setattr(national_panel.ds, "dataset", traced_dataset)
    national_panel.build_activity_panel(tmp_path, tmp_path / "panel.csv")

    assert requested == [[str(first), str(second)]]


def test_pending_dates_skips_done_and_samples():
    from process_ais.build_national_panel import pending_dates

    done = {"2021-01-15"}  # one already-done date should be excluded
    dates = pending_dates([2021], [1], days_per_month=8, done=done)
    assert all(isinstance(d, date) for d in dates)
    assert all(d.year == 2021 and d.month == 1 for d in dates)
    assert date(2021, 1, 15) not in dates
    assert 1 <= len(dates) <= 8


def test_load_done_reads_ok_and_missing(tmp_path):
    from process_ais.build_national_panel import load_done

    m = tmp_path / "ingestion_manifest.csv"
    pd.DataFrame(
        {"date": ["2021-01-01", "2021-01-02", "2021-01-03"], "status": ["ok", "missing", "error"]}
    ).to_csv(m, index=False)
    done = load_done(m)
    assert done == {"2021-01-01", "2021-01-02"}  # error dates are retried, not treated as done


def test_ingest_date_recovers_artifact_written_before_manifest_append(tmp_path, monkeypatch):
    import process_ais.build_national_panel as national_panel

    target = date(2022, 8, 17)
    url = national_panel.url_for(target.year, target.month, target.day)
    out = tmp_path / "year=2022" / "month=08" / "pings_2022-08-17.parquet"
    out.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2022-08-17T00:00:00Z"], utc=True),
            "port_complex_id": ["san_pedro_bay"],
            "source_file": [url.rsplit("/", 1)[-1]],
        }
    ).to_parquet(out, index=False)
    monkeypatch.setattr(national_panel, "download", lambda *_: pytest.fail("must not redownload"))

    row = national_panel.ingest_date(
        target, tmp_path, port_areas=None, assignment_coverage=None,
    )

    assert row["status"] == "ok" and row["retained_pings"] == 1
    assert row["error"].startswith("recovered existing immutable artifact")


def test_ingestion_selects_only_outer_rows_from_nested_coastal_domains(tmp_path):
    from process_ais.build_national_panel import load_ingestion_port_areas

    path = tmp_path / "domains.geojson"
    gpd.GeoDataFrame(
        {
            "port_complex_id": ["alpha", "alpha"],
            "domain": ["coastal_inner", "coastal_outer"],
        },
        geometry=[box(0, 0, 1, 1), box(-1, -1, 2, 2)],
        crs="EPSG:4326",
    ).to_file(path, driver="GeoJSON")

    areas = load_ingestion_port_areas(path)

    assert areas.domain.tolist() == ["coastal_outer"]
    assert areas.geometry.iloc[0].area == pytest.approx(9.0)


if __name__ == "__main__":
    import pytest as _p

    raise SystemExit(_p.main([__file__, "-q"]))
