"""Acquire ACS 5-year (2022) tract-level demographics for the port counties (NS-G5 equity).

Core estimands per plan.md §12: population, income, poverty, race/ethnicity, age. Scoped to the counties
containing the 11 G1-v2 gateways (env_util.GATEWAY_COUNTIES). Uses CENSUS_API_KEY from .env.

Run: python src/acquire/acs.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_util import GATEWAY_COUNTIES, ROOT, load_env

OUT = ROOT / "data/external/acs"
ACS_YEAR = 2022
ACS_VARS = {
    "B01003_001E": "total_pop", "B19013_001E": "median_hh_income",
    "B17001_001E": "poverty_universe", "B17001_002E": "below_poverty",
    "B02001_001E": "race_universe", "B02001_002E": "white", "B02001_003E": "black", "B02001_005E": "asian",
    "B03003_001E": "hisp_universe", "B03003_003E": "hispanic",
    "B01002_001E": "median_age", "B25077_001E": "median_home_value",
}


def _fetch_county(state: str, county: str, key: str) -> pd.DataFrame:
    get = "NAME," + ",".join(ACS_VARS)
    url = (f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5?get={get}"
           f"&for=tract:*&in={urllib.parse.quote(f'state:{state} county:{county}')}&key={key}")
    with urllib.request.urlopen(urllib.request.Request(url), timeout=90) as r:
        rows = json.load(r)
    df = pd.DataFrame(rows[1:], columns=rows[0]).rename(columns=ACS_VARS)
    for c in ACS_VARS.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["geoid"] = df["state"] + df["county"] + df["tract"]
    return df


def acquire(out: Path = OUT) -> pd.DataFrame:
    key = load_env().get("CENSUS_API_KEY", "")
    out.mkdir(parents=True, exist_ok=True)
    frames, manifest = [], []
    for complex_id, counties in GATEWAY_COUNTIES.items():
        for state, county in counties:
            try:
                df = _fetch_county(state, county, key)
            except Exception as e:  # keep going; report the miss
                print(f"  ! {complex_id} {state}{county}: {str(e)[:60]}")
                continue
            df.insert(0, "complex_id", complex_id)
            frames.append(df)
            print(f"  + {complex_id} {state}{county}: {len(df)} tracts")
    full = pd.concat(frames, ignore_index=True)
    dest = out / f"acs5_{ACS_YEAR}_port_county_tracts.csv"
    full.to_csv(dest, index=False, lineterminator="\n")
    pd.DataFrame([{"dataset": f"ACS 5-year {ACS_YEAR}", "tracts": len(full),
                   "counties": sum(len(c) for c in GATEWAY_COUNTIES.values()),
                   "source": f"Census ACS API {ACS_YEAR}/acs/acs5", "access_date": date.today().isoformat(),
                   "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}]).to_csv(
        out / "manifest.csv", index=False, lineterminator="\n")
    print(f"  = {len(full)} tracts -> {dest.name}")
    return full


if __name__ == "__main__":
    acquire()
