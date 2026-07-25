"""Ingest official monthly container throughput from the BTS Port Performance Freight Statistics Program.

The US DOT Bureau of Transportation Statistics publishes the Port Performance Freight Statistics Program on
`data.bts.gov` via the Socrata SODA API (official, machine-readable, no anti-bot). Dataset **rd72-aq8r
"Monthly TEU Data"** gives monthly TEU by US container gateway (Los Angeles, Long Beach, NY/NJ, Virginia,
Houston, Charleston, Savannah, Oakland, NWSA) for **2019-01 … 2022-10** — which spans the November-2021
queue-reform episode (plan.md H1). It is the official federal compilation of the port-authority TEU named in
`config/registries/g1v2_comparator_registry.csv`, retrievable from one reproducible API.

This turns the G1-v2 official-comparator coverage from 0 → the 6 registry gateways BTS covers. For
savannah_ga / houston_tx / charleston_sc, TEU is the registry PRIMARY comparator, so those are fully
populated; for san_pedro_bay (= LA+LB), new_york_new_jersey and norfolk_newport_news_va it populates the
SECONDARY (TEU) row and the PRIMARY (container-vessel calls) remains to be acquired.

CONFIRMATORY INTEGRITY: opening/ingesting official INPUTS is allowed AFTER the 2026-07-15 freeze; the G1-v2
pass/fail comparison is still run only ONCE, later, when coverage is adequate. The frozen comparator registry
and freeze receipt are NOT edited — provenance (source + access date + SHA-256) is recorded by
`teu_throughput.ingest_official_series` in `data/external/g1v2_official/ingestion_manifest.csv`.

Run: python src/process_ais/ingest_bts_official.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

try:
    from teu_throughput import ingest_official_series, load_comparator_registry, assemble_official
except ImportError:  # pragma: no cover - path shim mirrors the rest of the pipeline
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from teu_throughput import ingest_official_series, load_comparator_registry, assemble_official

BTS_HOST = "data.bts.gov"
BTS_SOURCE = ("BTS Port Performance Freight Statistics Program (data.bts.gov Socrata rd72-aq8r 'Monthly TEU "
              "Data' 2019-01..2022-10 + iahn-a7j4 'TEU Handled by Select U.S. Container Ports' 2020-01..2023-08); "
              "official US DOT compilation of port-authority monthly TEU")

# Two BTS Monthly-TEU tables use different column names; each maps registry complex_id -> columns to sum.
# The date column also differs ('port' vs 'unnamed_column'), detected in fetch.
BTS_TEU_DATASETS = [
    ("rd72-aq8r", {
        "san_pedro_bay": ["los_angeles_ca", "long_beach_ca"], "new_york_new_jersey": ["port_of_ny_nj"],
        "norfolk_newport_news_va": ["port_of_virginia_va"], "houston_tx": ["houston_tx"],
        "charleston_sc": ["charleston_sc"], "savannah_ga": ["savannah_ga"]}),
    ("iahn-a7j4", {
        "san_pedro_bay": ["los_angeles", "long_beach"], "new_york_new_jersey": ["ny_nj"],
        "norfolk_newport_news_va": ["port_of_va"], "houston_tx": ["houston"],
        "charleston_sc": ["charleston"], "savannah_ga": ["savannah"]}),
]
COMPLEX_TO_BTS_TEU = BTS_TEU_DATASETS[0][1]      # kept for the mapping test
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0"}


def fetch_bts_teu(resource: str) -> pd.DataFrame:
    """Return a BTS Monthly-TEU table with a parsed 'year_month' column (date column auto-detected)."""
    url = f"https://{BTS_HOST}/resource/{resource}.json?$limit=50000"
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=90) as r:
        df = pd.DataFrame(json.load(r))
    date_col = "port" if "port" in df.columns else ("unnamed_column" if "unnamed_column" in df.columns
                                                    else df.columns[0])
    df["_dt"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_dt"]).sort_values("_dt")
    for c in df.columns:
        if c not in (date_col, "_dt"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["year_month"] = df["_dt"].dt.strftime("%Y-%m")
    return df


def complex_teu_series(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Sum the BTS port columns for one registry complex (e.g. san_pedro_bay = LA + Long Beach)."""
    return (pd.DataFrame({"year_month": df["year_month"], "value": df[cols].sum(axis=1, min_count=1)})
            .dropna(subset=["value"]).reset_index(drop=True))


