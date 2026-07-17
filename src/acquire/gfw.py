"""Acquire Global Fishing Watch gridded AIS vessel presence (NS-G1/NS-G2).

The legacy entry point retains the inspected monthly gateway products. ``--spb-speed-bins`` performs the
separately registered, one-time daily/cell cargo retrieval for all seven official speed categories. GFW
presence is one standardized AIS position per vessel per hour; it is not a continuous track or waiting label.
Needs ``GFW_API_TOKEN`` in ``.env``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_util import ROOT, load_env

OUT = ROOT / "data/external/gfw"
BASE = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
PRESENCE = "public-global-presence:latest"
SPEED_BINS = ("<2", "2-4", "4-6", "6-10", "10-15", "15-25", ">25")
SPEED_TAGS = {"<2": "lt2", "2-4": "2-4", "4-6": "4-6", "6-10": "6-10",
              "10-15": "10-15", "15-25": "15-25", ">25": "gt25"}
SPB_BOX = [-124.5, -112.0, 28.7, 38.7]
SPB_SPEED_OUT = OUT / "spb_speed_bins"
SPB_AMENDMENT = ROOT / "prereg/amendments/2026-07-18_spb_direct_measurement_queue_reform.md"
SPB_FREEZE = ROOT / "prereg/studies/spb_queue_boundary/spb_direct_measurement_freeze_receipt.json"
SPB_EXTERNAL = ROOT / "prereg/studies/spb_queue_boundary/spb_direct_measurement_external_timestamp.json"
SPB_REGISTRATION_TITLE = "San Pedro Bay direct measurement and queue-reform speed-bin amendment"
SMOKE_EXCLUSION = "2021-12-01"
# offshore approach boxes [lon_min, lon_max, lat_min, lat_max] (~0-300nm approach of each gateway)
OFFSHORE_REGIONS = {
    "san_pedro_bay": [-122.0, -117.0, 31.0, 34.5],
    "new_york_new_jersey": [-74.6, -71.5, 39.4, 40.9],
    "savannah_ga": [-81.2, -79.3, 31.0, 32.4],
    "norfolk_newport_news_va": [-76.4, -74.2, 36.2, 37.4],
    "houston_tx": [-95.6, -93.3, 28.2, 29.7],
}


def _headers() -> dict:
    tok = load_env().get("GFW_API_TOKEN", "")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0"}


SAR = "public-global-sar-presence:latest"      # satellite radar detections (AIS non-observation layer)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _report_url(date_range: str, dataset: str, temporal_resolution: str,
                filters: tuple[str, ...]) -> str:
    params = [
        ("spatial-resolution", "LOW"),
        ("temporal-resolution", temporal_resolution),
        ("format", "JSON"),
        ("group-by", "FLAG"),
        ("datasets[0]", dataset),
        ("date-range", date_range),
    ] + [(f"filters[{index}]", value) for index, value in enumerate(filters)]
    return f"{BASE}?{urlencode(params)}"


def _post_json(url: str, body: bytes, *, retries: int = 6) -> dict:
    """POST with bounded retry; the GFW last-report slot makes parallel calls unsafe."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=_headers(), method="POST", data=body)
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.loads(response.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as error:
            last = error
            if error.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
        except (OSError, ValueError) as error:
            last = error
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError("GFW request failed") from last


def _fetch_presence_report(
    box: list[float],
    date_range: str,
    *,
    dataset: str = PRESENCE,
    temporal_resolution: str = "MONTHLY",
    filters: tuple[str, ...] = (),
) -> tuple[pd.DataFrame, dict]:
    lon0, lon1, lat0, lat1 = box
    region = {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1],
                                                  [lon0, lat1], [lon0, lat0]]]}
    url = _report_url(date_range, dataset, temporal_resolution, filters)
    j = _post_json(url, json.dumps({"geojson": region}, separators=(",", ":")).encode())
    entries = j.get("entries", [])
    dataset_version = next(iter(entries[0])) if entries and entries[0] else None
    recs = entries[0].get(dataset_version, []) if dataset_version else []
    return pd.DataFrame(recs), {
        "query_url": url,
        "dataset_version": dataset_version,
        "response_metadata": j.get("metadata", {}),
        "region": region,
    }


