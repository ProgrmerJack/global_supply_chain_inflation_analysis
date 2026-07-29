"""
Stage 1 of the Paper A macro chain: build the monthly macro panel from `data/raw/`.

    data/raw/{cpi_us,cpi_goods,cpi_services,indpro,oil_price}.csv   FRED monthly levels
    data/raw/gscpi_raw.xlsx                                          NY Fed GSCPI
        -> data/processed/analysis_dataset.csv

`build_dwell_index.py` (stage 2) merges the AIS dwell census onto this panel and writes
`data/processed/analysis_dataset_dwell.csv`, which every price and concentration guard reads.

HISTORY -- read before editing. The predecessor of this script
(`_archive/legacy_src/standardize/standardize_real.py`) looked for a sheet named "History",
wrapped the lookup in a bare `except:`, and, when that failed, SILENTLY SUBSTITUTED a seeded
AR(1) series with a hand-drawn Covid ramp for the GSCPI. The sheet is actually called
"GSCPI Monthly Data" and the workbook is a legacy OLE2 .xls despite its .xlsx name, so the
fallback fired every time and the fabricated series reached the shipped panel and the
manuscript. There is deliberately no fallback here: every loader raises. A missing or
unreadable input must stop the pipeline, never quietly become simulated data.

HISTORY (2026-08-05, second incident) -- the replacement written after the incident above
normalised dates with `+ pd.offsets.MonthBegin(0)`. The NY Fed workbook is MONTH-END dated
("31-Jan-1998"), and MonthBegin(0) ROLLS A MONTH-END DATE FORWARD, so every GSCPI observation
was relabelled one month late: the shipped panel satisfied gscpi[t] == GSCPI_true[t-1] for all
297 months. The integrity check added at the time guarded the series' MOMENTS (mean, sd) but
never its DATES, so it could not catch a shift. Dates are now normalised by truncation
(`.dt.to_period("M").dt.to_timestamp()`) through `_to_month_begin`, which asserts that no
observation changed calendar month. Never normalise a date column with an offset object here.

Run: python src/index/build_macro_panel.py
"""

from __future__ import annotations

import os

import pandas as pd

RAW = "data/raw"
OUT = "data/processed"
OUT_CSV = os.path.join(OUT, "analysis_dataset.csv")
GSCPI_XLS = os.path.join(RAW, "gscpi_raw.xlsx")
GSCPI_SHEET = "GSCPI Monthly Data"
SERIES = ["cpi_us", "cpi_goods", "cpi_services", "indpro", "oil_price"]


def _to_month_begin(raw: pd.Series, source: str) -> pd.Series:
    """Normalise a monthly date column to month-begin by TRUNCATING to the calendar month.

    Every monthly date column in this pipeline goes through here. Truncation is used rather
    than an offset because `+ pd.offsets.MonthBegin(0)` rolls a month-end date FORWARD into
    the next month — the bug described in the module docstring. The assertion below is the
    check that was missing: it fails if normalisation moved any observation into a different
    calendar month than the source recorded.
    """
    parsed = pd.to_datetime(raw)
    out = parsed.dt.to_period("M").dt.to_timestamp()
    moved = (out.dt.year != parsed.dt.year) | (out.dt.month != parsed.dt.month)
    if moved.any():
        i = moved.idxmax()
        raise ValueError(
            f"{source}: month-begin normalisation moved {moved.sum()} date(s) into a different "
            f"calendar month (first: {parsed[i].date()} -> {out[i].date()}). The source dates are "
            "not being read as calendar months; do not proceed — the series would be mislabelled."
        )
    return out


def load_fred(name: str) -> pd.DataFrame:
    """One FRED monthly series, normalised to month-begin dates. Missing file is fatal."""
    path = os.path.join(RAW, f"{name}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found — the macro panel cannot be built without it.")
    df = pd.read_csv(path, parse_dates=["date"])
    value_cols = [c for c in df.columns if c != "date"]
    if len(value_cols) != 1:
        raise ValueError(f"{path}: expected one value column, found {value_cols}")
    df = df.rename(columns={value_cols[0]: name})[["date", name]]
    df["date"] = _to_month_begin(df["date"], path)
    return df


def load_gscpi() -> pd.DataFrame:
    """The real NY Fed GSCPI. Any read failure raises — see the HISTORY note above."""
    if not os.path.exists(GSCPI_XLS):
        raise FileNotFoundError(f"{GSCPI_XLS} not found — refusing to build a panel without the GSCPI.")
    # The published workbook is a legacy OLE2 .xls carrying an .xlsx extension, so openpyxl
    # cannot open it and the engine must be named explicitly.
    df = pd.read_excel(GSCPI_XLS, sheet_name=GSCPI_SHEET, engine="xlrd")
    date_col = next((c for c in df.columns if "date" in str(c).lower()), None)
    gscpi_col = next((c for c in df.columns if "gscpi" in str(c).lower()), None)
    if date_col is None or gscpi_col is None:
        raise ValueError(f"{GSCPI_XLS}!{GSCPI_SHEET}: no Date/GSCPI columns in {list(df.columns)}")
    out = df[[date_col, gscpi_col]].dropna()
    out.columns = ["date", "gscpi"]
    out["date"] = _to_month_begin(out["date"], f"{GSCPI_XLS}!{GSCPI_SHEET}")
    # The GSCPI is published as a standardised index; a series that is not roughly mean-zero,
    # unit-variance is not the GSCPI and must not pass silently.
    if not (abs(out.gscpi.mean()) < 0.5 and 0.5 < out.gscpi.std() < 2.0):
        raise ValueError(f"{GSCPI_XLS}: gscpi mean={out.gscpi.mean():.3f} sd={out.gscpi.std():.3f} "
                         "is not a standardised index — check the source file.")
    out = out.sort_values("date").reset_index(drop=True)
    # A moments check cannot detect a shifted calendar, so also require the series to be a
    # contiguous monthly grid — this catches duplicated and missing months in one comparison.
    expected = pd.date_range(out["date"].iloc[0], out["date"].iloc[-1], freq="MS")
    if len(expected) != len(out) or not (out["date"].values == expected.values).all():
        missing = sorted(set(expected) - set(out["date"]))[:5]
        raise ValueError(f"{GSCPI_XLS}: GSCPI months are not a contiguous monthly grid "
                         f"({len(out)} rows vs {len(expected)} expected; e.g. missing {missing}).")
    return out


def build() -> pd.DataFrame:
    df = load_fred("cpi_us")
    for name in SERIES[1:]:
        df = df.merge(load_fred(name), on="date", how="left")
    df = df.merge(load_gscpi(), on="date", how="left")

    # year-on-year percentage change; the two shortened names are the ones downstream code expects
    for col, stem in [("cpi_us", "cpi"), ("cpi_goods", "cpi_goods"), ("cpi_services", "cpi_services"),
                      ("indpro", "indpro"), ("oil_price", "oil")]:
        # fill_method=None: a gap stays a gap rather than being padded into a fabricated change
        df[f"{stem}_yoy"] = df[col].pct_change(12, fill_method=None) * 100

    df = df.dropna(subset=["gscpi", "cpi_yoy"]).reset_index(drop=True)
    return df


def main() -> None:
    df = build()
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"wrote {OUT_CSV}  rows={len(df)}  {df.date.min():%Y-%m}..{df.date.max():%Y-%m}")
    print(f"  GSCPI: mean={df.gscpi.mean():+.3f} sd={df.gscpi.std():.3f} "
          f"(real NY Fed series from '{GSCPI_SHEET}')")


if __name__ == "__main__":
    main()
