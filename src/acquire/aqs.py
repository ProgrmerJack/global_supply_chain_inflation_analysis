"""Acquire EPA AQS daily air-quality for the port counties (NS-G4).

Ship-relevant pollutants NO2 (42602) + PM2.5 FRM/FEM (88101), daily summaries, 2019-2023, for the primary
county of each of the 11 G1-v2 gateways. Uses AQS_EMAIL + AQS_API_KEY from .env. AQS requires single-year
date ranges, so we loop (county x param x year) with a short pause. Hourly (for the wind-oriented design) and
SO2/O3 are a targeted follow-up per monitor.

Run: python src/acquire/aqs.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_util import GATEWAY_COUNTIES, ROOT, load_env

OUT = ROOT / "data/external/aqs"
PARAMS = {"42602": "NO2", "88101": "PM25"}
YEARS = range(2019, 2024)
KEEP = ["state_code", "county_code", "site_number", "parameter", "date_local", "arithmetic_mean",
        "units_of_measure", "aqi", "latitude", "longitude", "local_site_name"]


def acquire(out: Path = OUT) -> pd.DataFrame:
    env = load_env()
    e, k = urllib.parse.quote(env.get("AQS_EMAIL", "")), urllib.parse.quote(env.get("AQS_API_KEY", ""))
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for complex_id, counties in GATEWAY_COUNTIES.items():
        state, county = counties[0]                       # primary county per gateway
        for pcode, pname in PARAMS.items():
            for yr in YEARS:
                url = (f"https://aqs.epa.gov/data/api/dailyData/byCounty?email={e}&key={k}"
                       f"&param={pcode}&bdate={yr}0101&edate={yr}1231&state={state}&county={county}")
                try:
                    d = json.load(urllib.request.urlopen(url, timeout=120))
                except Exception as ex:
                    print(f"  ! {complex_id} {pname} {yr}: {str(ex)[:50]}"); time.sleep(0.4); continue
                data = d.get("Data", [])
                if data:
                    df = pd.DataFrame(data)
                    df = df[[c for c in KEEP if c in df.columns]].copy()
                    df.insert(0, "complex_id", complex_id)
                    frames.append(df)
                print(f"  + {complex_id} {pname} {yr}: {len(data)} obs")
                time.sleep(0.35)
    full = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    dest = out / "aqs_daily_no2_pm25_2019_2023.csv"
    full.to_csv(dest, index=False, lineterminator="\n")
    pd.DataFrame([{"dataset": "EPA AQS dailyData NO2+PM2.5 2019-2023", "obs": len(full),
                   "gateways": len(GATEWAY_COUNTIES), "source": "EPA AQS API dailyData/byCounty",
                   "access_date": date.today().isoformat(),
                   "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}]).to_csv(
        out / "manifest.csv", index=False, lineterminator="\n")
    print(f"  = {len(full)} obs -> {dest.name}")
    return full


if __name__ == "__main__":
    acquire()
