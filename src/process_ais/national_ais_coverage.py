"""Disk-light, confirmatory-guarded NOAA AIS geometry-coverage probe."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import os
from pathlib import Path
import sys
import tempfile

import geopandas as gpd
import pandas as pd

try:
    from .build_dwell_census import ingest_national_file
    from .source_manifest import normalise_file_manifest
    from .stream_sample_ais import download, url_for
    from ..governance.access import assert_confirmatory_unlocked
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from build_dwell_census import ingest_national_file
    from source_manifest import normalise_file_manifest
    from stream_sample_ais import download, url_for
    from governance.access import assert_confirmatory_unlocked


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PORT_AREAS = ROOT / "config/geometry/port_areas_usace.geojson"
DEFAULT_ASSIGNMENT_COVERAGE = ROOT / "config/registries/port_area_assignment_coverage.csv"
DEFAULT_OUTPUT_ROOT = ROOT / "data/interim/national_ais_coverage"


def build_port_geometry_coverage(
    pings: pd.DataFrame,
    assignment_coverage: pd.DataFrame,
    *,
    source_date: str,
    source_file: str,
) -> pd.DataFrame:
    """Keep observed safe-area counts distinct from unresolved or unavailable port geometry."""
    if "port_complex_id" not in pings:
        raise ValueError("assigned pings missing port_complex_id")
    required = {"port_complex_id", "port_area_status", "spatial_assignment_status"}
    if missing := required - set(assignment_coverage.columns):
        raise ValueError(f"port-area assignment coverage missing columns: {sorted(missing)}")
    if assignment_coverage.port_complex_id.duplicated().any():
        raise ValueError("port-area assignment coverage contains duplicate port_complex_id values")

    coverage = assignment_coverage.loc[:, ["port_complex_id", "port_area_status", "spatial_assignment_status"]].copy()
    counts = pings.port_complex_id.value_counts()
    coverage["assigned_ping_count"] = pd.Series(pd.NA, index=coverage.index, dtype="Int64")
    safe = coverage.spatial_assignment_status.eq("assignable")
    coverage.loc[safe, "assigned_ping_count"] = coverage.loc[safe, "port_complex_id"].map(counts).fillna(0).astype("Int64")
    coverage.insert(0, "source_file", source_file)
    coverage.insert(0, "source_date", source_date)
    return coverage


def run_coverage_probe(
    source_date: date,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    *,
    port_areas_path: Path | str = DEFAULT_PORT_AREAS,
    assignment_coverage_path: Path | str = DEFAULT_ASSIGNMENT_COVERAGE,
) -> tuple[Path, Path]:
    """Download one NOAA daily file temporarily, then persist only immutable metadata audits."""
    output_dir = Path(output_root) / source_date.isoformat()
    manifest_path = output_dir / "source_manifest.csv"
    coverage_path = output_dir / "port_geometry_coverage.csv"
    if manifest_path.exists() or coverage_path.exists():
        raise FileExistsError(f"immutable coverage artifacts already exist: {output_dir}")
    assert_confirmatory_unlocked(output_dir)

    areas = gpd.read_file(port_areas_path)
    assignment_coverage = pd.read_csv(assignment_coverage_path, keep_default_na=False)
    source_url = url_for(source_date.year, source_date.month, source_date.day)
    descriptor, raw_path = tempfile.mkstemp(suffix=".csv.zst")
    os.close(descriptor)
    raw_path = Path(raw_path)
    try:
        download(source_url, str(raw_path))
        pings, manifest = ingest_national_file(
            raw_path,
            source_url=source_url,
            retrieved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            port_areas=areas,
            assignment_coverage=assignment_coverage,
            source_file=source_url.rsplit("/", 1)[-1],
        )
    finally:
        if raw_path.exists():
            raw_path.unlink()

    output_dir.mkdir(parents=True, exist_ok=True)
    normalise_file_manifest([manifest]).to_csv(manifest_path, index=False, lineterminator="\n")
    build_port_geometry_coverage(
        pings,
        assignment_coverage,
        source_date=source_date.isoformat(),
        source_file=manifest["source_file"],
    ).to_csv(coverage_path, index=False, lineterminator="\n")
    return manifest_path, coverage_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one disk-light national NOAA AIS metadata-coverage probe.")
    parser.add_argument("date", type=date.fromisoformat, help="UTC source date in YYYY-MM-DD form")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    manifest_path, coverage_path = run_coverage_probe(args.date, args.output_root)
    print(f"wrote {manifest_path}")
    print(f"wrote {coverage_path}")