def fetch_presence(
    box: list[float],
    date_range: str,
    dataset: str = PRESENCE,
    *,
    temporal_resolution: str = "MONTHLY",
    filters: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Return one GFW report while preserving the legacy monthly caller contract."""
    return _fetch_presence_report(
        box,
        date_range,
        dataset=dataset,
        temporal_resolution=temporal_resolution,
        filters=filters,
    )[0]


def require_spb_speed_registration(
    amendment: Path = SPB_AMENDMENT,
    freeze: Path = SPB_FREEZE,
    external: Path = SPB_EXTERNAL,
    *,
    get_attributes=None,
) -> dict:
    """Fail closed unless the public OSF record binds the unchanged local amendment."""
    local = json.loads(freeze.read_text(encoding="utf-8"))
    receipt = json.loads(external.read_text(encoding="utf-8"))
    amendment_hash = _sha256(amendment)
    if local.get("sha256", {}).get("amendment") != amendment_hash:
        raise RuntimeError("SPB direct-measurement amendment no longer matches its local freeze")
    if receipt.get("status") != "EXTERNALLY_TIMESTAMPED":
        raise RuntimeError("SPB direct-measurement amendment is not externally timestamped")
    if receipt.get("local_freeze_receipt_sha256") != _sha256(freeze):
        raise RuntimeError("SPB external timestamp does not bind the local freeze receipt")
    if receipt.get("sha256", {}).get("amendment") != amendment_hash:
        raise RuntimeError("SPB external timestamp does not bind the amendment")
    registration_id = str(receipt.get("registration_id", ""))
    if receipt.get("registration_url") != f"https://osf.io/{registration_id}/":
        raise RuntimeError("SPB external timestamp lacks a canonical OSF registration URL")
    if get_attributes is None:
        def get_attributes(value: str) -> dict:
            request = urllib.request.Request(
                f"https://api.osf.io/v2/registrations/{value}/",
                headers={"Accept": "application/vnd.api+json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)["data"]["attributes"]
    attributes = get_attributes(registration_id)
    if (attributes.get("title") != SPB_REGISTRATION_TITLE or not attributes.get("date_registered")
            or not attributes.get("public") or attributes.get("revision_state") != "approved"
            or attributes.get("withdrawn")):
        raise RuntimeError("OSF does not report the approved public SPB direct-measurement registration")
    return receipt


def _normalise_speed_bin(frame: pd.DataFrame, year: int, speed_bin: str) -> pd.DataFrame:
    required = {"date", "lat", "lon", "hours"}
    if frame.empty and not len(frame.columns):
        frame = pd.DataFrame(columns=["date", "lat", "lon", "hours", "vesselIDs"])
    if missing := required.difference(frame.columns):
        raise ValueError(f"GFW speed-bin response lacks: {', '.join(sorted(missing))}")
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise", utc=True).dt.strftime("%Y-%m-%d")
    for column in ("lat", "lon", "hours"):
        out[column] = pd.to_numeric(out[column], errors="raise")
    if "vesselIDs" not in out:
        out["vesselIDs"] = 0
    out["vesselIDs"] = pd.to_numeric(out["vesselIDs"], errors="coerce").fillna(0)
    finite = out[["lat", "lon", "hours", "vesselIDs"]].map(math.isfinite).all().all()
    if (not finite or (out["hours"] < 0).any() or not out["lat"].between(-90, 90).all()
            or not out["lon"].between(-180, 180).all()):
        raise ValueError("GFW speed-bin response contains invalid coordinates or hours")
    if not out["date"].str.startswith(f"{year}-").all():
        raise ValueError("GFW speed-bin response falls outside its requested calendar year")
    out = out[out["date"] != SMOKE_EXCLUSION]
    out = (out.groupby(["date", "lat", "lon"], as_index=False)
           .agg(hours=("hours", "sum"), vessel_positions=("vesselIDs", "sum")))
    out.insert(3, "speed_bin", speed_bin)
    return out.sort_values(["date", "lat", "lon"], kind="stable").reset_index(drop=True)


def _write_manifest(rows: list[dict], path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame(rows).sort_values(["year", "speed_bin"], kind="stable").to_csv(
        tmp, index=False, lineterminator="\n"
    )
    tmp.replace(path)


def acquire_spb_speed_bins(
    out: Path = SPB_SPEED_OUT,
    years: range = range(2019, 2024),
    speed_bins: tuple[str, ...] = SPEED_BINS,
    *,
    verify=require_spb_speed_registration,
    fetch=_fetch_presence_report,
) -> pd.DataFrame:
    """Retrieve the registered daily/cell panel once, with hash-checked resume."""
    receipt = verify()
    if any(speed_bin not in SPEED_BINS for speed_bin in speed_bins):
        raise ValueError("speed_bins must use the seven registered GFW categories")
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.csv"
    rows = pd.read_csv(manifest_path).to_dict("records") if manifest_path.exists() else []
    indexed = {(int(row["year"]), str(row["speed_bin"])): row for row in rows}
    completed = []
    for year in years:
        for speed_bin in speed_bins:
            key = (year, speed_bin)
            path = out / f"spb_cargo_speed_{SPEED_TAGS[speed_bin]}_{year}.parquet"
            prior = indexed.get(key)
            if path.exists():
                if not prior or prior.get("sha256") != _sha256(path):
                    raise RuntimeError(f"unverifiable existing GFW speed-bin artifact: {path.name}")
                completed.append(prior)
                continue
            if prior:
                raise RuntimeError(f"GFW speed-bin manifest names a missing artifact: {path.name}")
            date_range = f"{year}-01-01,{year}-12-31"
            filters = (f"vessel_type='cargo' AND speed='{speed_bin}'",)
            frame, metadata = fetch(
                SPB_BOX,
                date_range,
                dataset=PRESENCE,
                temporal_resolution="DAILY",
                filters=filters,
            )
            frame = _normalise_speed_bin(frame, year, speed_bin)
            tmp = path.with_suffix(path.suffix + ".tmp")
            frame.to_parquet(tmp, index=False)
            tmp.replace(path)
            row = {
                "artifact": path.name,
                "year": year,
                "speed_bin": speed_bin,
                "rows": len(frame),
                "presence_hours": float(frame["hours"].sum()),
                "first_date": frame["date"].min() if len(frame) else "",
                "last_date": frame["date"].max() if len(frame) else "",
                "dataset_request": PRESENCE,
                "dataset_version": metadata.get("dataset_version") or "",
                "date_range": date_range,
                "filter": filters[0],
                "query_url": metadata["query_url"],
                "bounding_box": json.dumps(SPB_BOX, separators=(",", ":")),
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "sha256": _sha256(path),
                "registration_id": receipt["registration_id"],
                "registration_url": receipt["registration_url"],
                "excluded_smoke_date": SMOKE_EXCLUSION,
            }
            rows.append(row)
            indexed[key] = row
            completed.append(row)
            _write_manifest(rows, manifest_path)
            print(f"  + {speed_bin:>5} {year}: {len(frame):,} rows, {row['presence_hours']:,.1f} hours")
    return pd.DataFrame(completed)


def acquire(out: Path = OUT, years: range = range(2019, 2024), dataset: str = PRESENCE,
            tag: str = "presence") -> pd.DataFrame:
    out.mkdir(parents=True, exist_ok=True)
    summaries, manifest = [], []
    for complex_id, box in OFFSHORE_REGIONS.items():
        parts = []
        for yr in years:                    # GFW caps the interval span per call -> one year at a time
            try:
                d = fetch_presence(box, f"{yr}-01-01,{yr}-12-31", dataset=dataset)
                if len(d):
                    parts.append(d)
            except urllib.error.HTTPError as e:
                print(f"  ! {complex_id} {yr}: HTTP {e.code} {e.read(100).decode('utf-8','ignore')[:70]}")
            time.sleep(0.4)
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if not len(df):
            print(f"  ! {complex_id}: no data"); continue
        df["hours"] = pd.to_numeric(df.get("hours"), errors="coerce")
        df["vesselIDs"] = pd.to_numeric(df.get("vesselIDs"), errors="coerce")
        monthly = (df.groupby("date").agg(presence_hours=("hours", "sum"),
                                          vessel_positions=("vesselIDs", "sum"),
                                          active_cells=("hours", "size")).reset_index())
        monthly.insert(0, "complex_id", complex_id)
        dest = out / f"offshore_{tag}_{complex_id}_2019_2023.csv"
        monthly.to_csv(dest, index=False, lineterminator="\n")
        summaries.append(monthly)
        manifest.append({"complex_id": complex_id, "months": len(monthly), "box": str(box),
                         "source": f"GFW 4wings report {PRESENCE}", "access_date": date.today().isoformat(),
                         "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
        print(f"  + {complex_id}: {len(monthly)} months, {int(monthly.presence_hours.sum())} presence-hours")
        time.sleep(0.5)
    pd.DataFrame(manifest).to_csv(out / "manifest.csv", index=False, lineterminator="\n")
    return pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spb-speed-bins", action="store_true")
    args = parser.parse_args()
    acquire_spb_speed_bins() if args.spb_speed_bins else acquire()
