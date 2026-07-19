"""Outcome-blind national port areas sourced from USACE port polygons."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import geopandas as gpd
import pandas as pd
import requests
from shapely import voronoi_polygons
from shapely.geometry import MultiPoint
from shapely.ops import unary_union


SOURCE_COLUMNS = ("port_complex_id", "status", "usace_port_ids", "exclusion_reason")
USACE_PORT_FEATURE_URL = (
    "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/"
    "Port_Statistical_Area/FeatureServer/0/query"
)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "data/processed/port_registry.csv"
DEFAULT_SOURCES = ROOT / "config/registries/port_area_sources.csv"
DEFAULT_OUTPUT = ROOT / "config/geometry/port_areas_usace.geojson"
DEFAULT_ASSIGNMENT_COVERAGE = ROOT / "config/registries/port_area_assignment_coverage.csv"
ASSIGNMENT_COVERAGE_COLUMNS = (
    "port_complex_id",
    "port_area_status",
    "spatial_assignment_status",
    "conflicting_port_complex_ids",
)
AREA_OVERLAP_TOLERANCE_M2 = 0.01


def _source_ids(value: str) -> list[str]:
    return [source_id.strip() for source_id in str(value).split(";") if source_id.strip()]


def load_port_geometry_sources(path: Path | str, included_complexes: list[str]) -> pd.DataFrame:
    """Load one declared USACE source record for each selected port complex."""
    sources = pd.read_csv(path, dtype=str, keep_default_na=False)
    if missing := set(SOURCE_COLUMNS) - set(sources.columns):
        raise ValueError(f"port geometry sources missing columns: {sorted(missing)}")
    sources = sources.loc[:, SOURCE_COLUMNS].copy()
    sources["port_complex_id"] = sources["port_complex_id"].str.strip()
    if sources.port_complex_id.duplicated().any():
        raise ValueError("port geometry sources contain duplicate port_complex_id values")

    selected = list(dict.fromkeys(included_complexes))
    missing = sorted(set(selected) - set(sources.port_complex_id))
    if missing:
        raise ValueError(f"port geometry sources missing source records: {', '.join(missing)}")
    sources = sources.set_index("port_complex_id").loc[selected].reset_index()

    invalid_status = sorted(set(sources.status) - {"available", "unavailable"})
    if invalid_status:
        raise ValueError(f"port geometry sources have invalid status values: {invalid_status}")
    available = sources.status.eq("available")
    if sources.loc[available, "usace_port_ids"].map(_source_ids).map(bool).eq(False).any():
        raise ValueError("available port geometry source requires usace_port_ids")
    if sources.loc[~available, "exclusion_reason"].str.strip().eq("").any():
        raise ValueError("unavailable port geometry source requires exclusion_reason")
    return sources


def fetch_usace_port_features(source_ids: list[str], *, get=requests.get) -> gpd.GeoDataFrame:
    """Retrieve declared USACE Port polygons in WGS84 GeoJSON."""
    source_ids = sorted(set(map(str, source_ids)))
    if not source_ids or any(not source_id.isdigit() for source_id in source_ids):
        raise ValueError("USACE port IDs must be a non-empty list of numeric identifiers")
    where = "PORTIDPK IN (" + ",".join(f"'{source_id}'" for source_id in source_ids) + ")"
    response = get(
        USACE_PORT_FEATURE_URL,
        params={
            "f": "geojson",
            "where": where,
            "outFields": "PORTIDPK,FEATURENAME,FEATUREDESCRIPTION,DATA_YEAR",
            "returnGeometry": "true",
            "outSR": "4326",
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("type") != "FeatureCollection":
        raise ValueError("USACE port service did not return GeoJSON features")
    features = gpd.GeoDataFrame.from_features(payload["features"], crs="EPSG:4326")
    if "PORTIDPK" not in features.columns:
        raise ValueError("USACE port service returned features without PORTIDPK")
    features["PORTIDPK"] = features["PORTIDPK"].astype(str)
    return features


def derive_port_geometries(sources: pd.DataFrame, features: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Dissolve each declared many-to-one USACE source mapping into one port area."""
    if missing := set(SOURCE_COLUMNS) - set(sources.columns):
        raise ValueError(f"port geometry sources missing columns: {sorted(missing)}")
    if missing := {"PORTIDPK", "DATA_YEAR"} - set(features.columns):
        raise ValueError(f"USACE port features missing columns: {sorted(missing)}")

    features = features.copy()
    features["PORTIDPK"] = features["PORTIDPK"].astype(str)
    records = []
    for source in sources.loc[sources.status.eq("available")].itertuples(index=False):
        source_ids = sorted(_source_ids(source.usace_port_ids))
        subset = features.loc[features.PORTIDPK.isin(source_ids)]
        missing_ids = sorted(set(source_ids) - set(subset.PORTIDPK))
        if missing_ids:
            raise ValueError(f"missing declared USACE port IDs: {', '.join(missing_ids)}")
        records.append(
            {
                "port_complex_id": source.port_complex_id,
                "source_port_ids": ";".join(source_ids),
                "source_data_years": ";".join(map(str, sorted(set(subset.DATA_YEAR.dropna())))),
                "geometry": unary_union(subset.geometry),
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=features.crs).sort_values(
        "port_complex_id", kind="stable"
    ).reset_index(drop=True)


def assess_port_area_assignment(sources: pd.DataFrame, areas: gpd.GeoDataFrame) -> pd.DataFrame:
    """Flag selected complexes that need finer geometry before spatial AIS assignment."""
    if missing := {"port_complex_id", "status"} - set(sources.columns):
        raise ValueError(f"port geometry sources missing columns: {sorted(missing)}")
    if missing := {"port_complex_id", "geometry"} - set(areas.columns):
        raise ValueError(f"port areas missing columns: {sorted(missing)}")
    if sources.port_complex_id.duplicated().any() or areas.port_complex_id.duplicated().any():
        raise ValueError("port-area assignment inputs require unique port_complex_id values")
    if set(sources.status) - {"available", "unavailable"}:
        raise ValueError("port geometry sources have invalid status values")

    available = sources.loc[sources.status.eq("available"), "port_complex_id"]
    missing_areas = sorted(set(available) - set(areas.port_complex_id))
    if missing_areas:
        raise ValueError(f"available port areas missing frozen geometry: {', '.join(missing_areas)}")
    unexpected_areas = sorted(set(areas.port_complex_id) - set(available))
    if unexpected_areas:
        raise ValueError(f"frozen port areas lack an available source record: {', '.join(unexpected_areas)}")

    geometry_by_port = areas.set_index("port_complex_id").geometry
    conflicts: dict[str, list[str]] = {port: [] for port in available}
    for port in available:
        for other in available:
            if port >= other:
                continue
            if geometry_by_port[port].intersection(geometry_by_port[other]).area > 0:
                conflicts[port].append(other)
                conflicts[other].append(port)

    records = []
    for source in sources.loc[:, ["port_complex_id", "status"]].itertuples(index=False):
        conflict_ids = ";".join(sorted(conflicts.get(source.port_complex_id, [])))
        records.append(
            {
                "port_complex_id": source.port_complex_id,
                "port_area_status": source.status,
                "spatial_assignment_status": (
                    "unavailable"
                    if source.status == "unavailable"
                    else "requires_finer_geometry"
                    if conflict_ids
                    else "assignable"
                ),
                "conflicting_port_complex_ids": conflict_ids,
            }
        )
    return pd.DataFrame(records, columns=ASSIGNMENT_COVERAGE_COLUMNS)


def derive_partitioned_coastal_domains(
    areas: gpd.GeoDataFrame,
    *,
    inner_buffer_m: float,
    outer_buffer_m: float,
    projected_crs: str = "EPSG:5070",
) -> gpd.GeoDataFrame:
    """Create nested, non-overlapping coastal domains around frozen port areas.

    Neighboring buffered port areas can overlap even when the source USACE
    statistical areas do not. Their added buffer space is therefore clipped by
    a deterministic Voronoi partition of one representative point per port.
    Every source area remains assigned to its own port; another port's source
    area is removed from each buffered extension before the partition is
    applied. This preserves the declared port geography while preventing one
    AIS ping from being assigned to two coastal domains.

    The function uses geometry only. It does not inspect AIS activity or any
    policy-period outcome.
    """
    required = {"port_complex_id", "geometry"}
    if missing := required - set(areas.columns):
        raise ValueError(f"coastal-domain areas missing columns: {sorted(missing)}")
    if areas.empty:
        raise ValueError("coastal-domain areas cannot be empty")
    if areas.port_complex_id.duplicated().any():
        raise ValueError("coastal-domain areas require unique port_complex_id values")
    if not 0 < inner_buffer_m < outer_buffer_m:
        raise ValueError("coastal-domain buffers require 0 < inner < outer")
    if areas.crs is None:
        raise ValueError("coastal-domain areas require a declared CRS")

    projected = areas.loc[:, ["port_complex_id", "geometry"]].to_crs(projected_crs)
    if projected.geometry.is_empty.any() or projected.geometry.isna().any():
        raise ValueError("coastal-domain areas require non-empty geometries")
    for left, left_geometry in projected.set_index("port_complex_id").geometry.items():
        for right, right_geometry in projected.set_index("port_complex_id").geometry.items():
            if left >= right:
                continue
            if left_geometry.intersection(right_geometry).area > AREA_OVERLAP_TOLERANCE_M2:
                raise ValueError(f"source port areas overlap: {left}, {right}")

    cores = projected.geometry.tolist()
    all_cores = unary_union(cores)
    owner_points = [geometry.representative_point() for geometry in cores]
    envelope = unary_union(
        [geometry.buffer(outer_buffer_m) for geometry in cores]
    ).envelope
    cells = list(
        voronoi_polygons(MultiPoint(owner_points), extend_to=envelope).geoms
    )

    records = []
    for row_number, row in enumerate(projected.itertuples(index=False)):
        owner_point = owner_points[row_number]
        matching_cells = [cell for cell in cells if cell.covers(owner_point)]
        if len(matching_cells) != 1:
            raise ValueError(
                f"could not resolve one coastal partition for {row.port_complex_id}"
            )
        cell = matching_cells[0]
        other_cores = all_cores.difference(row.geometry)
        for domain, radius in (
            ("coastal_inner", inner_buffer_m),
            ("coastal_outer", outer_buffer_m),
        ):
            extension = (
                row.geometry.buffer(radius)
                .difference(other_cores)
                .intersection(cell)
            )
            records.append(
                {
                    "port_complex_id": row.port_complex_id,
                    "domain": domain,
                    "buffer_m": float(radius),
                    "partition_method": "source-core-plus-representative-point-voronoi-v1",
                    "geometry": unary_union([row.geometry, extension]),
                }
            )

    domains = gpd.GeoDataFrame(
        records, geometry="geometry", crs=projected_crs
    ).to_crs(areas.crs)
    domains = domains.sort_values(
        ["port_complex_id", "buffer_m"], kind="stable"
    ).reset_index(drop=True)
    projected_domains = domains.to_crs(projected_crs)
    for domain, group in projected_domains.groupby("domain", sort=False):
        geometries = group.set_index("port_complex_id").geometry
        for left, left_geometry in geometries.items():
            for right, right_geometry in geometries.items():
                if left >= right:
                    continue
                if left_geometry.intersection(right_geometry).area > AREA_OVERLAP_TOLERANCE_M2:
                    raise ValueError(
                        f"{domain} coastal partitions overlap: {left}, {right}"
                    )
    return domains


def write_partitioned_coastal_domains(
    domains: gpd.GeoDataFrame,
    output_path: Path | str,
) -> None:
    """Write a frozen coastal-domain GeoJSON without replacing an artifact."""
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f"immutable coastal domains already exist: {output_path}")
    required = {
        "port_complex_id", "domain", "buffer_m", "partition_method", "geometry",
    }
    if missing := required - set(domains.columns):
        raise ValueError(f"coastal domains missing columns: {sorted(missing)}")
    if domains.duplicated(["port_complex_id", "domain"]).any():
        raise ValueError("coastal domains contain duplicate port-domain rows")
    if domains.crs is None:
        raise ValueError("coastal domains require a declared CRS")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    domains.to_file(output_path, driver="GeoJSON")


