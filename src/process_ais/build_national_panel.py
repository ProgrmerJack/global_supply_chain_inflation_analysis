"""National AIS ingestion + monthly activity panel (Phase 1, Task 5 driver; docs/implementation_plan.md §5).

Disk-light, resumable, confirmatory-guarded batch ingestion for the frozen national port universe. It reuses
the validated chain (`stream_sample_ais.download`/`url_for`, `build_dwell_census.ingest_national_file`) —
there is no second downloader or parser. Each sampled day is streamed to a temp file, filtered to the
assignable USACE port complexes, its curated in-box pings are RETAINED (Hive parquet by year/month), and the
raw file is deleted. Retained pings are the reconstruction basis: monthly activity, dwell, calls and (once
state zones are frozen) vessel states are all recomputable from them, and they are small (~few MB/day).

Outputs (under the confirmatory-guarded Phase-0 tree):
  data/interim/national_pings/year=YYYY/month=MM/pings_YYYY-MM-DD.parquet
  data/interim/national_pings/ingestion_manifest.csv   (resumable ledger)
  data/processed/national_activity_month.csv           (per complex-month)

Run from repo root (resumable; re-run to continue):
  python src/process_ais/build_national_panel.py --years 2021-2021 --months 1-12 --days-per-month 8
  python src/process_ais/build_national_panel.py --build-panel        # (re)build the activity panel from retained pings
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow.dataset as ds

try:
    from .stream_sample_ais import download, url_for, sample_days
    from .build_dwell_census import ingest_national_file, write_immutable_parquet
    from .port_call_segmentation import PRIMARY_GAP_HOURS
    from ..governance.access import (
        assert_confirmatory_unlocked,
        assert_nature_recovery_unlocked,
    )
except ImportError:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[1]))   # src/
    sys.path.insert(0, str(_here.parents[0]))   # src/process_ais/
    from stream_sample_ais import download, url_for, sample_days  # type: ignore
    from build_dwell_census import ingest_national_file, write_immutable_parquet  # type: ignore
    from port_call_segmentation import PRIMARY_GAP_HOURS  # type: ignore
    from governance.access import (  # type: ignore
        assert_confirmatory_unlocked,
        assert_nature_recovery_unlocked,
    )

ROOT = Path(__file__).resolve().parents[2]
PHASE0 = ROOT
DEFAULT_PORT_AREAS = PHASE0 / "config/geometry/port_areas_usace.geojson"
DEFAULT_ASSIGNMENT_COVERAGE = PHASE0 / "config/registries/port_area_assignment_coverage.csv"
DEFAULT_PINGS_DIR = PHASE0 / "data/interim/national_pings"
DEFAULT_PANEL_PATH = PHASE0 / "data/processed/national_activity_month.csv"
MANIFEST_NAME = "ingestion_manifest.csv"
MANIFEST_COLUMNS = ["date", "url", "status", "raw_rows", "retained_pings", "n_complexes", "seconds", "error"]
CALL_COLUMNS = ["port_complex_id", "year_month", "port_calls", "cargo_port_calls", "freight_port_calls"]
PORT_CALL_FILES_PER_BATCH = 7  # bounded state sort; avoids both a global sort and per-file reader overhead


def _parse_range(spec: str) -> list[int]:
    out: list[int] = []
    for part in str(spec).split(","):
        if "-" in part:
            lo, hi = part.split("-")
            out += list(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def load_done(manifest_path: Path) -> set[str]:
    """Dates already ingested (ok) or permanently missing (404); error dates are retried."""
    if not Path(manifest_path).exists():
        return set()
    m = pd.read_csv(manifest_path)
    return set(m.loc[m["status"].isin(["ok", "missing"]), "date"].astype(str))


def load_ingestion_port_areas(path: Path | str) -> gpd.GeoDataFrame:
    """Load ordinary port areas or the outer rows of a nested domain file."""
    areas = gpd.read_file(path)
    if "domain" in areas.columns:
        unknown = sorted(set(areas.domain) - {"coastal_inner", "coastal_outer"})
        if unknown:
            raise ValueError(f"unknown nested coastal domains: {unknown}")
        areas = areas.loc[areas.domain.eq("coastal_outer")].copy()
    if areas.port_complex_id.duplicated().any():
        raise ValueError("ingestion port areas require one geometry per port")
    return areas


def pending_dates(years: list[int], months: list[int], days_per_month: int, done: set[str]) -> list[date]:
    out: list[date] = []
    for year in years:
        for month in months:
            for day in sample_days(year, month, days_per_month):
                iso = f"{year}-{month:02d}-{day:02d}"
                if iso not in done:
                    out.append(date(year, month, day))
    return out


def ingest_date(
    target: date,
    pings_dir: Path,
    *,
    port_areas,
    assignment_coverage,
    parser_version: str = "national-ais-v1",
) -> dict:
    """Stream one national day, retain curated in-box pings, delete the raw file. Never raises on a bad day."""
    url = url_for(target.year, target.month, target.day)
    out = (
        pings_dir / f"year={target.year}" / f"month={target.month:02d}"
        / f"pings_{target.isoformat()}.parquet"
    )
    if out.exists():
        existing = pd.read_parquet(out, columns=["timestamp", "port_complex_id", "source_file"])
        timestamps = pd.to_datetime(existing["timestamp"], errors="coerce", utc=True)
        expected_source = url.rsplit("/", 1)[-1]
        if timestamps.isna().any() or (len(existing) and set(timestamps.dt.date) != {target}):
            raise ValueError(f"existing immutable artifact has invalid timestamps: {out}")
        if len(existing) and set(existing["source_file"].astype(str)) != {expected_source}:
            raise ValueError(f"existing immutable artifact has wrong source: {out}")
        return {
            "date": target.isoformat(), "url": url, "status": "ok", "raw_rows": "",
            "retained_pings": int(len(existing)),
            "n_complexes": int(existing["port_complex_id"].nunique()), "seconds": 0.0,
            "error": "recovered existing immutable artifact after interrupted manifest append",
        }
    suffix = ".zip" if url.endswith(".zip") else (".csv.zst" if url.endswith(".zst") else ".csv")
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    t0 = time.time()
    try:
        download(url, tmp)
        pings, manifest = ingest_national_file(
            tmp,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            port_areas=port_areas,
            assignment_coverage=assignment_coverage,
            parser_version=parser_version,
            source_file=url.rsplit("/", 1)[-1],
        )
        n_complexes = int(pings["port_complex_id"].nunique()) if len(pings) else 0
        write_immutable_parquet(pings, out)
        return {"date": target.isoformat(), "url": url, "status": "ok",
                "raw_rows": int(manifest["raw_row_count"]), "retained_pings": int(len(pings)),
                "n_complexes": n_complexes, "seconds": round(time.time() - t0, 1), "error": ""}
    except Exception as exc:  # noqa: BLE001
        status = "missing" if "404" in str(exc) else "error"
        return {"date": target.isoformat(), "url": url, "status": status, "raw_rows": 0,
                "retained_pings": 0, "n_complexes": 0, "seconds": round(time.time() - t0, 1), "error": str(exc)[:200]}
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def run_ingestion(
    years: list[int],
    months: list[int],
    days_per_month: int,
    *,
    pings_dir: Path = DEFAULT_PINGS_DIR,
    port_areas_path: Path = DEFAULT_PORT_AREAS,
    assignment_coverage_path: Path = DEFAULT_ASSIGNMENT_COVERAGE,
    workers: int = 4,
    dates: list | None = None,
    unlock_guard=assert_confirmatory_unlocked,
    parser_version: str = "national-ais-v1",
) -> Path:
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pings_dir = Path(pings_dir)
    unlock_guard(pings_dir)   # fail closed unless the applicable registration is unlocked
    pings_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = pings_dir / MANIFEST_NAME
    areas = load_ingestion_port_areas(port_areas_path)
    coverage = pd.read_csv(assignment_coverage_path, keep_default_na=False)

    done = load_done(manifest_path)
    tasks = ([d for d in dates if d.isoformat() not in done] if dates is not None
             else pending_dates(years, months, days_per_month, done))
    print(f"national ingestion: {len(tasks)} day(s) to fetch ({len(done)} already done), workers={workers}. "
          f"~241 MB/day => ~{len(tasks) * 0.24:.0f} GB streamed, ~{len(tasks) * 60 / 3600 / max(workers,1):.1f} h",
          flush=True)
    lock = threading.Lock()
    header_needed = not manifest_path.exists()
    done_count = 0
    # Each day writes its own parquet (no contention); only the manifest append is serialized.
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(
            ingest_date,
            t,
            pings_dir,
            port_areas=areas,
            assignment_coverage=coverage,
            parser_version=parser_version,
        ): t
                   for t in tasks}
        for fut in as_completed(futures):
            row = fut.result()
            with lock:
                pd.DataFrame([row], columns=MANIFEST_COLUMNS).to_csv(
                    manifest_path, mode="a", header=header_needed, index=False, lineterminator="\n")
                header_needed = False
                done_count += 1
                print(f"  [{done_count}/{len(tasks)}] {row['date']} {row['status']} "
                      f"retained={row['retained_pings']:,} complexes={row['n_complexes']} {row['seconds']}s",
                      flush=True)
    return manifest_path


def _stream_port_call_counts(pings_dir: Path) -> pd.DataFrame:
    """Count 24-hour-gap calls one retained source day at a time.

    Only the prior ping for each vessel-port pair survives between files.  This is intentionally separate
    from the DuckDB panel aggregation: a global window sort over the entire census exceeded safe memory
    during the full rebuild.
    """
    files = sorted(pings_dir.glob("year=*/month=*/*.parquet"), key=lambda path: path.as_posix())
    prior = pd.DataFrame(
        {
            "port_complex_id": pd.Series(dtype="string"),
            "mmsi": pd.Series(dtype="int64"),
            "prior_timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
        }
    )
    count_parts = []
    keys = ["port_complex_id", "mmsi"]
    for start in range(0, len(files), PORT_CALL_FILES_PER_BATCH):
        file_batch = files[start:start + PORT_CALL_FILES_PER_BATCH]
        current = ds.dataset([str(path) for path in file_batch], format="parquet").to_table(
            columns=["port_complex_id", "mmsi", "timestamp", "vessel_type"]
        ).to_pandas()
        current["timestamp"] = pd.to_datetime(current["timestamp"], errors="coerce", utc=True)
        current["mmsi"] = pd.to_numeric(current["mmsi"], errors="coerce")
        current["vessel_type"] = pd.to_numeric(current["vessel_type"], errors="coerce")
        current = current.dropna(subset=["port_complex_id", "mmsi", "timestamp"]).copy()
        if current.empty:
            continue
        current["port_complex_id"] = current["port_complex_id"].astype("string")
        current["mmsi"] = current["mmsi"].astype("int64")
        batch = current.merge(prior, on=keys, how="left", validate="many_to_one")
        batch = batch.sort_values([*keys, "timestamp"], kind="stable")
        previous_in_batch = batch.groupby(keys, sort=False)["timestamp"].shift()
        batch["_prior_timestamp"] = previous_in_batch.where(previous_in_batch.notna(), batch["prior_timestamp"])
        starts = batch.loc[
            batch["_prior_timestamp"].isna()
            | ((batch["timestamp"] - batch["_prior_timestamp"]).dt.total_seconds() > PRIMARY_GAP_HOURS * 3600)
        ].copy()
        if not starts.empty:
            starts["year_month"] = starts["timestamp"].dt.strftime("%Y-%m")
            starts["_cargo"] = starts["vessel_type"].between(70, 79, inclusive="both")
            starts["_freight"] = starts["vessel_type"].between(70, 89, inclusive="both")
            count_parts.append(
                starts.groupby(["port_complex_id", "year_month"], as_index=False).agg(
                    port_calls=("mmsi", "size"),
                    cargo_port_calls=("_cargo", "sum"),
                    freight_port_calls=("_freight", "sum"),
                )
            )
        last_current = (
            current.sort_values([*keys, "timestamp"], kind="stable")
            .drop_duplicates(keys, keep="last")
            .rename(columns={"timestamp": "prior_timestamp"})[keys + ["prior_timestamp"]]
        )
        prior = (
            pd.concat([prior, last_current], ignore_index=True)
            .sort_values([*keys, "prior_timestamp"], kind="stable")
            .drop_duplicates(keys, keep="last")
            .reset_index(drop=True)
        )
    if not count_parts:
        return pd.DataFrame(columns=CALL_COLUMNS)
    calls = pd.concat(count_parts, ignore_index=True)
    calls = calls.groupby(["port_complex_id", "year_month"], as_index=False)[CALL_COLUMNS[2:]].sum()
    return calls.reindex(columns=CALL_COLUMNS)


def build_activity_panel(pings_dir: Path = DEFAULT_PINGS_DIR, out_path: Path = DEFAULT_PANEL_PATH,
                         memory_limit: str = "4GB") -> pd.DataFrame:
    """Outcome-blind monthly activity per complex, aggregated by DuckDB streaming directly over the retained
    parquet (spills to disk, so it scales to the full ~4000-day census without loading it all into RAM).

    Columns include monthly unique-vessel counts, 24-hour-gap port-call counts, source-day coverage and
    per-vessel residence spans.  AIS type 70-79 is the broad NMEA cargo class (not a container-ship label);
    80-89 is tanker.  Calls are assigned to their UTC start month and use the existing registered 24-hour
    absence rule from ``port_call_segmentation``.  All time handling is pinned to UTC for determinism.
    """
    import duckdb

    pings_dir = Path(pings_dir)
    if not any(pings_dir.glob("year=*/month=*/*.parquet")):
        raise ValueError("no retained national pings found; run ingestion first")
    glob = (pings_dir / "year=*" / "month=*" / "*.parquet").as_posix()
    spill = Path(tempfile.gettempdir()) / "duckdb_national_panel"
    spill.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")                    # deterministic UTC month/day extraction
    con.execute("SET preserve_insertion_order=false")    # lower peak memory
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{spill.as_posix()}'")   # spill to disk instead of OOM
    query = f"""
        WITH pings AS (
            SELECT port_complex_id, mmsi, timestamp AS ts,
                   strftime(timestamp, '%Y-%m') AS year_month,
                   strftime(timestamp, '%Y-%m-%d') AS day,
                   vessel_type AS vt
            FROM read_parquet('{glob}')
            WHERE mmsi IS NOT NULL AND timestamp IS NOT NULL AND port_complex_id IS NOT NULL
        ),
        per_vessel AS (
            SELECT port_complex_id, year_month, mmsi,
                   (epoch(max(ts)) - epoch(min(ts))) / 86400.0 AS dwell_days
            FROM pings GROUP BY 1, 2, 3
        ),
        ship AS (
            SELECT port_complex_id, year_month, sum(dwell_days) AS ship_days
            FROM per_vessel GROUP BY 1, 2
        ),
        base AS (
            SELECT port_complex_id, year_month,
                   count(DISTINCT mmsi) AS unique_vessels,
                   count(DISTINCT CASE WHEN vt >= 70 AND vt < 80 THEN mmsi END) AS unique_cargo_vessels,
                   count(*) AS n_pings,
                   count(DISTINCT day) AS days_sampled
            FROM pings GROUP BY 1, 2
        )
        SELECT b.port_complex_id, b.year_month, b.unique_vessels, b.unique_cargo_vessels,
               b.n_pings, b.days_sampled, s.ship_days
        FROM base b
        JOIN ship s USING (port_complex_id, year_month)
        ORDER BY b.port_complex_id, b.year_month
    """
    panel = con.execute(query).df()
    con.close()
    panel = panel.merge(_stream_port_call_counts(pings_dir), on=["port_complex_id", "year_month"],
                        how="left", validate="one_to_one")
    for column in ("unique_cargo_vessels", "port_calls", "cargo_port_calls", "freight_port_calls"):
        panel[column] = panel[column].fillna(0).astype("int64")
    out_path = Path(out_path)
    assert_confirmatory_unlocked(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(out_path, index=False, lineterminator="\n")
    print(f"activity panel: {len(panel)} complex-months, {panel.port_complex_id.nunique()} complexes, "
          f"months {panel.year_month.min()}..{panel.year_month.max()} -> {out_path}")
    return panel


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="National AIS ingestion + monthly activity panel (resumable, disk-light).")
    ap.add_argument("--years", default="2021-2021")
    ap.add_argument("--months", default="1-12")
    ap.add_argument("--days-per-month", type=int, default=31, help="31 = full every-day census (default); fewer = sample")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pings-dir", type=Path, default=DEFAULT_PINGS_DIR)
    ap.add_argument("--port-areas", type=Path, default=DEFAULT_PORT_AREAS)
    ap.add_argument("--assignment-coverage", type=Path, default=DEFAULT_ASSIGNMENT_COVERAGE)
    ap.add_argument(
        "--guard-scope",
        choices=("confirmatory", "nature-recovery"),
        default="confirmatory",
    )
    ap.add_argument("--parser-version", default="national-ais-v1")
    ap.add_argument("--ingest-only", action="store_true")
    ap.add_argument("--build-panel", action="store_true", help="only (re)build the activity panel from retained pings")
    args = ap.parse_args()

    if not args.build_panel:
        guard = (
            assert_nature_recovery_unlocked
            if args.guard_scope == "nature-recovery"
            else assert_confirmatory_unlocked
        )
        run_ingestion(_parse_range(args.years), _parse_range(args.months), args.days_per_month,
                      pings_dir=args.pings_dir, workers=args.workers,
                      port_areas_path=args.port_areas,
                      assignment_coverage_path=args.assignment_coverage,
                      unlock_guard=guard,
                      parser_version=args.parser_version)
    if not args.ingest_only:
        build_activity_panel(args.pings_dir)


if __name__ == "__main__":
    main()
