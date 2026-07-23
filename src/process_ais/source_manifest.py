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
import pandas as pd

BASE = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"
PORT_ZONE = {"LA_Long_Beach": 11, "NY_NJ": 18, "Houston": 15, "Savannah": 17, "Seattle": 10}
PARSER = "extract_port_observations.py+build_dwell_census_fgdb.py @1.0.0"
COLS = ["year", "month", "day", "era", "NOAA_file_name", "NOAA_url", "UTM_zone", "port_relevance",
        "file_size_bytes", "checksum_sha256", "downloaded_at", "parser_version",
        "retained_rows", "dropped_rows", "notes"]


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
