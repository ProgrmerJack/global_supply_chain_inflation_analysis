"""
Disk-light, resumable, parallel sampler for Marine Cadastre AIS (2015-2025).

Strategy ("stream and discard"): for each sampled day, download the daily national
AIS file to a temporary path, extract ONLY the 5-port cargo/tanker observations in
memory, record a tiny per-day per-port occupancy summary, and immediately DELETE the
raw file. Peak disk use is ~one temp file (~300 MB) regardless of how many years we
process; the surviving output is a few thousand summary rows (kilobytes).

Why a sample + occupancy metric: NOAA distributes the entire US-coast feed per day
(~290 MB), so a full census is ~1.1 TB. We instead sample a representative set of
days per month and use the monthly mean of the daily in-port unique-vessel count
(an anchorage-occupancy congestion proxy) which is robust to day sampling. The same
sampling is applied uniformly to every year (including 2022), so the series is
internally consistent.

Resumability: every attempted file is recorded in manifest.csv; a re-run skips files
already done. Safe to interrupt and restart (or run in the background for hours).

Outputs (under --out-dir, default data/processed/ais_sampled_2015_2025/):
    daily_port_summary.csv   one row per (date, Port): unique_vessels, n_obs
    monthly_congestion.csv   per (Port, YearMonth): mean/median daily vessels & obs
    manifest.csv             every file attempt: date, url, status, rows, seconds
"""

from __future__ import annotations

import argparse
import calendar
import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from extract_port_observations import extract_from_dataframe  # noqa: E402

BASE_URL = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"
AZURE_CSV2_URL = "https://noaaocm.blob.core.windows.net/ais/csv2"
# columns we actually need for occupancy (case/format-insensitive). "cargo" is required
# for the 2015-2017 vessel-type fix: that era stores 4-digit AVIS codes in VesselType and
# the real 2-digit NMEA type in Cargo (see extract_port_observations.extract_from_dataframe).
NEEDED = {"mmsi", "basedatetime", "base_datetime", "base_date_time", "lat", "latitude",
          "lon", "longitude", "vesseltype", "vessel_type", "cargo", "cargotype"}
UA = {"User-Agent": "Mozilla/5.0 (research; supply-chain-inflation)"}


# ----------------------------------------------------------------------------
def url_for(year: int, month: int, day: int) -> str:
    if year >= 2015:
        return f"{AZURE_CSV2_URL}/csv{year}/ais-{year}-{month:02d}-{day:02d}.csv.zst"
    return f"{BASE_URL}/{year}/AIS_{year}_{month:02d}_{day:02d}.zip"


def sample_days(year: int, month: int, n: int) -> list[int]:
    dim = calendar.monthrange(year, month)[1]
    pts = np.linspace(1, dim, min(n, dim))
    return sorted({int(round(x)) for x in pts})


def _find_aria2c() -> str | None:
    path = shutil.which("aria2c")
    if path:
        return path
    if os.name == "nt":
        root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
        hits = glob.glob(os.path.join(root, "aria2.aria2*", "**", "aria2c.exe"), recursive=True)
        if hits:
            return hits[0]
    return None


def _download_aria2(url: str, dest: str, retries: int, timeout: int, max_seconds: int, connections: int) -> None:
    aria2 = _find_aria2c()
    if not aria2:
        raise FileNotFoundError("aria2c not found")
    cmd = [
        aria2,
        f"--max-connection-per-server={connections}",
        f"--split={connections}",
        "--min-split-size=1M",
        f"--connect-timeout={min(timeout, 60)}",
        f"--timeout={timeout}",
        f"--max-tries={retries}",
        "--retry-wait=2",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--file-allocation=none",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--dir",
        os.path.dirname(os.path.abspath(dest)) or ".",
        "--out",
        os.path.basename(dest),
        url,
    ]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=max_seconds)
    if cp.returncode != 0:
        msg = (cp.stderr or cp.stdout or "").strip().replace("\n", " ")
        raise RuntimeError(f"aria2 failed ({cp.returncode}): {msg[:300]}")


def _remove_partial(path: str) -> None:
    for p in (path, f"{path}.aria2"):
        if os.path.exists(p):
            os.remove(p)


