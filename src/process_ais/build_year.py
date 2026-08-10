"""
Driver: a directory of downloaded daily AIS files -> one year's congestion metrics.

This is the single command to run per year after the raw AIS download lands. It
chains the validated pieces:

    raw daily files  --extract_port_observations-->  port observations
                     --compute_dwell_metrics------>  vessel dwell + monthly metrics

and writes outputs in the SAME layout/filenames as the verified 2022 data, so that the
per-year occupancy/congestion index automatically extends the long monthly series.

SUPERSEDED: that consumer was `src/index/build_ais_congestion_index.py`, which was retired to
`_archive/legacy_src/index/` on 2026-08-05 along with the per-year `ais_*_analysis/` inputs it read.
The live congestion measure is the dwell census (`build_dwell_census.py` -> `build_dwell_index.py`).

Example:
    .venv/Scripts/python.exe src/process_ais/build_year.py \
        --year 2018 --raw-dir data/raw/ais/2018

Outputs (under <out-dir>/ais_<year>_analysis/):
    ais_<year>_raw_port_observations.parquet
    ais_<year>_vessel_dwell_times.parquet
    ais_<year>_monthly_port_metrics.parquet
"""

from __future__ import annotations

import argparse
import glob
import os

import pandas as pd

from extract_port_observations import extract_file
from compute_dwell_metrics import process_port_observations

# default filename patterns by era (case-insensitive glob handled below)
DEFAULT_PATTERNS = ["AIS_*.csv", "ais-*.csv", "ais-*.csv.zst", "AIS_*.csv.gz", "*.csv", "*.csv.zst"]


def find_files(raw_dir: str, pattern: str | None) -> list[str]:
    if pattern:
        return sorted(glob.glob(os.path.join(raw_dir, pattern)))
    seen: set[str] = set()
    out: list[str] = []
    for pat in DEFAULT_PATTERNS:
        for f in glob.glob(os.path.join(raw_dir, pat)):
            if f not in seen:
                seen.add(f)
                out.append(f)
    return sorted(out)


def build_year(year: int, raw_dir: str, out_dir: str, pattern: str | None, chunksize: int) -> None:
    files = find_files(raw_dir, pattern)
    if not files:
        raise FileNotFoundError(f"No AIS files found in {raw_dir} (pattern={pattern!r}).")
    print(f"[{year}] {len(files)} daily files in {raw_dir}")

    analysis_dir = os.path.join(out_dir, f"ais_{year}_analysis")
    os.makedirs(analysis_dir, exist_ok=True)

    parts, failed = [], []
    for i, f in enumerate(files, 1):
        try:
            obs = extract_file(f, chunksize=chunksize)
            if len(obs):
                parts.append(obs)
            if i % 20 == 0 or i == len(files):
                print(f"  {i}/{len(files)} files; cumulative in-port rows: {sum(map(len, parts)):,}")
        except Exception as e:  # noqa: BLE001 — keep going, record the bad file
            failed.append((os.path.basename(f), str(e)))
            print(f"  [skip] {os.path.basename(f)}: {e}")

    if not parts:
        raise RuntimeError(f"[{year}] no in-port observations extracted from {len(files)} files.")

    obs = pd.concat(parts, ignore_index=True)
    raw_out = os.path.join(analysis_dir, f"ais_{year}_raw_port_observations.parquet")
    obs.to_parquet(raw_out, index=False)
    print(f"[{year}] wrote {len(obs):,} port observations -> {raw_out}")

    dwell, monthly = process_port_observations(obs)
    dwell_out = os.path.join(analysis_dir, f"ais_{year}_vessel_dwell_times.parquet")
    monthly_out = os.path.join(analysis_dir, f"ais_{year}_monthly_port_metrics.parquet")
    dwell.to_parquet(dwell_out, index=False)
    monthly.to_parquet(monthly_out, index=False)
    print(f"[{year}] wrote dwell episodes -> {dwell_out}")
    print(f"[{year}] wrote monthly metrics ({len(monthly)} port-months) -> {monthly_out}")

    if failed:
        log = os.path.join(analysis_dir, f"ais_{year}_excluded_files.csv")
        pd.DataFrame(failed, columns=["file", "reason"]).to_csv(log, index=False)
        print(f"[{year}] {len(failed)} files skipped; logged -> {log}")

    print(f"[{year}] done. Rebuild the dwell census to extend the series.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build one year's AIS congestion metrics.")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--raw-dir", required=True, help="directory of downloaded daily AIS files")
    ap.add_argument("--out-dir", default="data/processed", help="processed output root")
    ap.add_argument("--pattern", default=None, help="glob for daily files (default: auto)")
    ap.add_argument("--chunksize", type=int, default=1_000_000)
    args = ap.parse_args()
    build_year(args.year, args.raw_dir, args.out_dir, args.pattern, args.chunksize)


if __name__ == "__main__":
    main()
