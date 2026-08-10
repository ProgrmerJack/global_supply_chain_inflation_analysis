"""
Dwell census for the 2009-2014 era (File Geodatabase format), disk-light & resumable.

Pre-2015 Marine Cadastre AIS ships as MONTHLY per-UTM-zone File Geodatabases
(Zone{NN}_{year}_{MM}.gdb.zip), normalized into Broadcast (positions, by MMSI) and
Vessel (MMSI -> VesselType/Length/Width) layers. Unlike 2015+, VesselType here is the
clean 2-digit NMEA code in the Vessel layer (verified: LA 2013-06 -> 351 cargo/tanker),
so no Cargo-field trick is needed; we join Broadcast to Vessel by MMSI.

Each of the 5 study ports lives in a distinct zone:
    LA_Long_Beach=11  NY_NJ=18  Houston=15  Savannah=17  Seattle=10
so one zone file = one port. We stream each zone-month FGDB to a temp dir, bbox-filter
Broadcast to the port box (GDAL push-down), join Vessel for type, keep cargo/tanker
(70-89), build the same observation schema as the 2015+ extractor, then feed the
VERIFIED dwell core (compute_dwell_metrics). Raw files are deleted immediately; peak
disk = one unzipped FGDB.

Output: data/processed/ais_dwell_census/monthly_dwell_2009_2014.csv  (same columns as
the 2015+ census, so the two concatenate into one 2009-2025 dwell series).
"""

from __future__ import annotations

import argparse
import calendar
import os
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import geopandas as gpd
import pandas as pd
import pyogrio

sys.path.insert(0, os.path.dirname(__file__))
from stream_sample_ais import download  # noqa: E402
from extract_port_observations import PORT_DEFINITIONS, classify_vessel, OUT_COLS  # noqa: E402
from compute_dwell_metrics import compute_vessel_dwell, aggregate_monthly  # noqa: E402
from mode_time import assign_mode_labels, compute_mode_intervals, aggregate_monthly_mode_time, load_mode_zones  # noqa: E402

BASE_URL = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"
PORT_ZONE = {"LA_Long_Beach": 11, "NY_NJ": 18, "Houston": 15, "Savannah": 17, "Seattle": 10}


def fgdb_url(year: int, month: int, zone: int) -> str:
    # URL layout varies by era (all still wrap a FileGDB):
    #   2009-2010: named month folder + .zip      (01_January_2009/Zone11_2009_01.zip)
    #   2011-2013: NN month folder + .gdb.zip      (01/Zone11_2011_01.gdb.zip)
    #   2014:      NN month folder + .zip          (01/Zone11_2014_01.zip)
    if year <= 2010:
        folder = f"{month:02d}_{calendar.month_name[month]}_{year}"
        return f"{BASE_URL}/{year}/{folder}/Zone{zone}_{year}_{month:02d}.zip"
    ext = "zip" if year >= 2014 else "gdb.zip"
    return f"{BASE_URL}/{year}/{month:02d}/Zone{zone}_{year}_{month:02d}.{ext}"


def extract_port_month(year: int, month: int, port: str):
    """Return (obs DataFrame|None, status) of cargo/tanker pings in `port` for the month.

    Reads the FileGDB straight from the downloaded zip via GDAL's /vsizip virtual FS —
    ~9.5x faster than extracting to disk first (Windows lock/FS overhead on the .gdb)."""
    zone = PORT_ZONE[port]
    b = PORT_DEFINITIONS[port]
    bbox = (b["lon_min"], b["lat_min"], b["lon_max"], b["lat_max"])
    url = fgdb_url(year, month, zone)
    tmpzip = tempfile.mktemp(suffix=".gdb.zip")
    try:
        # zone files range 78 MB (LA) to ~2.1 GB (Houston/Gulf); allow a long budget so
        # the big ones complete rather than tripping the truncated-download guard.
        download(url, tmpzip, timeout=180, max_seconds=3600)
        with zipfile.ZipFile(tmpzip) as z:
            gdb_inner = next((p for p in (n.split("/")[0] for n in z.namelist())
                              if p.endswith(".gdb")), None)
        if not gdb_inner:
            return None, "error:no .gdb inside zip"
        vsi = f"/vsizip/{tmpzip}/{gdb_inner}".replace("\\", "/")
        layers = [l[0] for l in pyogrio.list_layers(vsi)]
        bcast = next(l for l in layers if l.endswith("Broadcast"))
        vessel = next(l for l in layers if l.endswith("Vessel"))

        b_df = gpd.read_file(vsi, layer=bcast, bbox=bbox, columns=["MMSI", "BaseDateTime"])
        if not len(b_df):
            return None, "empty"
        v_df = gpd.read_file(vsi, layer=vessel, read_geometry=False,
                             columns=["MMSI", "VesselType", "Length", "Width"])
        m = b_df[["MMSI", "BaseDateTime"]].copy()
        m["LON"] = b_df.geometry.x.values
        m["LAT"] = b_df.geometry.y.values
        m = m.merge(v_df, on="MMSI", how="left")
        vt = pd.to_numeric(m["VesselType"], errors="coerce")
        m = m[vt.between(70, 89)].copy()
        if not len(m):
            return None, "no_cargo"
        m["VesselType"] = vt[vt.between(70, 89)].values
        m["VesselCategory"] = classify_vessel(m["VesselType"])
        m["Port"] = port
        for c in OUT_COLS:
            if c not in m.columns:
                m[c] = pd.NA
        return m.reindex(columns=OUT_COLS), "ok"
    except Exception as e:  # noqa: BLE001
        status = "missing" if "404" in str(e) else "error"
        return None, f"{status}:{str(e)[:120]}"
    finally:
        if os.path.exists(tmpzip):
            os.remove(tmpzip)


