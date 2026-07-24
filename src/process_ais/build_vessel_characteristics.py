"""Per-MMSI vessel-characteristics table from a sparse NOAA AIS re-sample (data-gap recovery).

The full 2015-2025 census retained pings WITHOUT vessel size / navigation status (the canonical schema dropped
them; fixed going forward in extract_port_observations). Vessel size (length/width/draft) and IMO are
NEAR-CONSTANT per MMSI, so they are recoverable from a SPARSE sample: ~1 day/month, deterministic and varied
across days-of-month, streams ~30 GB (disk-light) and captures essentially every recurring vessel that visited
our complexes. Source is NOAA AIS static broadcasts — the SAME provenance as the census pings (single-source,
reproducible, defensible), not a third-party registry.

The retained sparse pings (kept under data/interim/vessel_static_sample/, WITH status) also serve as the
navigation-status state-validation sample — so neither vessel size nor state validation ever needs another
download. Emissions then proceed from retained state-time (per MMSI) x this table / an external registry
(per MMSI) x EPA factors, with no AIS re-download.

Outputs:
  data/interim/vessel_static_sample/year=*/month=*/pings_*.parquet   (retained sparse pings, status-bearing)
  data/processed/vessel_characteristics.csv   [mmsi, length_m, width_m, draft_m, vessel_type, imo, n_obs, first_year, last_year]

Run from repo root (resumable, ~1-3 h for ~30 GB):
  python src/process_ais/build_vessel_characteristics.py --years 2015-2025 --workers 8
  python src/process_ais/build_vessel_characteristics.py --build-table   # (re)build the table from the sample
"""

from __future__ import annotations

import argparse
import calendar
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

try:
    from .build_national_panel import run_ingestion, _parse_range
    from ..governance.access import assert_confirmatory_unlocked
except ImportError:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[1]))
    sys.path.insert(0, str(_here.parents[0]))
    from build_national_panel import run_ingestion, _parse_range  # type: ignore
    from governance.access import assert_confirmatory_unlocked  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data/interim/vessel_static_sample"
CHARS_OUT = ROOT / "data/processed/vessel_characteristics.csv"


def sample_static_dates(years: list[int]) -> list[date]:
    """One deterministic, VARIED day per month (rotates day-of-month) so recurring vessels are caught
    regardless of their monthly rotation, without a day-1 sampling bias. ~12 days/year -> ~132 for 2015-2025."""
    out: list[date] = []
    for i, y in enumerate(years):
        for m in range(1, 13):
            dim = calendar.monthrange(y, m)[1]
            day = ((i * 12 + m) * 7) % dim + 1     # deterministic spread over days-of-month
            out.append(date(y, m, day))
    return out


def build_characteristics_table(sample_dir: Path = SAMPLE_DIR, out_path: Path = CHARS_OUT) -> pd.DataFrame:
    """Aggregate the sparse sample to one row per MMSI (median size, modal type/IMO) via DuckDB streaming."""
    import duckdb

    sample_dir = Path(sample_dir)
    if not any(sample_dir.glob("year=*/month=*/*.parquet")):
        raise ValueError("no sampled pings found; run the sparse ingestion first")
    glob = (sample_dir / "year=*" / "month=*" / "*.parquet").as_posix()
    spill = Path(tempfile.gettempdir()) / "duckdb_vessel_chars"
    spill.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET memory_limit='4GB'")
    con.execute(f"SET temp_directory='{spill.as_posix()}'")
    query = f"""
        WITH s AS (
            SELECT mmsi, length, width, draft, imo, vessel_type,
                   strftime(timestamp, '%Y') AS yr
            FROM read_parquet('{glob}')
            WHERE mmsi IS NOT NULL
        )
        SELECT mmsi,
               median(length) FILTER (WHERE length > 0) AS length_m,
               median(width)  FILTER (WHERE width  > 0) AS width_m,
               median(draft)  FILTER (WHERE draft  > 0) AS draft_m,
               mode(vessel_type) AS vessel_type,
               mode(imo) FILTER (WHERE imo > 0) AS imo,
               count(*) AS n_obs,
               min(yr) AS first_year,
               max(yr) AS last_year
        FROM s GROUP BY mmsi ORDER BY mmsi
    """
    table = con.execute(query).df()
    con.close()

    out_path = Path(out_path)
    assert_confirmatory_unlocked(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_path, index=False, lineterminator="\n")
    have_size = int(table["length_m"].notna().sum())
    print(f"vessel characteristics: {len(table)} MMSIs ({have_size} with a size), "
          f"years {table.first_year.min()}..{table.last_year.max()} -> {out_path}")
    return table


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Recover per-MMSI vessel size/IMO/status from a sparse AIS re-sample.")
    ap.add_argument("--years", default="2015-2025")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--build-table", action="store_true", help="only (re)build the table from the retained sample")
    args = ap.parse_args()

    if not args.build_table:
        dates = sample_static_dates(_parse_range(args.years))
        run_ingestion([], [], 0, pings_dir=SAMPLE_DIR, workers=args.workers, dates=dates)
    build_characteristics_table(SAMPLE_DIR)


if __name__ == "__main__":
    main()