def merged_teu_series(complex_id: str) -> pd.DataFrame:
    """Merge the BTS TEU datasets for one complex into 2019-01..2023-08 (assert they agree in overlap)."""
    parts = []
    for resource, cmap in BTS_TEU_DATASETS:
        cols = cmap.get(complex_id)
        if not cols:
            continue
        df = fetch_bts_teu(resource)
        if all(c in df.columns for c in cols):
            parts.append(complex_teu_series(df, cols).assign(_src=resource))
    if not parts:
        return pd.DataFrame(columns=["year_month", "value"])
    both = pd.concat(parts, ignore_index=True)
    # rd72 is the original single-vintage 'Monthly TEU Data' covering the full 2021 episode -> prefer it in
    # overlap; iahn (a later revision) only fills the 2022-11..2023-08 extension. Revisions differ a few %.
    prio = {"rd72-aq8r": 0, "iahn-a7j4": 1}
    both["_prio"] = both["_src"].map(prio).fillna(9)
    overlap = both.groupby("year_month")["value"].nunique()
    disagree = both.year_month.isin(overlap[overlap > 1].index)
    if disagree.any():
        w = both[disagree].pivot_table("value", "year_month", "_src")
        rel = ((w.max(axis=1) - w.min(axis=1)) / w.max(axis=1)).max()
        print(f"    ~ {complex_id}: BTS vintages differ up to {rel:.1%} in overlap; using rd72 vintage there")
    return (both.sort_values(["year_month", "_prio"]).drop_duplicates("year_month", keep="first")
            .drop(columns=["_src", "_prio"]).reset_index(drop=True))


def ingest(out_official_dir: Path | None = None) -> pd.DataFrame:
    access = date.today().isoformat()
    tmp = Path(__file__).resolve().parents[2] / "data/interim/bts_teu_staging"
    tmp.mkdir(parents=True, exist_ok=True)
    kwargs = {} if out_official_dir is None else {"official_dir": out_official_dir}
    for complex_id in COMPLEX_TO_BTS_TEU:
        series = merged_teu_series(complex_id)
        if not len(series):
            print(f"  ! {complex_id}: no BTS columns — skipped")
            continue
        raw = tmp / f"{complex_id}__container_teu_total__bts.csv"
        series.to_csv(raw, index=False, lineterminator="\n")
        dest = ingest_official_series(complex_id, "CONTAINER_TEU_TOTAL", raw,
                                      source=BTS_SOURCE, access_date=access, **kwargs)
        print(f"  + {complex_id}: {len(series)} months {series.year_month.min()}..{series.year_month.max()} "
              f"-> {dest.name}")

    registry = load_comparator_registry()
    _, cov = assemble_official(registry, **({} if out_official_dir is None else {"official_dir": out_official_dir}))
    n = int(cov["present"].sum())
    print(f"\nG1-v2 monthly-TEU coverage now: {n}/{len(cov)} registered series present")
    return cov


# --------------------------------------------------------------------------- annual container CALLS (primary)
BTS_PORTDATA_RESOURCE = "5rpz-kgm9"        # "Port Data" — annual, from USACE Waterborne Commerce
BTS_CALLS_SOURCE = ("BTS Port Performance Freight Statistics Program (data.bts.gov Socrata 5rpz-kgm9 "
                    "'Port Data'; source USACE Waterborne Commerce), cargo_type=VESSEL CALLS, "
                    "trade_type=Container: official ANNUAL container-vessel calls")
