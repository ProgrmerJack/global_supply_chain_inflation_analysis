"""Fast EPA AQS acquisition via pre-generated bulk annual files (NS-G4; the go-forward method).

Diagnosis: the AQS *API* returns ~22 s per request even for tiny payloads (server-side latency), so the serial
daily pull took ~1 h. AQS also publishes pre-generated national annual files
(`aqs.epa.gov/aqsweb/airdata/{freq}_{param}_{year}.zip`) — one download = ALL US monitors for a param-year.
This downloads them concurrently, filters to the gateway counties, and assembles. Used here for HOURLY data
(needed for the plan §11 wind-oriented design; hourly via the API would be intractable). No auth.

Run: python src/acquire/aqs_bulk.py            # hourly NO2 + PM2.5, gateway counties, 2019-2023
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_util import GATEWAY_COUNTIES, ROOT
from _http import fetch_many, get_bytes

OUT = ROOT / "data/external/aqs_hourly"
PARAMS = {"42602": "NO2", "88101": "PM25"}       # add 42401 SO2 / 44201 O3 as needed
YEARS = range(2019, 2024)
COUNTY_SET = {(int(s), int(c)) for lst in GATEWAY_COUNTIES.values() for (s, c) in lst}
KEEP = ["State Code", "County Code", "Site Num", "Parameter Name", "Date GMT", "Time GMT",
        "Sample Measurement", "Units of Measure", "Latitude", "Longitude", "Local Site Name"]
SPB_KEEP = [
    "State Code", "County Code", "Site Num", "Parameter Code", "POC", "Latitude", "Longitude",
    "Datum", "Parameter Name", "Date Local", "Time Local", "Date GMT", "Time GMT",
    "Sample Measurement", "Units of Measure", "MDL", "Uncertainty", "Qualifier",
    "Method Type", "Method Code", "Method Name", "State Name", "County Name",
    "Date of Last Change",
]


def _fetch_filter(task):
    param, pname, yr = task
    url = f"https://aqs.epa.gov/aqsweb/airdata/hourly_{param}_{yr}.zip"
    raw = get_bytes(url, timeout=300)
    df = pd.read_csv(io.BytesIO(raw), compression="zip", low_memory=False)
    df = df[df.apply(lambda r: (int(r["State Code"]), int(r["County Code"])) in COUNTY_SET, axis=1)]
    return df[[c for c in KEEP if c in df.columns]].copy()


def acquire(out: Path = OUT) -> pd.DataFrame:
    out.mkdir(parents=True, exist_ok=True)
    tasks = [(p, pn, y) for p, pn in PARAMS.items() for y in YEARS]
    frames = []
    for (p, pn, y), df in fetch_many(tasks, _fetch_filter, max_workers=6):   # 10 national zips, concurrent
        if df is None:
            print(f"  ! hourly_{p}_{y}: failed"); continue
        frames.append(df)
        print(f"  + {pn} {y}: {len(df)} gateway-county hourly obs")
    full = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    dest = out / "aqs_hourly_no2_pm25_gatewaycounties_2019_2023.csv"
    full.to_csv(dest, index=False, lineterminator="\n")
    pd.DataFrame([{"dataset": "EPA AQS HOURLY NO2+PM2.5 gateway counties 2019-2023 (bulk files)",
                   "obs": len(full), "source": "aqs.epa.gov/aqsweb/airdata bulk files",
                   "access_date": date.today().isoformat(),
                   "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}]).to_csv(
        out / "manifest.csv", index=False, lineterminator="\n")
    print(f"  = {len(full)} hourly obs -> {dest.name}")
    return full


def acquire_spb_no2_2023_2025(out: Path = OUT) -> pd.DataFrame:
    """Retrieve complete 2023--2025 Los Angeles County NO2 files once."""
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    sources = []
    for year in (2023, 2024, 2025):
        url = f"https://aqs.epa.gov/aqsweb/airdata/hourly_42602_{year}.zip"
        raw = get_bytes(url, timeout=600)
        source_hash = hashlib.sha256(raw).hexdigest()
        frame = pd.read_csv(io.BytesIO(raw), compression="zip", low_memory=False)
        frame = frame.loc[
            frame["State Code"].eq(6) & frame["County Code"].eq(37),
            [column for column in SPB_KEEP if column in frame.columns],
        ].copy()
        frame["source_year"] = year
        frames.append(frame)
        sources.append({"year": year, "url": url, "zip_sha256": source_hash, "rows": len(frame)})
    full = pd.concat(frames, ignore_index=True)
    destination = out / "aqs_hourly_no2_los_angeles_2023_2025.csv"
    full.to_csv(destination, index=False, lineterminator="\n")
    (out / "manifest_spb_no2_2023_2025.json").write_text(json.dumps({
        "dataset": "EPA AQS hourly NO2, Los Angeles County, 2023-2025",
        "source": "EPA AQS AirData annual bulk files",
        "access_date": date.today().isoformat(),
        "sources": sources,
        "rows": len(full),
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }, indent=2) + "\n", encoding="utf-8")
    return full


if __name__ == "__main__":
    acquire_spb_no2_2023_2025() if "--spb-no2-2023-2025" in sys.argv else acquire()