def download(
    url: str,
    dest: str,
    retries: int = 2,
    timeout: int = 120,
    max_seconds: int = 900,
    backend: str = "auto",
    connections: int = 16,
) -> None:
    """Download with a total-time budget so a slow trickle is aborted+retried,
    not allowed to hang for tens of minutes. Persistent failures raise (the file
    is then logged as 'error' and re-attempted on the next resume pass)."""
    if backend in {"auto", "aria2"} and _find_aria2c():
        try:
            _download_aria2(url, dest, retries, timeout, max_seconds, connections)
            return
        except Exception:
            _remove_partial(dest)
            if backend == "aria2":
                raise

    last = None
    for attempt in range(retries):
        try:
            start = time.time()
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
                cl = r.headers.get("Content-Length")
                expected = int(cl) if cl else None
                written = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    if time.time() - start > max_seconds:
                        raise TimeoutError(f"exceeded {max_seconds}s download budget")
            # a dropped connection yields an empty read (looks like EOF), leaving a
            # truncated file that later fails to unzip ("File is not a zip file").
            # Detect it here so it's logged as a retryable error, not silent bad data.
            if expected is not None and written < expected:
                raise IOError(f"truncated download: {written} of {expected} bytes")
            return
        except Exception as e:  # noqa: BLE001
            last = e
            _remove_partial(dest)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"download failed after {retries} tries: {last}")


def _csv_chunks(path: str):
    """Yield DataFrame chunks of the inner CSV, loading only NEEDED columns."""
    usecols = lambda c: str(c).strip().lower() in NEEDED  # noqa: E731
    kw = dict(chunksize=500_000, low_memory=False, usecols=usecols)
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as fh:
                yield from pd.read_csv(fh, **kw)
    elif path.endswith(".zst"):
        import zstandard as zstd
        with open(path, "rb") as f:
            reader = zstd.ZstdDecompressor().stream_reader(f)
            text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
            yield from pd.read_csv(text, **kw)
    else:
        yield from pd.read_csv(path, **kw)


def process_day(year: int, month: int, day: int, keep_pings_dir: str | None) -> dict:
    date = f"{year}-{month:02d}-{day:02d}"
    url = url_for(year, month, day)
    t0 = time.time()
    # keep the true format in the temp name so _csv_chunks can detect zip vs zst
    suffix = ".zip" if url.endswith(".zip") else (".csv.zst" if url.endswith(".zst") else ".csv")
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        download(url, tmp)
        parts = [extract_from_dataframe(ch) for ch in _csv_chunks(tmp)]
        parts = [p for p in parts if len(p)]
        obs = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["MMSI", "Port"])
        rows = []
        for port, g in obs.groupby("Port"):
            rows.append({"date": date, "Port": port,
                         "unique_vessels": int(g["MMSI"].nunique()),
                         "n_obs": int(len(g))})
        if keep_pings_dir and len(obs):
            os.makedirs(keep_pings_dir, exist_ok=True)
            obs.to_parquet(os.path.join(keep_pings_dir, f"obs_{year}_{month:02d}_{day:02d}.parquet"), index=False)
        return {"date": date, "url": url, "status": "ok", "rows": int(len(obs)),
                "seconds": round(time.time() - t0, 1), "summary": rows, "error": ""}
    except Exception as e:  # noqa: BLE001
        status = "missing" if "404" in str(e) else "error"
        return {"date": date, "url": url, "status": status, "rows": 0,
                "seconds": round(time.time() - t0, 1), "summary": [], "error": str(e)[:200]}
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ----------------------------------------------------------------------------
def load_done(manifest_path: str) -> set[str]:
    if not os.path.exists(manifest_path):
        return set()
    m = pd.read_csv(manifest_path)
    # treat ok + missing as done (don't retry permanently-missing days); retry errors
    return set(m.loc[m["status"].isin(["ok", "missing"]), "date"].astype(str))


