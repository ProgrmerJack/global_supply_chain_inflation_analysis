"""Macro-panel date alignment (src/index/build_macro_panel.py).

These tests exist because of a specific defect. The NY Fed GSCPI workbook is MONTH-END dated
("31-Jan-1998"), and the builder normalised it with `+ pd.offsets.MonthBegin(0)`, which rolls a
month-end date FORWARD to the first of the NEXT month. Every GSCPI observation was therefore
relabelled one month late — the shipped panel satisfied `gscpi[t] == GSCPI_true[t-1]` for all
297 months — and Paper A's concentration results were computed against the wrong month.

Nothing caught it: the builder's integrity check guarded the series' moments (mean, sd), which a
one-month shift leaves untouched, and no test covered this module at all. The end-to-end test
below is the check that was missing.
"""

import importlib.util
import os

import pandas as pd
import pytest

REPO = os.path.join(os.path.dirname(__file__), "..")
_SRC = os.path.join(REPO, "src", "index", "build_macro_panel.py")

_spec = importlib.util.spec_from_file_location("build_macro_panel", _SRC)
build_macro_panel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_macro_panel)


def test_month_end_dates_are_truncated_not_rolled_forward():
    """The exact historical bug, pinned as a unit test."""
    month_end = pd.Series(pd.to_datetime(["1998-01-31", "1998-02-28", "2020-12-31"]))

    got = build_macro_panel._to_month_begin(month_end, "unit-test")

    assert list(got.dt.strftime("%Y-%m-%d")) == ["1998-01-01", "1998-02-01", "2020-12-01"]
    # ...and the idiom that caused the incident does something different. If this ever stops
    # differing, pandas has changed MonthBegin semantics and the guard needs rereading.
    rolled_forward = month_end + pd.offsets.MonthBegin(0)
    assert list(rolled_forward.dt.strftime("%Y-%m-%d")) == ["1998-02-01", "1998-03-01", "2021-01-01"]


def test_month_begin_dates_are_left_alone():
    """FRED CSVs already arrive month-begin; normalisation must be a no-op for them."""
    month_begin = pd.Series(pd.to_datetime(["2009-01-01", "2015-06-01"]))
    got = build_macro_panel._to_month_begin(month_begin, "unit-test")
    assert got.equals(month_begin)


def test_normalisation_never_changes_calendar_month():
    """Property check across a long month-end grid: year-month must survive normalisation."""
    dates = pd.Series(pd.date_range("1998-01-31", "2025-12-31", freq="ME"))
    got = build_macro_panel._to_month_begin(dates, "unit-test")
    assert (got.dt.year == dates.dt.year).all()
    assert (got.dt.month == dates.dt.month).all()
    assert (got.dt.day == 1).all()


@pytest.mark.skipif(
    not os.path.exists(os.path.join(REPO, "data", "raw", "gscpi_raw.xlsx"))
    or not os.path.exists(os.path.join(REPO, "data", "processed", "analysis_dataset.csv")),
    reason="requires the raw GSCPI workbook and a built panel",
)
def test_shipped_panel_gscpi_matches_the_source_workbook_month_for_month():
    """End-to-end: the shipped panel's GSCPI must equal the NY Fed value for the SAME month.

    This is the test whose absence let a one-month shift reach the manuscript. It deliberately
    re-reads the source workbook rather than trusting any intermediate artifact.
    """
    raw = pd.read_excel(
        os.path.join(REPO, "data", "raw", "gscpi_raw.xlsx"),
        sheet_name="GSCPI Monthly Data",
        engine="xlrd",
    )
    date_col = next(c for c in raw.columns if "date" in str(c).lower())
    gscpi_col = next(c for c in raw.columns if "gscpi" in str(c).lower())
    truth = raw[[date_col, gscpi_col]].dropna()
    truth.columns = ["date", "gscpi_true"]
    # normalise independently of the builder, so a bug in the builder cannot hide itself
    truth["date"] = pd.to_datetime(truth["date"]).dt.to_period("M").dt.to_timestamp()

    panel = pd.read_csv(
        os.path.join(REPO, "data", "processed", "analysis_dataset.csv"), parse_dates=["date"]
    )
    merged = panel[["date", "gscpi"]].dropna().merge(truth, on="date", how="inner")

    assert len(merged) > 200, f"expected a long overlap, got {len(merged)} months"
    assert (merged.gscpi - merged.gscpi_true).abs().max() < 1e-9

    # Explicitly rule out the failure mode: a one-month shift in EITHER direction must not match.
    for lag in (-1, 1):
        shifted = truth.copy()
        shifted["date"] = shifted["date"] + pd.DateOffset(months=lag)
        m = panel[["date", "gscpi"]].dropna().merge(shifted, on="date", how="inner")
        assert (m.gscpi - m.gscpi_true).abs().max() > 1e-6, (
            f"panel GSCPI also matches the source shifted by {lag:+d} month(s) — "
            "the series is not uniquely aligned"
        )
