"""
Deterministic NOAA source-file manifest for the AIS census (reproducibility-grade provenance).

Emits outputs/source_manifest.csv listing every raw NOAA Marine Cadastre file the pipeline sources, so a
reader can reconstruct EXACTLY which files were used without guessing. The disk-light pipeline discards raw
files after extraction, so per-file byte counts and checksums are not retained; every row instead carries
the exact filename and download URL, which regenerate the file from NOAA.

Two eras (URLs identical to the downloaders / build_dwell_census_fgdb.py):
  * 2015-2025: daily national CSV files  AIS_YYYY_MM_DD.zip  (filtered to the five port boxes).
  * 2009-2014: monthly per-UTM-zone File Geodatabases  ZoneNN_YYYY_MM.(gdb.)zip  (one per port zone).

Missing-at-source files (4, derived from the census) are flagged. Run: python src/process_ais/source_manifest.py
"""
import calendar
import datetime as dt
import hashlib
import json
from pathlib import Path

import pandas as pd
import requests

BASE = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"
PORT_ZONE = {"LA_Long_Beach": 11, "NY_NJ": 18, "Houston": 15, "Savannah": 17, "Seattle": 10}
PARSER = "extract_port_observations.py+build_dwell_census_fgdb.py @1.0.0"
COLS = ["year", "month", "day", "era", "NOAA_file_name", "NOAA_url", "UTM_zone", "port_relevance",
        "file_size_bytes", "checksum_sha256", "downloaded_at", "parser_version",
        "retained_rows", "dropped_rows", "notes"]
