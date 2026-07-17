"""Acquire OpenAQ v3 air-quality measurements near each gateway (NS-G4; backstops the throttled AQS pull).

Finds government monitors within a radius of each gateway and pulls daily aggregates for the ship-relevant
pollutants (NO2, PM2.5, SO2, O3), 2019-2023, via bounded concurrency + adaptive 429 backoff (`_http`). The
prior serial version silently swallowed rate-limited calls -> 0 rows; this retries hard and fetches in parallel.
Uses the OpenAQ key (.env). Confirmatory outcomes (monitor selection, wind defs) are frozen separately.

Run: python src/acquire/openaq.py
"""
from __future__ import annotations

import hashlib
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_util import ROOT, load_env
from _http import fetch_many, get_json

OUT = ROOT / "data/external/openaq"
WANT = {"no2", "pm25", "so2", "o3"}
MAX_MONITORS = 12                     # closest N monitors per gateway (bounds call volume)
GATEWAY_COORDS = {
    "san_pedro_bay": (33.74, -118.26), "new_york_new_jersey": (40.66, -74.14),
    "savannah_ga": (32.08, -81.09), "norfolk_newport_news_va": (36.88, -76.33),
    "houston_tx": (29.72, -95.10), "charleston_sc": (32.79, -79.92),
    "baltimore_md": (39.24, -76.53), "philadelphia_pa": (39.90, -75.13),
    "jacksonville_fl": (30.39, -81.52), "miami_fl": (25.78, -80.17),
    "port_everglades_fl": (26.09, -80.12),
}


def acquire(out: Path = OUT, radius_m: int = 25000) -> pd.DataFrame:
    key = load_env().get("OpenAQ", "")
    hdr = {"X-API-Key": key}
    out.mkdir(parents=True, exist_ok=True)

    # 1) locations per gateway (concurrent), keep the closest MAX_MONITORS
    def _loc(item):
        cid, (lat, lon) = item
        return get_json(f"https://api.openaq.org/v3/locations?coordinates={lat},{lon}"
                        f"&radius={radius_m}&limit=100", hdr)
    tasks = []                       # (cid, location_meta, sensor_id, pname)
    for (cid, _), loc in fetch_many(GATEWAY_COORDS.items(), _loc, max_workers=8):
        results = sorted((loc or {}).get("results", []), key=lambda L: L.get("distance") or 9e9)[:MAX_MONITORS]
        for L in results:
            for s in L.get("sensors", []):
                pname = (s.get("parameter") or {}).get("name", "")
                if pname in WANT:
                    tasks.append((cid, {"id": L.get("id"), "name": L.get("name"),
                                        "lat": (L.get("coordinates") or {}).get("latitude"),
                                        "lon": (L.get("coordinates") or {}).get("longitude")}, s["id"], pname))
    print(f"  {len(tasks)} pollutant-sensors across {len({t[0] for t in tasks})} gateways")

    # 2) daily measurements per sensor-year (OpenAQ caps limit at 1000; 1 yr < 1000 days -> no pagination)
    sy_tasks = [(cid, meta, sid, pname, yr) for (cid, meta, sid, pname) in tasks for yr in range(2019, 2024)]

    def _meas(task):
        cid, meta, sid, pname, yr = task
        m = get_json(f"https://api.openaq.org/v3/sensors/{sid}/measurements/daily"
                     f"?date_from={yr}-01-01&date_to={yr}-12-31&limit=1000", hdr)
        recs = m.get("results", [])
        if not recs:
            return None
        df = pd.json_normalize(recs)
        df["complex_id"], df["location"], df["location_id"] = cid, meta["name"], meta["id"]
        df["sensor_id"], df["parameter"], df["lat"], df["lon"] = sid, pname, meta["lat"], meta["lon"]
        return df

    frames = [d for _, d in fetch_many(sy_tasks, _meas, max_workers=8) if d is not None]
    full = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    keep = [c for c in ["complex_id", "location", "location_id", "sensor_id", "parameter", "lat", "lon",
                        "value", "period.datetimeFrom.local", "summary.min", "summary.max"] if c in full.columns]
    full = full[keep] if keep else full
    dest = out / "openaq_daily_2019_2023.csv"
    full.to_csv(dest, index=False, lineterminator="\n")
    pd.DataFrame([{"dataset": "OpenAQ v3 daily NO2/PM25/SO2/O3 near gateways 2019-2023", "rows": len(full),
                   "sensors": len(tasks), "source": "OpenAQ API v3", "access_date": date.today().isoformat(),
                   "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}]).to_csv(
        out / "manifest.csv", index=False, lineterminator="\n")
    print(f"  = {len(full)} daily obs from {len(frames)} sensors -> {dest.name}")
    return full


if __name__ == "__main__":
    acquire()