def aggregate_monthly(summary_path: str, out_path: str) -> None:
    if not os.path.exists(summary_path):
        print("no daily summary yet; skipping monthly aggregation")
        return
    df = pd.read_csv(summary_path)
    if df.empty:
        return
    df["date"] = pd.to_datetime(df["date"])
    df["YearMonth"] = df["date"].dt.to_period("M").astype(str)
    monthly = df.groupby(["Port", "YearMonth"]).agg(
        mean_daily_vessels=("unique_vessels", "mean"),
        median_daily_vessels=("unique_vessels", "median"),
        mean_daily_obs=("n_obs", "mean"),
        days_sampled=("unique_vessels", "size"),
    ).reset_index()
    monthly.to_csv(out_path, index=False)
    print(f"wrote monthly congestion ({len(monthly)} port-months) -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stream-sample Marine Cadastre AIS to a tiny occupancy series.")
    ap.add_argument("--years", default="2015-2025", help="e.g. 2015-2025 or 2019,2020")
    ap.add_argument("--months", default="1-12", help="e.g. 1-12 or 1,6")
    ap.add_argument("--days-per-month", type=int, default=8)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out-dir", default="data/processed/ais_sampled_2015_2025")
    ap.add_argument("--keep-pings", action="store_true", help="also save port observations (more disk)")
    args = ap.parse_args()

    def parse_range(s: str) -> list[int]:
        out: list[int] = []
        for part in s.split(","):
            if "-" in part:
                a, b = part.split("-"); out += list(range(int(a), int(b) + 1))
            else:
                out.append(int(part))
        return out

    years = parse_range(args.years)
    months = parse_range(args.months)
    os.makedirs(args.out_dir, exist_ok=True)
    manifest_path = os.path.join(args.out_dir, "manifest.csv")
    summary_path = os.path.join(args.out_dir, "daily_port_summary.csv")
    monthly_path = os.path.join(args.out_dir, "monthly_congestion.csv")
    pings_dir = os.path.join(args.out_dir, "_pings") if args.keep_pings else None

    done = load_done(manifest_path)
    tasks = [(y, m, d) for y in years for m in months for d in sample_days(y, m, args.days_per_month)
             if f"{y}-{m:02d}-{d:02d}" not in done]
    print(f"years={years[0]}..{years[-1]} months={months} days/month={args.days_per_month}")
    print(f"{len(tasks)} files to fetch ({len(done)} already done). workers={args.workers}")
    if not tasks:
        aggregate_monthly(summary_path, monthly_path)
        return

    lock = threading.Lock()
    man_new = not os.path.exists(manifest_path)
    sum_new = not os.path.exists(summary_path)
    t_start = time.time()
    n_ok = n_miss = n_err = 0

    with open(manifest_path, "a", newline="") as mf, open(summary_path, "a", newline="") as sf, \
            ThreadPoolExecutor(max_workers=args.workers) as ex:
        if man_new:
            mf.write("date,url,status,rows,seconds,error\n")
        if sum_new:
            sf.write("date,Port,unique_vessels,n_obs\n")
        mf.flush(); sf.flush()

        futures = {ex.submit(process_day, y, m, d, pings_dir): (y, m, d) for (y, m, d) in tasks}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            with lock:
                err = str(r.get("error", "")).replace(",", ";").replace("\n", " ")
                mf.write(f"{r['date']},{r['url']},{r['status']},{r['rows']},{r['seconds']},{err}\n")
                for s in r["summary"]:
                    sf.write(f"{s['date']},{s['Port']},{s['unique_vessels']},{s['n_obs']}\n")
                if i % 10 == 0:
                    mf.flush(); sf.flush()
            n_ok += r["status"] == "ok"; n_miss += r["status"] == "missing"; n_err += r["status"] == "error"
            if i % 20 == 0 or i == len(futures):
                rate = i / max(time.time() - t_start, 1e-9)
                eta_h = (len(futures) - i) / rate / 3600
                print(f"  {i}/{len(futures)}  ok={n_ok} missing={n_miss} err={n_err}  "
                      f"{rate*60:.1f} files/min  ETA {eta_h:.1f} h", flush=True)

    aggregate_monthly(summary_path, monthly_path)
    print(f"done in {(time.time()-t_start)/3600:.2f} h. ok={n_ok} missing={n_miss} err={n_err}")


if __name__ == "__main__":
    main()
