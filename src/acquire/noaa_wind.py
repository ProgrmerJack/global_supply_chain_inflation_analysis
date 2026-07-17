"""Acquire NOAA NCEI hourly surface wind (ISD global-hourly) near each gateway (NS-G4 wind-oriented design).

Downloads the Integrated Surface Database hourly CSV per station-year (2019-2023) for the airport nearest each
gateway, parses the WND field (direction deg + speed m/s). Feeds the downwind/upwind exposure identification in
the observed air-quality design (plan §11). No auth (NCEI is open). Robust to unknown station ids (skips 404).

Run: python src/acquire/noaa_wind.py
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_util import ROOT
from _http import fetch_many, get_bytes

OUT = ROOT / "data/external/noaa_wind"
YEARS = range(2019, 2024)
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0"}
# gateway -> ISD station id (USAF+WBAN) of the nearest airport
STATIONS = {
    "san_pedro_bay": "72297023129",        # Long Beach Daugherty Field
    "new_york_new_jersey": "72502014734",  # Newark Liberty
    "savannah_ga": "72207003822",          # Savannah/Hilton Head
    "norfolk_newport_news_va": "72308013737",  # Norfolk Intl
    "houston_tx": "72243012960",           # Houston Hobby
    "charleston_sc": "72208013880",        # Charleston Intl
    "baltimore_md": "72406093721",         # Baltimore/Washington Intl
    "philadelphia_pa": "72408013739",      # Philadelphia Intl
    "jacksonville_fl": "72206013889",      # Jacksonville Intl
    "miami_fl": "72202012839",             # Miami Intl
    "port_everglades_fl": "72203012849",   # Fort Lauderdale/Hollywood
}


def _parse_wnd(wnd: str):
    try:
        d, _, _, s, _ = str(wnd).split(",")
        return (None if d == "999" else int(d)), (None if s == "9999" else int(s) / 10.0)
    except Exception:
        return None, None


def _download(task):
    cid, st, yr = task
    url = f"https://www.ncei.noaa.gov/data/global-hourly/access/{yr}/{st}.csv"
    try:
        return get_bytes(url)                                  # retries on reset/5xx inside
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def acquire(out: Path = OUT) -> pd.DataFrame:
    out.mkdir(parents=True, exist_ok=True)
    tasks = [(cid, st, yr) for cid, st in STATIONS.items() for yr in YEARS]
    results = fetch_many(tasks, _download, max_workers=12)     # concurrent station-year downloads
    frames = []
    for (cid, st, yr), raw in results:
        if not raw:
            continue
        df = pd.read_csv(io.BytesIO(raw), usecols=lambda c: c in ("STATION", "DATE", "WND", "NAME",
                                                                  "LATITUDE", "LONGITUDE"), low_memory=False)
        df[["wind_dir_deg", "wind_speed_ms"]] = df["WND"].apply(lambda w: pd.Series(_parse_wnd(w)))
        df["complex_id"] = cid
        frames.append(df.drop(columns=["WND"]))
    full = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(full):
        print(full.groupby("complex_id").size().to_string())
    dest = out / "noaa_hourly_wind_2019_2023.csv"
    full.to_csv(dest, index=False, lineterminator="\n")
    pd.DataFrame([{"dataset": "NOAA NCEI ISD hourly wind near gateways 2019-2023", "obs": len(full),
                   "source": "NOAA NCEI global-hourly (ISD)", "access_date": date.today().isoformat(),
                   "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}]).to_csv(
        out / "manifest.csv", index=False, lineterminator="\n")
    print(f"  = {len(full)} hourly wind obs -> {dest.name}")
    return full


def acquire_spb_2024_supplement(out: Path = OUT) -> pd.DataFrame:
    """Retrieve only the missing prospective AB 617 meteorology year.

    The original multi-gateway archive is deliberately left byte-for-byte intact.
    This narrow supplement avoids downloading the already-retained 2019--2023
    station-years again while extending the San Pedro Bay support through the
    protocol's fixed 2024 endpoint.
    """
    out.mkdir(parents=True, exist_ok=True)
    station = STATIONS["san_pedro_bay"]
    raw = _download(("san_pedro_bay", station, 2024))
    if not raw:
        raise RuntimeError("NOAA NCEI returned no 2024 San Pedro Bay station file")
    frame = pd.read_csv(
        io.BytesIO(raw),
        usecols=lambda c: c in ("STATION", "DATE", "WND", "NAME", "LATITUDE", "LONGITUDE"),
        low_memory=False,
    )
    frame[["wind_dir_deg", "wind_speed_ms"]] = frame["WND"].apply(
        lambda value: pd.Series(_parse_wnd(value))
    )
    frame["complex_id"] = "san_pedro_bay"
    frame = frame.drop(columns=["WND"])
    destination = out / "noaa_hourly_wind_spb_2024.csv"
    frame.to_csv(destination, index=False, lineterminator="\n")
    manifest = out / "manifest_spb_2024.csv"
    pd.DataFrame([{
        "dataset": "NOAA NCEI ISD hourly wind San Pedro Bay 2024 supplement",
        "obs": len(frame),
        "source": "NOAA NCEI global-hourly (ISD)",
        "station": station,
        "access_date": date.today().isoformat(),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }]).to_csv(manifest, index=False, lineterminator="\n")
    print(f"  = {len(frame)} hourly wind obs -> {destination.name}")
    return frame


def acquire_spb_year(year: int, out: Path = OUT) -> pd.DataFrame:
    """Retrieve one missing SPB station-year without touching retained years."""
    if year < 1901 or year > date.today().year:
        raise ValueError("NOAA station year is outside the observable range")
    out.mkdir(parents=True, exist_ok=True)
    station = STATIONS["san_pedro_bay"]
    raw = _download(("san_pedro_bay", station, year))
    if not raw:
        raise RuntimeError(f"NOAA NCEI returned no {year} San Pedro Bay station file")
    frame = pd.read_csv(
        io.BytesIO(raw),
        usecols=lambda c: c in ("STATION", "DATE", "WND", "NAME", "LATITUDE", "LONGITUDE"),
        low_memory=False,
    )
    frame[["wind_dir_deg", "wind_speed_ms"]] = frame["WND"].apply(
        lambda value: pd.Series(_parse_wnd(value))
    )
    frame["complex_id"] = "san_pedro_bay"
    frame = frame.drop(columns=["WND"])
    destination = out / f"noaa_hourly_wind_spb_{year}.csv"
    frame.to_csv(destination, index=False, lineterminator="\n")
    (out / f"manifest_spb_{year}.csv").write_text(
        "dataset,obs,source,station,access_date,sha256\n"
        f"NOAA NCEI ISD hourly wind San Pedro Bay {year},{len(frame)},NOAA NCEI global-hourly (ISD),"
        f"{station},{date.today().isoformat()},{hashlib.sha256(destination.read_bytes()).hexdigest()}\n",
        encoding="utf-8",
    )
    return frame


def acquire_spb_ghcnh_2025_continuation(out: Path = OUT) -> pd.DataFrame:
    """Fill the co-located station after ISD was discontinued in August 2025."""
    out.mkdir(parents=True, exist_ok=True)
    url = (
        "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/"
        "access/by-year/2025/psv/GHCNh_USW00023129_2025.psv"
    )
    raw = get_bytes(url, timeout=600)
    frame = pd.read_csv(
        io.BytesIO(raw), sep="|",
        usecols=["STATION", "Station_name", "DATE", "LATITUDE", "LONGITUDE",
                 "wind_direction", "wind_speed", "wind_direction_Quality_Code",
                 "wind_speed_Quality_Code"],
        low_memory=False,
    ).rename(columns={
        "Station_name": "NAME", "wind_direction": "wind_dir_deg",
        "wind_speed": "wind_speed_ms",
    })
    frame["complex_id"] = "san_pedro_bay"
    destination = out / "noaa_hourly_wind_spb_2025_ghcnh_continuation.csv"
    frame.to_csv(destination, index=False, lineterminator="\n")
    (out / "manifest_spb_2025_ghcnh_continuation.json").write_text(json.dumps({
        "dataset": "NOAA GHCNh co-located Long Beach 2025 continuation",
        "source": url,
        "station": "USW00023129",
        "rows": len(frame),
        "access_date": date.today().isoformat(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }, indent=2) + "\n", encoding="utf-8")
    return frame


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Acquire fixed NOAA ISD wind inputs.")
    parser.add_argument(
        "--spb-2024-only",
        action="store_true",
        help="retrieve only the missing San Pedro Bay 2024 supplement",
    )
    parser.add_argument("--spb-year", type=int, help="retrieve one SPB station-year")
    parser.add_argument("--spb-ghcnh-2025", action="store_true", help="retrieve co-located GHCNh continuation")
    args = parser.parse_args()
    if args.spb_ghcnh_2025:
        acquire_spb_ghcnh_2025_continuation()
    elif args.spb_year:
        acquire_spb_year(args.spb_year)
    elif args.spb_2024_only:
        acquire_spb_2024_supplement()
    else:
        acquire()