def write_port_area_assignment_coverage(coverage: pd.DataFrame, output_path: Path | str) -> None:
    """Write the immutable audit that governs safe spatial port assignment."""
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f"immutable port-area assignment audit already exists: {output_path}")
    if missing := set(ASSIGNMENT_COVERAGE_COLUMNS) - set(coverage.columns):
        raise ValueError(f"port-area assignment coverage missing columns: {sorted(missing)}")
    if coverage.port_complex_id.duplicated().any():
        raise ValueError("port-area assignment coverage contains duplicate port_complex_id values")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    coverage.reindex(columns=ASSIGNMENT_COVERAGE_COLUMNS).to_csv(output_path, index=False, lineterminator="\n")


def build_port_areas(
    registry_path: Path | str,
    source_path: Path | str,
    output_path: Path | str,
    *,
    retrieved_at_utc: str,
    fetcher=fetch_usace_port_features,
) -> gpd.GeoDataFrame:
    """Create one immutable USACE-derived geometry file for the selected port universe."""
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f"immutable port-area artifact already exists: {output_path}")
    registry = pd.read_csv(registry_path, dtype=str)
    if missing := {"port_complex_id", "inclusion_status"} - set(registry.columns):
        raise ValueError(f"port registry missing columns: {sorted(missing)}")
    included = registry.loc[registry.inclusion_status.eq("included"), "port_complex_id"].tolist()
    sources = load_port_geometry_sources(source_path, included)
    source_ids = [
        source_id
        for value in sources.loc[sources.status.eq("available"), "usace_port_ids"]
        for source_id in _source_ids(value)
    ]
    areas = derive_port_geometries(sources, fetcher(source_ids))
    areas["retrieved_at_utc"] = retrieved_at_utc
    areas["source_service_url"] = USACE_PORT_FEATURE_URL
    output_path.parent.mkdir(parents=True, exist_ok=True)
    areas.to_file(output_path, driver="GeoJSON")
    return areas


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    if DEFAULT_OUTPUT.exists():
        areas = gpd.read_file(DEFAULT_OUTPUT)
        print(f"using immutable {DEFAULT_OUTPUT} ({len(areas)} port areas)")
    else:
        areas = build_port_areas(
            DEFAULT_REGISTRY,
            DEFAULT_SOURCES,
            DEFAULT_OUTPUT,
            retrieved_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        print(f"wrote {DEFAULT_OUTPUT} ({len(areas)} port areas)")
    registry = pd.read_csv(DEFAULT_REGISTRY, dtype=str)
    sources = load_port_geometry_sources(
        DEFAULT_SOURCES,
        registry.loc[registry.inclusion_status.eq("included"), "port_complex_id"].tolist(),
    )
    if DEFAULT_ASSIGNMENT_COVERAGE.exists():
        print(f"using immutable {DEFAULT_ASSIGNMENT_COVERAGE}")
    else:
        write_port_area_assignment_coverage(
            assess_port_area_assignment(sources, areas),
            DEFAULT_ASSIGNMENT_COVERAGE,
        )
        print(f"wrote {DEFAULT_ASSIGNMENT_COVERAGE}")