FILE_MANIFEST_COLUMNS = [
    "source_file",
    "source_url",
    "retrieved_at",
    "file_size_bytes",
    "sha256",
    "raw_row_count",
    "accepted_row_count",
    "rejected_row_count",
    "rejection_counts",
    "first_timestamp",
    "last_timestamp",
    "parser_version",
    "port_complex_id",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_file_manifest_record(
    raw_path: Path | str,
    *,
    source_url: str,
    retrieved_at: str,
    raw_row_count: int,
    accepted: pd.DataFrame,
    rejected: pd.DataFrame,
    parser_version: str,
    port_complex_id: str,
) -> dict[str, object]:
    """Record file provenance before the disk-light pipeline deletes the raw download."""
    if "timestamp" not in accepted:
        raise ValueError("accepted rows must include timestamp")
    if "reason" not in rejected:
        raise ValueError("rejected rows must include reason")

    timestamps = pd.to_datetime(accepted["timestamp"], errors="coerce", utc=True).dropna()
    counts = rejected["reason"].dropna().astype(str).value_counts().sort_index()
    return build_file_manifest_record_from_counts(
        raw_path,
        source_url=source_url,
        retrieved_at=retrieved_at,
        raw_row_count=raw_row_count,
        accepted_row_count=len(accepted),
        rejected_row_count=len(rejected),
        rejection_counts=counts.to_dict(),
        first_timestamp=timestamps.min() if len(timestamps) else None,
        last_timestamp=timestamps.max() if len(timestamps) else None,
        parser_version=parser_version,
        port_complex_id=port_complex_id,
    )


def build_file_manifest_record_from_counts(
    raw_path: Path | str,
    *,
    source_url: str,
    retrieved_at: str,
    raw_row_count: int,
    accepted_row_count: int,
    rejected_row_count: int,
    rejection_counts: dict[str, int],
    first_timestamp: object | None,
    last_timestamp: object | None,
    parser_version: str,
    port_complex_id: str,
    source_file: str | None = None,
) -> dict[str, object]:
    """Record streaming parse totals without retaining all accepted or rejected rows."""
    raw_path = Path(raw_path)
    counts = {str(reason): int(count) for reason, count in rejection_counts.items()}
    if min([raw_row_count, accepted_row_count, rejected_row_count, *counts.values()]) < 0:
        raise ValueError("manifest row counts cannot be negative")
    if raw_row_count != accepted_row_count + rejected_row_count:
        raise ValueError("manifest source rows must equal accepted plus rejected rows")
    if rejected_row_count != sum(counts.values()):
        raise ValueError("manifest rejected rows must equal rejection-count totals")
    timestamps = pd.to_datetime([first_timestamp, last_timestamp], errors="coerce", utc=True)
    if accepted_row_count and timestamps.isna().any():
        raise ValueError("accepted manifest rows require timestamp coverage")
    if not accepted_row_count and (first_timestamp is not None or last_timestamp is not None):
        raise ValueError("empty accepted manifest rows cannot have timestamp coverage")
    return {
        "source_file": source_file or raw_path.name,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "file_size_bytes": raw_path.stat().st_size,
        "sha256": _sha256(raw_path),
        "raw_row_count": raw_row_count,
        "accepted_row_count": accepted_row_count,
        "rejected_row_count": rejected_row_count,
        "rejection_counts": json.dumps(counts, sort_keys=True, separators=(",", ":")),
        "first_timestamp": timestamps[0].isoformat() if accepted_row_count else None,
        "last_timestamp": timestamps[1].isoformat() if accepted_row_count else None,
        "parser_version": parser_version,
        "port_complex_id": port_complex_id,
    }


def cache_immutable_source_document(
    destination: Path | str,
    *,
    source_url: str,
    retrieved_at: str,
    parser_version: str,
    port_complex_id: str,
    get=requests.get,
) -> dict[str, object]:
    """Download a static source document once and return its zero-row provenance record."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"immutable source document already exists: {destination}")
    response = get(source_url, timeout=120)
    response.raise_for_status()
    content = response.content
    if not content:
        raise ValueError("source document download is empty")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return build_file_manifest_record_from_counts(
        destination,
        source_url=source_url,
        retrieved_at=retrieved_at,
        raw_row_count=0,
        accepted_row_count=0,
        rejected_row_count=0,
        rejection_counts={},
        first_timestamp=None,
        last_timestamp=None,
        parser_version=parser_version,
        port_complex_id=port_complex_id,
    )


def normalise_file_manifest(records: list[dict[str, object]]) -> pd.DataFrame:
    """Return a byte-stable order for concurrent per-file provenance records."""
    manifest = pd.DataFrame(records)
    if missing := set(FILE_MANIFEST_COLUMNS) - set(manifest.columns):
        raise ValueError(f"file manifest records missing columns: {sorted(missing)}")
    if manifest.duplicated(["port_complex_id", "source_file"]).any():
        raise ValueError("file manifest contains duplicate port/source records")
    return manifest.reindex(columns=FILE_MANIFEST_COLUMNS).sort_values(
        ["port_complex_id", "source_file"], kind="stable"
    ).reset_index(drop=True)


def _fgdb_url(year, month, zone):
    if year <= 2010:
        folder = f"{month:02d}_{calendar.month_name[month]}_{year}"
        return f"{BASE}/{year}/{folder}/Zone{zone}_{year}_{month:02d}.zip"
    ext = "zip" if year >= 2014 else "gdb.zip"
    return f"{BASE}/{year}/{month:02d}/Zone{zone}_{year}_{month:02d}.{ext}"


def build():
    rows = []
    # 2009-2014 FGDB era: one file per (port zone, year, month); flag the 4 missing at source
    present = set(zip(*[pd.read_csv("data/processed/ais_dwell_census_mode_2009_2014/monthly_dwell_2009_2014.csv")[c]
                        for c in ("Port", "YearMonth")]))
    for port, zone in PORT_ZONE.items():
        for year in range(2009, 2015):
            for month in range(1, 13):
                url = _fgdb_url(year, month, zone)
                miss = (port, f"{year}-{month:02d}") not in present
                rows.append(dict(year=year, month=month, day="", era="FGDB",
                                 NOAA_file_name=url.rsplit("/", 1)[1], NOAA_url=url, UTM_zone=zone,
                                 port_relevance=port, parser_version=PARSER,
                                 notes="MISSING at NOAA source" if miss else "monthly per-zone FileGDB"))
    # 2015-2025 CSV era: every daily national file (filtered to the five port boxes)
    d = dt.date(2015, 1, 1)
    end = dt.date(2025, 12, 31)
    while d <= end:
        fn = f"AIS_{d.year}_{d.month:02d}_{d.day:02d}.zip"
        rows.append(dict(year=d.year, month=d.month, day=d.day, era="CSV",
                         NOAA_file_name=fn, NOAA_url=f"{BASE}/{d.year}/{fn}", UTM_zone="national",
                         port_relevance="LA_Long_Beach;NY_NJ;Houston;Savannah;Seattle", parser_version=PARSER,
                         notes="daily national file; filtered to 5 port boxes then discarded (disk-light)"))
        d += dt.timedelta(days=1)
    df = pd.DataFrame(rows).reindex(columns=COLS)
    # unfilled provenance columns (raw files discarded — regenerable from NOAA_url)
    for c in ("file_size_bytes", "checksum_sha256", "downloaded_at", "retained_rows", "dropped_rows"):
        df[c] = ""
    df.to_csv("outputs/source_manifest.csv", index=False)
    nmiss = (df.notes == "MISSING at NOAA source").sum()
    print(f"wrote outputs/source_manifest.csv: {len(df):,} rows "
          f"({(df.era=='FGDB').sum()} FGDB incl. {nmiss} missing-at-source, {(df.era=='CSV').sum():,} daily CSV)")
    assert nmiss == 4 and (df.era == "FGDB").sum() == 360, "manifest coverage changed unexpectedly"


if __name__ == "__main__":
    build()