def port_month_dwell(year: int, month: int, port: str, mode_zones):
    """One (port, month) unit: download its zone, compute that port's monthly dwell row.
    Returns (monthly_metrics_df|None, status). Per-port granularity gives clean
    resumability — a 2 GB Houston failure never discards the cheap LA/NY/etc. rows."""
    obs, status = extract_port_month(year, month, port)
    if obs is None:
        return None, None, None, status
    ym = f"{year}-{month:02d}"
    classified = assign_mode_labels(obs, mode_zones)
    mode_monthly = aggregate_monthly_mode_time(compute_mode_intervals(classified))
    monthly = aggregate_monthly(compute_vessel_dwell(obs))
    monthly = monthly[monthly["YearMonth"] == ym].copy()
    return monthly, mode_monthly, classified, "ok"


def _parse_range(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-"); out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


# process the cheap headline port (LA, 78 MB) first; the 2.1 GB Houston/Gulf zone last
PORT_ORDER = ["LA_Long_Beach", "Savannah", "NY_NJ", "Seattle", "Houston"]


def _timed_task(year: int, month: int, port: str, mode_zones):
    t = time.time()
    monthly, mode_monthly, classified, status = port_month_dwell(year, month, port, mode_zones)
    return monthly, mode_monthly, classified, status, time.time() - t


def main() -> None:
    ap = argparse.ArgumentParser(description="2009-2014 FGDB dwell census (per-port, parallel).")
    ap.add_argument("--years", default="2009-2014")
    ap.add_argument("--months", default="1-12")
    ap.add_argument("--workers", type=int, default=4, help="concurrent (month,port) downloads")
    ap.add_argument("--out-dir", default="data/processed/ais_dwell_census")
    ap.add_argument("--mode-zones", default="config/geometry/port_mode_zones.geojson")
    ap.add_argument("--mode-output", default="monthly_mode_time_2009_2014.csv")
    ap.add_argument("--retain-pings", action="store_true")
    args = ap.parse_args()
    years, months = _parse_range(args.years), _parse_range(args.months)
    os.makedirs(args.out_dir, exist_ok=True)
    dwell_path = os.path.join(args.out_dir, "monthly_dwell_2009_2014.csv")
    mode_path = os.path.join(args.out_dir, args.mode_output)
    manifest_path = os.path.join(args.out_dir, "manifest_port_2009_2014.csv")
    mode_zones = load_mode_zones(args.mode_zones)

    # resumability is per (Port, YearMonth): a pair is done iff it has a dwell row, so a
    # failed 2 GB Houston download never forces re-downloading the cheap ports.
    done = set()
    dwell_new = not os.path.exists(dwell_path)
    if not dwell_new:
        ex_df = pd.read_csv(dwell_path)
        done = set(zip(ex_df["Port"].astype(str), ex_df["YearMonth"].astype(str)))

    prio = {p: i for i, p in enumerate(PORT_ORDER)}
    tasks = [(y, m, port) for y in years for m in months for port in PORT_ORDER
             if (port, f"{y}-{m:02d}") not in done]
    tasks.sort(key=lambda t: (prio[t[2]], t[0], t[1]))  # LA first, then chronological
    print(f"{len(tasks)} (port,month) task(s) ({len(done)} done). workers={args.workers}", flush=True)
    if not tasks:
        return

    man_new = not os.path.exists(manifest_path)
    state = {"dwell_new": dwell_new, "mode_new": not os.path.exists(mode_path)}
    lock = threading.Lock()
    t0 = time.time(); n = n_ok = 0
    with open(manifest_path, "a", newline="") as mf, \
            open(dwell_path, "a", newline="") as df_out, \
            open(mode_path, "a", newline="") as mode_out, \
            ThreadPoolExecutor(max_workers=args.workers) as ex:
        if man_new:
            mf.write("YearMonth,Port,status,seconds\n"); mf.flush()
        futures = {ex.submit(_timed_task, y, m, port, mode_zones): (y, m, port) for (y, m, port) in tasks}
        for fut in as_completed(futures):
            y, m, port = futures[fut]
            monthly, mode_monthly, classified, status, secs = fut.result()
            with lock:
                n += 1
                mf.write(f"{y}-{m:02d},{port},{str(status).replace(',',';')[:80]},{secs:.0f}\n"); mf.flush()
                if monthly is not None and len(monthly):
                    monthly.to_csv(df_out, header=state["dwell_new"], index=False)
                    state["dwell_new"] = False; df_out.flush(); n_ok += 1
                if mode_monthly is not None and len(mode_monthly):
                    mode_monthly.to_csv(mode_out, header=state["mode_new"], index=False)
                    state["mode_new"] = False; mode_out.flush()
                if args.retain_pings and classified is not None and len(classified):
                    ping_dir = os.path.join(
                        args.out_dir, "port_pings_fgdb", f"year={y}", f"month={m:02d}", f"port={port}"
                    )
                    os.makedirs(ping_dir, exist_ok=True)
                    classified.to_parquet(os.path.join(ping_dir, "port_pings.parquet"), index=False)
                rate = n / max(time.time() - t0, 1e-9)
                print(f"  {y}-{m:02d} {port}: {status} ({secs:.0f}s)  [{n}/{len(tasks)}] ok={n_ok}  "
                      f"ETA {(len(tasks)-n)/rate/3600:.2f} h", flush=True)
    print(f"done in {(time.time()-t0)/3600:.2f} h. ok={n_ok}/{len(tasks)}")


if __name__ == "__main__":
    main()
