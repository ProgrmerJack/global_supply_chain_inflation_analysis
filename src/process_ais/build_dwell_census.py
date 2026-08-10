"""
Full daily-census dwell-time builder (2015-2025 CSV/zst era), disk-light & resumable.

Unlike stream_sample_ais.py (8-day occupancy sample), this downloads EVERY day so we
can measure true per-vessel dwell time (entry->exit within a port-month) — the metric
the manuscript describes. To stay disk-light across a multi-day run it works ONE MONTH
at a time: download every day of the month to a temp file, extract only the 5-port
cargo/tanker pings (with the 2015-2017 Cargo-field vessel-type fix), delete the raw
file, hold just that month's tiny port-ping set in memory, compute monthly dwell
metrics, append them, and move on. Peak disk = one ~300 MB temp file; permanent output
= a few thousand summary rows.

Reuses the validated chain:
    stream_sample_ais.download / url_for      (downloader)
    extract_port_observations.extract_*       (port + vessel-type filter, Cargo fix)
    compute_dwell_metrics.compute/aggregate   (dwell logic verified against 2022)

Resumability: month_manifest.csv records coverage per month. A month is "done" when no
day errored (all days ok or permanently 404-missing); re-running retries error months.

Outputs (under --out-dir, default data/processed/ais_dwell_census/):
    monthly_dwell.csv     per (Port, YearMonth): UniqueVessels, Mean/MedianDwellDays,
                          ... plus days_ok / days_total coverage
    month_manifest.csv    per YearMonth: days_total, days_ok, days_missing, days_error
"""

from __future__ import annotations

import argparse
import calendar
import io
import os
import shutil
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from stream_sample_ais import download, url_for  # noqa: E402
from extract_port_observations import (  # noqa: E402
    CANONICAL_PING_COLUMNS,
    REJECTION_COLUMNS,
    _ALIASES,
    assign_pings_to_safe_port_areas,
    deduplicate_pings,
    extract_from_dataframe,
    normalise_pings,
)
from compute_dwell_metrics import compute_vessel_dwell, aggregate_monthly  # noqa: E402
from mode_time import assign_mode_labels, compute_mode_intervals, aggregate_monthly_mode_time, load_mode_zones  # noqa: E402
from source_manifest import build_file_manifest_record_from_counts  # noqa: E402

# every source-column alias we may need for extraction + dwell (lowercase)
NEEDED = {a for alts in _ALIASES.values() for a in alts}