ANNUAL_OFFICIAL_DIR = ROOT / "data/external/g1v2_official_annual"

# 5rpz-kgm9 port_name -> registry complex_id (san_pedro_bay = Los Angeles + Long Beach). NOTE: 5rpz annual
# container *TEU* undercounts port-authority TEU ~34% (USACE definition) and is NOT ingested; only the
# annual *vessel calls* are taken here (the primary comparator, at the annual resolution A4 uses).
PORT_NAME_TO_COMPLEX = {
    "Los Angeles, CA Port of": "san_pedro_bay", "Long Beach, CA Port of": "san_pedro_bay",
    "New York, NY & NJ": "new_york_new_jersey", "Virginia, VA, Port of": "norfolk_newport_news_va",
    "Houston Port Authority, TX": "houston_tx", "Port of Charleston, SC": "charleston_sc",
    "Savannah, GA Port of": "savannah_ga", "Baltimore, MD": "baltimore_md",
    "Philadelphia Regional Port, PA": "philadelphia_pa", "Jacksonville, FL": "jacksonville_fl",
    "PortMiami, FL": "miami_fl", "Port Everglades, FL": "port_everglades_fl",
}


def fetch_bts_port_data() -> pd.DataFrame:
    url = f"https://{BTS_HOST}/resource/{BTS_PORTDATA_RESOURCE}.json?$limit=50000"
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=120) as r:
        df = pd.DataFrame(json.load(r))
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["year"] = df["reporting_year"].astype(str).str[:4]
    df["complex_id"] = df["port_name"].map(PORT_NAME_TO_COMPLEX)
    return df


def annual_container_calls(df: pd.DataFrame, complex_id: str) -> pd.DataFrame:
    """Official annual container-vessel calls for one complex (SPB sums LA + Long Beach)."""
    g = df[(df["cargo_type"] == "VESSEL CALLS") & (df["trade_type"] == "Container")
           & (df["complex_id"] == complex_id)]
    series = g.groupby("year")["volume"].sum().reset_index().rename(columns={"volume": "value"})
    series = series.dropna(subset=["value"]).sort_values("year").reset_index(drop=True)
    series["value"] = series["value"].round().astype(int)
    return series


def ingest_annual_calls(out_dir: Path = ANNUAL_OFFICIAL_DIR) -> pd.DataFrame:
    """Ingest official ANNUAL container-vessel calls for all 11 registry gateways."""
    df = fetch_bts_port_data()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    access = date.today().isoformat()
    manifest = []
    for complex_id in sorted(set(PORT_NAME_TO_COMPLEX.values())):
        series = annual_container_calls(df, complex_id)
        if not len(series):
            print(f"  ! {complex_id}: no annual container calls — skipped")
            continue
        dest = out_dir / f"{complex_id}__container_vessel_calls__annual.csv"
        series.to_csv(dest, index=False, lineterminator="\n")
        manifest.append({"complex_id": complex_id, "metric": "CONTAINER_VESSEL_CALLS", "frequency": "annual",
                         "source": BTS_CALLS_SOURCE, "access_date": access,
                         "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                         "n_years": len(series), "coverage": f"{series.year.min()}..{series.year.max()}"})
        print(f"  + {complex_id}: {len(series)} yrs {series.year.min()}..{series.year.max()} -> {dest.name}")
    man = pd.DataFrame(manifest)
    man.to_csv(out_dir / "annual_ingestion_manifest.csv", index=False, lineterminator="\n")
    print(f"\nG1-v2 annual container-CALLS coverage: {len(man)}/11 gateways (primary comparator, annual)")
    return man


if __name__ == "__main__":
    print("== monthly container TEU (rd72 + iahn) ==")
    ingest()
    print("\n== annual container vessel calls (5rpz, primary comparator) ==")
    ingest_annual_calls()