def ingest_filtered_chunks(
    chunks,
    *,
    source_file: str,
    port_complex_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Canonicalise already port-filtered chunks without a second source parser."""
    accepted_parts = []
    rejected_parts = []
    raw_row_count = 0
    for chunk in chunks:
        accepted, rejected = normalise_pings(
            chunk,
            source_file=source_file,
            port_complex_id=port_complex_id,
        )
        if len(rejected):
            rejected = rejected.copy()
            rejected["row_number"] = rejected["row_number"] + raw_row_count
            rejected_parts.append(rejected)
        if len(accepted):
            accepted_parts.append(accepted)
        raw_row_count += len(chunk)

    accepted = (
        deduplicate_pings(pd.concat(accepted_parts, ignore_index=True))
        if accepted_parts
        else pd.DataFrame(columns=CANONICAL_PING_COLUMNS)
    )
    rejected = (
        pd.concat(rejected_parts, ignore_index=True).reindex(columns=REJECTION_COLUMNS)
        if rejected_parts
        else pd.DataFrame(columns=REJECTION_COLUMNS)
    )
    return accepted, rejected, raw_row_count


def ingest_national_chunks(
    chunks,
    *,
    source_file: str,
    port_areas,
    assignment_coverage: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Stream one national AIS file into safe port areas with complete parse accounting."""
    assigned_parts = []
    raw_row_count = accepted_row_count = rejected_row_count = 0
    rejection_counts: dict[str, int] = {}
    first_timestamp = last_timestamp = None
    for chunk in chunks:
        accepted, rejected = normalise_pings(
            chunk,
            source_file=source_file,
            port_complex_id="__national_source__",
        )
        raw_row_count += len(chunk)
        accepted_row_count += len(accepted)
        rejected_row_count += len(rejected)
        for reason, count in rejected["reason"].value_counts().items():
            rejection_counts[str(reason)] = rejection_counts.get(str(reason), 0) + int(count)
        if len(accepted):
            timestamp_min = accepted["timestamp"].min()
            timestamp_max = accepted["timestamp"].max()
            first_timestamp = timestamp_min if first_timestamp is None else min(first_timestamp, timestamp_min)
            last_timestamp = timestamp_max if last_timestamp is None else max(last_timestamp, timestamp_max)
            assigned = assign_pings_to_safe_port_areas(accepted, port_areas, assignment_coverage)
            if len(assigned):
                assigned_parts.append(assigned)

    if raw_row_count != accepted_row_count + rejected_row_count:
        raise RuntimeError("national AIS parse accounting does not reconcile source rows")
    pings = (
        deduplicate_pings(pd.concat(assigned_parts, ignore_index=True))
        if assigned_parts
        else pd.DataFrame(columns=CANONICAL_PING_COLUMNS)
    )
    return pings, {
        "raw_row_count": raw_row_count,
        "accepted_row_count": accepted_row_count,
        "rejected_row_count": rejected_row_count,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "first_timestamp": first_timestamp.isoformat() if first_timestamp is not None else None,
        "last_timestamp": last_timestamp.isoformat() if last_timestamp is not None else None,
    }


def ingest_national_file(
    raw_path: str | Path,
    *,
    source_url: str,
    retrieved_at: str,
    port_areas,
    assignment_coverage: pd.DataFrame,
    parser_version: str = "national-ais-v1",
    source_file: str | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Ingest one retained NOAA source file and bind its stream summary to source provenance."""
    raw_path = Path(raw_path)
    source_file = source_file or raw_path.name
    pings, summary = ingest_national_chunks(
        _read_chunks(str(raw_path)),
        source_file=source_file,
        port_areas=port_areas,
        assignment_coverage=assignment_coverage,
    )
    manifest = build_file_manifest_record_from_counts(
        raw_path,
        source_url=source_url,
        retrieved_at=retrieved_at,
        parser_version=parser_version,
        port_complex_id="__national_source__",
        source_file=source_file,
        **summary,
    )
    return pings, manifest


def write_immutable_parquet(pings: pd.DataFrame, destination: str | Path) -> None:
    """Atomically create one parquet artifact and refuse any replacement."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"immutable artifact already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.stem}.", suffix=".tmp", dir=destination.parent)
    os.close(descriptor)
    try:
        pings.to_parquet(temporary, index=False)
        if destination.exists():
            raise FileExistsError(f"immutable artifact already exists: {destination}")
        os.rename(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _read_chunks(path: str):
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
            yield from pd.read_csv(io.TextIOWrapper(reader, encoding="utf-8", errors="replace"), **kw)
    else:
        yield from pd.read_csv(path, **kw)


def fetch_day_obs(
    year: int,
    month: int,
    day: int,
    retries: int,
    timeout: int,
    max_seconds: int,
    backend: str,
    connections: int,
):
    """Download one day, return (day, status, port-obs DataFrame|None, error)."""
    url = url_for(year, month, day)
    suffix = ".zip" if url.endswith(".zip") else (".csv.zst" if url.endswith(".zst") else ".csv")
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        download(
            url,
            tmp,
            retries=retries,
            timeout=timeout,
            max_seconds=max_seconds,
            backend=backend,
            connections=connections,
        )
        parts = [extract_from_dataframe(ch) for ch in _read_chunks(tmp)]
        parts = [p for p in parts if len(p)]
        obs = pd.concat(parts, ignore_index=True) if parts else None
        return day, "ok", obs, ""
    except Exception as e:  # noqa: BLE001
        status = "missing" if "404" in str(e) else "error"
        return day, status, None, str(e)[:200]
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def process_month(
    year: int,
    month: int,
    workers: int,
    mode_zones,
    retries: int,
    timeout: int,
    max_seconds: int,
    backend: str,
    connections: int,
):
    """Download every day of the month, return dwell metrics, mode metrics, classified pings, and coverage."""
    days = list(range(1, calendar.monthrange(year, month)[1] + 1))
    ym = f"{year}-{month:02d}"
    obs_parts = []
    cov = {"YearMonth": ym, "days_total": len(days), "days_ok": 0, "days_missing": 0, "days_error": 0}
    errs = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(fetch_day_obs, year, month, d, retries, timeout, max_seconds, backend, connections): d
            for d in days
        }
        for fut in as_completed(futs):
            _d, status, obs, err = fut.result()
            cov[f"days_{status}"] = cov.get(f"days_{status}", 0) + 1
            if status == "error":
                errs.append(err)
            if obs is not None and len(obs):
                obs_parts.append(obs)
    cov["sample_error"] = errs[0] if errs else ""
    if cov["days_ok"] != cov["days_total"] or cov.get("days_error", 0) or cov.get("days_missing", 0):
        return None, None, None, cov
    if not obs_parts:
        return None, None, None, cov
    obs = pd.concat(obs_parts, ignore_index=True)
    classified = assign_mode_labels(obs, mode_zones)
    mode_monthly = aggregate_monthly_mode_time(compute_mode_intervals(classified))
    monthly = aggregate_monthly(compute_vessel_dwell(obs))
    monthly = monthly[monthly["YearMonth"] == ym].copy()
    monthly["days_ok"] = cov["days_ok"]
    monthly["days_total"] = cov["days_total"]
    return monthly, mode_monthly, classified, cov


def _parse_range(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-"); out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def complete_months_from_manifest(manifest_path: str) -> set[str]:
    if not os.path.exists(manifest_path):
        return set()
    m = pd.read_csv(manifest_path)
    complete = (
        m["days_ok"].eq(m["days_total"])
        & m["days_error"].fillna(0).eq(0)
        & m["days_missing"].fillna(0).eq(0)
    )
    return set(m.loc[complete, "YearMonth"].astype(str))


def prune_incomplete_outputs(out_dir: str, dwell_path: str, mode_path: str, manifest_path: str) -> set[str]:
    """Remove stale partial rows and ping partitions for months not complete in the manifest."""
    if not os.path.exists(manifest_path):
        return set()
    complete = complete_months_from_manifest(manifest_path)
    m = pd.read_csv(manifest_path)
    attempted = set(m["YearMonth"].astype(str))
    incomplete = attempted - complete

    def prune_csv(path: str, keys: list[str]) -> None:
        if not os.path.exists(path):
            return
        df = pd.read_csv(path)
        if "YearMonth" not in df.columns:
            return
        before = len(df)
        df = df[df["YearMonth"].astype(str).isin(complete)].copy()
        subset = [k for k in keys if k in df.columns]
        if subset:
            df = df.drop_duplicates(subset=subset, keep="last")
        if len(df) != before:
            tmp = f"{path}.tmp"
            df.to_csv(tmp, index=False)
            os.replace(tmp, path)

    prune_csv(dwell_path, ["Port", "YearMonth"])
    prune_csv(mode_path, ["MMSI", "Port", "YearMonth"])

    ping_root = os.path.join(out_dir, "port_pings")
    for ym in incomplete:
        year, month = ym.split("-")
        ping_dir = os.path.join(ping_root, f"year={year}", f"month={month}")
        if os.path.exists(ping_dir):
            shutil.rmtree(ping_dir)
    return complete


def main() -> None:
    ap = argparse.ArgumentParser(description="Full daily-census dwell builder (2015+ CSV era).")
    ap.add_argument("--years", default="2015-2025")
    ap.add_argument("--months", default="1-12")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out-dir", default="data/processed/ais_dwell_census")
    ap.add_argument("--mode-zones", default="config/geometry/port_mode_zones.geojson")
    ap.add_argument("--mode-output", default="monthly_mode_time.csv")
    ap.add_argument("--retain-pings", action="store_true", help="write curated in-port pings as partitioned parquet")
    ap.add_argument("--download-retries", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--max-seconds", type=int, default=1800)
    ap.add_argument("--download-backend", choices=["auto", "aria2", "urllib"], default="auto")
    ap.add_argument("--aria2-connections", type=int, default=16)
    args = ap.parse_args()

    years, months = _parse_range(args.years), _parse_range(args.months)
    os.makedirs(args.out_dir, exist_ok=True)
    dwell_path = os.path.join(args.out_dir, "monthly_dwell.csv")
    mode_path = os.path.join(args.out_dir, args.mode_output)
    manifest_path = os.path.join(args.out_dir, "month_manifest.csv")
    mode_zones = load_mode_zones(args.mode_zones)

    done = prune_incomplete_outputs(args.out_dir, dwell_path, mode_path, manifest_path)
    todo = [(y, m) for y in years for m in months if f"{y}-{m:02d}" not in done]
    print(
        f"{len(todo)} month(s) to process ({len(done)} complete). workers={args.workers} "
        f"retries={args.download_retries} timeout={args.timeout}s max_seconds={args.max_seconds}s "
        f"backend={args.download_backend} aria2_connections={args.aria2_connections}"
    )
    if not todo:
        return

    man_new = not os.path.exists(manifest_path)
    dwell_new = not os.path.exists(dwell_path)
    mode_new = not os.path.exists(mode_path)
    t0 = time.time()
    with open(manifest_path, "a", newline="") as mf, \
            open(dwell_path, "a", newline="") as df_out, \
            open(mode_path, "a", newline="") as mode_out:
        if man_new:
            mf.write("YearMonth,days_total,days_ok,days_missing,days_error,sample_error\n")
        for i, (y, m) in enumerate(todo, 1):
            monthly, mode_monthly, classified, cov = process_month(
                y,
                m,
                args.workers,
                mode_zones,
                args.download_retries,
                args.timeout,
                args.max_seconds,
                args.download_backend,
                args.aria2_connections,
            )
            mf.write(f"{cov['YearMonth']},{cov['days_total']},{cov['days_ok']},"
                     f"{cov.get('days_missing',0)},{cov.get('days_error',0)},"
                     f"{str(cov.get('sample_error','')).replace(',',';')[:120]}\n")
            mf.flush()
            complete = cov["days_ok"] == cov["days_total"] and not cov.get("days_error", 0) and not cov.get("days_missing", 0)
            if complete and monthly is not None and len(monthly):
                monthly.to_csv(df_out, header=dwell_new, index=False)
                dwell_new = False
                df_out.flush()
            if complete and mode_monthly is not None and len(mode_monthly):
                mode_monthly.to_csv(mode_out, header=mode_new, index=False)
                mode_new = False
                mode_out.flush()
            if complete and args.retain_pings and classified is not None and len(classified):
                ping_dir = os.path.join(args.out_dir, "port_pings", f"year={y}", f"month={m:02d}")
                os.makedirs(ping_dir, exist_ok=True)
                classified.to_parquet(os.path.join(ping_dir, "port_pings.parquet"), index=False)
            rate = i / max(time.time() - t0, 1e-9)
            eta_h = (len(todo) - i) / rate / 3600
            print(f"  {cov['YearMonth']}: days_ok={cov['days_ok']}/{cov['days_total']} "
                  f"err={cov.get('days_error',0)}  [{i}/{len(todo)}]  ETA {eta_h:.1f} h", flush=True)
    print(f"done in {(time.time()-t0)/3600:.2f} h.")


if __name__ == "__main__":
    main()
