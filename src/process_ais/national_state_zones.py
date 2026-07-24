"""Outcome-blind construction of national near-port AIS state zones.

The primary geometry uses only published NOAA chart features and USACE navigation-
facility metadata.  Dock coordinates have no waterside orientation, so their
buffers are explicitly *candidate* berth geometry that must pass the registered
blind-label and official-statistics G1 checks; they are not a substitute for
terminal ground truth.
"""

from __future__ import annotations

import hashlib
from itertools import combinations
import json
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union
from shapely import make_valid, set_precision


# Midpoints of the waterside extents documented by BTS PPFSP technical guidance:
# container/Ro-Ro up to 400 ft; oil/chemical 150--200 ft; miscellaneous 150--250 ft.
CONTAINER_RORO_BUFFER_M = 121.92
LIQUID_BUFFER_M = 53.34
MISCELLANEOUS_BUFFER_M = 60.96
CHARTED_BERTH_POINT_BUFFER_M = MISCELLANEOUS_BUFFER_M

_PORT_COLUMN = "port_complex_id"
_OVERLAP_TOLERANCE_DEGREES_SQUARED = 1e-12
_GEOJSON_PRECISION_GRID_DEGREES = 1e-7
_STATE_ZONE_PRIORITY = ("official_anchorage", "berth", "approach_channel")
ROOT = Path(__file__).resolve().parents[2]
PHASE0_CONFIG = ROOT / "config"
DEFAULT_PORT_AREAS = PHASE0_CONFIG / "geometry" / "port_areas_usace.geojson"
DEFAULT_ASSIGNMENT_COVERAGE = PHASE0_CONFIG / "registries" / "port_area_assignment_coverage.csv"
DEFAULT_ZONE_SOURCES = PHASE0_CONFIG / "geometry" / "national_state_zone_sources.geojson"
DEFAULT_ZONES = PHASE0_CONFIG / "geometry" / "national_state_zones.geojson"
DEFAULT_ZONE_COVERAGE = PHASE0_CONFIG / "registries" / "national_state_zone_coverage.csv"
DEFAULT_PROVENANCE = PHASE0_CONFIG / "protocol" / "national_state_zone_provenance.json"

NOAA_ENC_QUERY = "https://encdirect.noaa.gov/arcgis/rest/services/encdirect/{service}/MapServer/{layer}/query"
NOAA_CHANNEL_QUERY = (
    "https://gis.charttools.noaa.gov/arcgis/rest/services/NavigationChartData/"
    "MarineTransportation/MapServer/1/query"
)
USACE_DOCK_QUERY = (
    "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/Docks/FeatureServer/0/query"
)
NOAA_ENC_ROLE_LAYERS = {
    "official_anchorage": (("enc_harbour", 186), ("enc_approach", 191), ("enc_berthing", 87)),
    "charted_berth_point": (("enc_harbour", 49), ("enc_approach", 53)),
    "land_exclusion": (("enc_harbour", 233), ("enc_approach", 238), ("enc_berthing", 103)),
}


def dock_buffer_metres(docks: pd.DataFrame) -> pd.Series:
    """Return the predeclared BTS-informed berth buffer for each USACE dock point."""
    fields = [column for column in ("COMMODITIES", "PURPOSE", "NAV_UNIT_NAME") if column in docks.columns]
    metadata = docks.loc[:, fields].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    container_roro = metadata.str.contains(r"container|roll[ -]?on|ro[ -]?ro|automobile|vehicle", regex=True)
    liquid = metadata.str.contains(
        r"oil|petroleum|gasoline|diesel|fuel|chemical|crude|kerosene|lpg|lng|liquefied",
        regex=True,
    )
    return pd.Series(
        np.select(
            [container_roro, liquid],
            [CONTAINER_RORO_BUFFER_M, LIQUID_BUFFER_M],
            default=MISCELLANEOUS_BUFFER_M,
        ),
        index=docks.index,
        dtype="float64",
    )


def _normalise_features(features: gpd.GeoDataFrame, name: str) -> gpd.GeoDataFrame:
    if _PORT_COLUMN not in features.columns or "geometry" not in features.columns:
        raise ValueError(f"{name} requires port_complex_id and geometry")
    if features.crs is None:
        raise ValueError(f"{name} requires a declared CRS")
    normalised = features.loc[features.geometry.notna() & ~features.geometry.is_empty].to_crs("EPSG:4326").copy()
    normalised["geometry"] = normalised.geometry.make_valid()
    return normalised.loc[~normalised.geometry.is_empty].copy()


def _port_union(features: gpd.GeoDataFrame, port_id: str):
    subset = features.loc[features[_PORT_COLUMN].eq(port_id), "geometry"]
    if not len(subset):
        return GeometryCollection()
    geometry = unary_union(subset)
    return make_valid(geometry) if not geometry.is_valid else geometry


def _wgs84_geometry(geometry, crs):
    return gpd.GeoSeries([geometry], crs=crs).to_crs("EPSG:4326").iloc[0]


def fetch_arcgis_features(
    url: str,
    port_areas: gpd.GeoDataFrame,
    *,
    eligible_port_ids: list[str],
    source_layer: str,
    where: str = "1=1",
    out_fields: str = "*",
    get=requests.get,
) -> gpd.GeoDataFrame:
    """Fetch all paginated GeoJSON features intersecting each declared port area."""
    port_areas = _normalise_features(port_areas, "port areas")
    port_ids = list(dict.fromkeys(eligible_port_ids))

    def fetch_port(port_id: str) -> list[gpd.GeoDataFrame]:
        records: list[gpd.GeoDataFrame] = []
        area = port_areas.loc[port_areas[_PORT_COLUMN].eq(port_id), "geometry"]
        if len(area) != 1:
            raise ValueError(f"source fetch requires one port area for {port_id}")
        minx, miny, maxx, maxy = area.iloc[0].bounds
        offset = 0
        while True:
            response = get(
                url,
                params={
                    "f": "geojson",
                    "where": where,
                    "outFields": out_fields,
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "geometryType": "esriGeometryEnvelope",
                    "geometry": f"{minx},{miny},{maxx},{maxy}",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "resultOffset": offset,
                    "resultRecordCount": 1000,
                },
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("type") != "FeatureCollection":
                raise ValueError(f"{source_layer} did not return GeoJSON features")
            raw_features = payload.get("features", [])
            page = (
                gpd.GeoDataFrame.from_features(raw_features, crs="EPSG:4326")
                if raw_features
                else gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
            )
            if len(page):
                page = page.loc[page.geometry.intersects(area.iloc[0])].copy()
                page[_PORT_COLUMN] = port_id
                page["source_layer"] = source_layer
                records.append(page)
            returned = len(raw_features)
            if not payload.get("exceededTransferLimit"):
                break
            if returned == 0:
                raise ValueError(f"{source_layer} reported a paginated empty page")
            offset += returned
        return records

    worker_count = min(6, len(port_ids))
    if worker_count <= 1:
        records = fetch_port(port_ids[0]) if port_ids else []
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            records = [page for port_records in executor.map(fetch_port, port_ids) for page in port_records]

    if not records:
        return gpd.GeoDataFrame(columns=[_PORT_COLUMN, "source_layer", "geometry"], geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(records, ignore_index=True), geometry="geometry", crs="EPSG:4326")


def _assert_non_overlapping(zones: gpd.GeoDataFrame) -> None:
    for port_id, group in zones.groupby(_PORT_COLUMN, sort=True):
        for left, right in combinations(group.geometry.tolist(), 2):
            if left.intersection(right).area > _OVERLAP_TOLERANCE_DEGREES_SQUARED:
                raise ValueError(f"state zones overlap within {port_id}")

    port_unions = {
        port_id: unary_union(group.geometry.tolist())
        for port_id, group in zones.groupby(_PORT_COLUMN, sort=True)
    }
    for left_port, right_port in combinations(sorted(port_unions), 2):
        if port_unions[left_port].intersection(port_unions[right_port]).area > _OVERLAP_TOLERANCE_DEGREES_SQUARED:
            raise ValueError(f"state zones overlap across {left_port} and {right_port}")


def stabilise_zone_export(zones: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Snap valid WGS84 geometry and reapply the registered within-port state priority."""
    zones = _normalise_features(zones, "state zones")
    stable = zones.copy()
    stable["geometry"] = stable.geometry.map(
        lambda geometry: make_valid(set_precision(geometry, grid_size=_GEOJSON_PRECISION_GRID_DEGREES))
    )
    if "state" in stable.columns:
        priority = {state: rank for rank, state in enumerate(_STATE_ZONE_PRIORITY)}
        for _, indices in stable.groupby(_PORT_COLUMN, sort=True).groups.items():
            occupied = GeometryCollection()
            ordered = sorted(indices, key=lambda index: (priority.get(stable.at[index, "state"], len(priority)), index))
            for index in ordered:
                geometry = set_precision(
                    make_valid(stable.at[index, "geometry"].difference(occupied)),
                    grid_size=_GEOJSON_PRECISION_GRID_DEGREES,
                )
                # Snapping may move an edge back into a higher-priority geometry; trim it once more on
                # the same precision grid before the immutable GeoJSON is written.
                geometry = make_valid(geometry.difference(occupied))
                stable.at[index, "geometry"] = geometry
                occupied = unary_union([occupied, geometry])
        stable = stable.loc[stable.geometry.notna() & ~stable.geometry.is_empty].copy()
    if not stable.geometry.is_valid.all():
        raise ValueError("state-zone export contains invalid geometry after precision stabilization")
    return stable


def build_state_zones(
    port_areas: gpd.GeoDataFrame,
    *,
    anchors: gpd.GeoDataFrame,
    berth_points: gpd.GeoDataFrame,
    docks: gpd.GeoDataFrame,
    channels: gpd.GeoDataFrame,
    land: gpd.GeoDataFrame,
    eligible_port_ids: list[str],
) -> gpd.GeoDataFrame:
    """Build mutually exclusive official-anchorage, berth and channel polygons.

    ``eligible_port_ids`` must come from the immutable port-area assignment audit.
    This deliberately excludes ambiguous or unavailable port areas instead of
    assigning their pings to a nearest complex.
    """
    port_areas = _normalise_features(port_areas, "port areas")
    anchors = _normalise_features(anchors, "anchorage features")
    berth_points = _normalise_features(berth_points, "charted berth points")
    docks = _normalise_features(docks, "USACE dock features")
    channels = _normalise_features(channels, "channel features")
    land = _normalise_features(land, "land features")
    eligible_port_ids = list(dict.fromkeys(eligible_port_ids))

    if port_areas[_PORT_COLUMN].duplicated().any():
        raise ValueError("port areas must have one geometry per complex")
    missing_areas = sorted(set(eligible_port_ids) - set(port_areas[_PORT_COLUMN]))
    if missing_areas:
        raise ValueError(f"eligible ports lack frozen port areas: {', '.join(missing_areas)}")

    records: list[dict] = []
    for port_id in eligible_port_ids:
        port_area = port_areas.loc[port_areas[_PORT_COLUMN].eq(port_id), "geometry"].iloc[0]
        metric_crs = gpd.GeoSeries([port_area], crs="EPSG:4326").estimate_utm_crs()
        area_metric = gpd.GeoSeries([port_area], crs="EPSG:4326").to_crs(metric_crs).iloc[0]

        def metric_union(features: gpd.GeoDataFrame):
            geometry = _port_union(features, port_id)
            if geometry.is_empty:
                return GeometryCollection()
            metric_geometry = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(metric_crs).iloc[0]
            return make_valid(metric_geometry) if not metric_geometry.is_valid else metric_geometry

        anchor_geometry = metric_union(anchors).intersection(area_metric)
        land_geometry = metric_union(land)
        channel_geometry = metric_union(channels).intersection(area_metric)

        dock_rows = docks.loc[docks[_PORT_COLUMN].eq(port_id)].copy()
        dock_buffers = GeometryCollection()
        if len(dock_rows):
            dock_rows = dock_rows.to_crs(metric_crs)
            dock_buffers = unary_union(
                [
                    geometry.buffer(radius)
                    for geometry, radius in zip(dock_rows.geometry, dock_buffer_metres(dock_rows), strict=True)
                ]
            )

        charted_berths = metric_union(berth_points)
        if not charted_berths.is_empty:
            charted_berths = charted_berths.buffer(CHARTED_BERTH_POINT_BUFFER_M)
        berth_geometry = (
            unary_union([dock_buffers, charted_berths])
            .difference(land_geometry)
            .intersection(area_metric)
            .difference(anchor_geometry)
        )
        channel_geometry = channel_geometry.difference(land_geometry).difference(anchor_geometry).difference(berth_geometry)

        # Reapply differences after the projection round-trip: without this final
        # topological cleanup, transformation precision can leave tiny slivers
        # inside charted land or a higher-priority zone.
        land_wgs84 = _port_union(land, port_id)
        anchor_wgs84 = make_valid(_wgs84_geometry(anchor_geometry, metric_crs)).difference(land_wgs84)
        anchor_wgs84 = make_valid(anchor_wgs84)
        berth_wgs84 = (
            make_valid(_wgs84_geometry(berth_geometry, metric_crs))
            .difference(land_wgs84)
            .difference(anchor_wgs84)
        )
        berth_wgs84 = make_valid(berth_wgs84)
        channel_wgs84 = (
            make_valid(_wgs84_geometry(channel_geometry, metric_crs))
            .difference(land_wgs84)
            .difference(anchor_wgs84)
            .difference(berth_wgs84)
        )
        channel_wgs84 = make_valid(channel_wgs84)

        if not anchor_wgs84.is_empty:
            records.append(
                {
                    _PORT_COLUMN: port_id,
                    "state": "official_anchorage",
                    "geometry_source": "noaa_enc_anchorage_area",
                    "geometry": anchor_wgs84,
                }
            )
        if not berth_wgs84.is_empty:
            source = "usace_navigation_facilities_docks"
            if not charted_berths.is_empty:
                source += "+noaa_enc_berth_points"
            records.append(
                {
                    _PORT_COLUMN: port_id,
                    "state": "berth",
                    "geometry_source": source,
                    "geometry": berth_wgs84,
                }
            )
        if not channel_wgs84.is_empty:
            records.append(
                {
                    _PORT_COLUMN: port_id,
                    "state": "approach_channel",
                    "geometry_source": "noaa_coastal_maintained_channels",
                    "geometry": channel_wgs84,
                }
            )

    zones = stabilise_zone_export(gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326"))
    _assert_non_overlapping(zones)
    return zones.sort_values([_PORT_COLUMN, "state"], kind="stable").reset_index(drop=True)


def build_state_zones_from_snapshot(
    port_areas: gpd.GeoDataFrame,
    source_snapshot: gpd.GeoDataFrame,
    *,
    eligible_port_ids: list[str],
) -> gpd.GeoDataFrame:
    """Rebuild derived zones from the immutable source snapshot without network access."""
    source_snapshot = _normalise_features(source_snapshot, "state-zone source snapshot")
    if "source_role" not in source_snapshot.columns:
        raise ValueError("state-zone source snapshot requires source_role")

    def role(name: str) -> gpd.GeoDataFrame:
        subset = source_snapshot.loc[source_snapshot.source_role.eq(name)].copy()
        if len(subset):
            return subset
        return gpd.GeoDataFrame(
            columns=[_PORT_COLUMN, "source_role", "geometry"], geometry="geometry", crs="EPSG:4326"
        )

    return build_state_zones(
        port_areas,
        anchors=role("official_anchorage"),
        berth_points=role("charted_berth_point"),
        docks=role("navigation_facility_dock"),
        channels=role("maintained_channel"),
        land=role("land_exclusion"),
        eligible_port_ids=eligible_port_ids,
    )


def assess_state_zone_coverage(eligible_port_ids: list[str], zones: gpd.GeoDataFrame) -> pd.DataFrame:
    """Record geometry availability without turning a missing state into a zero outcome."""
    zones = _normalise_features(zones, "state zones")
    if "state" not in zones.columns:
        raise ValueError("state zones require a state column")

    rows = []
    for port_id in list(dict.fromkeys(eligible_port_ids)):
        states = set(zones.loc[zones[_PORT_COLUMN].eq(port_id), "state"])
        berth = int("berth" in states)
        channel = int("approach_channel" in states)
        rows.append(
            {
                _PORT_COLUMN: port_id,
                "official_anchorage_available": int("official_anchorage" in states),
                "berth_candidate_available": berth,
                "approach_channel_available": channel,
                "state_geometry_status": "ready" if berth and channel else "unavailable",
            }
        )
    return pd.DataFrame(rows)


def load_assignable_port_areas(
    port_areas_path: Path | str = DEFAULT_PORT_AREAS,
    assignment_coverage_path: Path | str = DEFAULT_ASSIGNMENT_COVERAGE,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Load only complexes that passed the frozen, outcome-blind area-assignment audit."""
    areas = _normalise_features(gpd.read_file(port_areas_path), "port areas")
    coverage = pd.read_csv(assignment_coverage_path, dtype=str, keep_default_na=False)
    required = {_PORT_COLUMN, "spatial_assignment_status"}
    if missing := required - set(coverage.columns):
        raise ValueError(f"port area assignment coverage missing columns: {sorted(missing)}")
    eligible = coverage.loc[coverage.spatial_assignment_status.eq("assignable"), _PORT_COLUMN].tolist()
    if not eligible:
        raise ValueError("port area assignment audit has no assignable complexes")
    missing = sorted(set(eligible) - set(areas[_PORT_COLUMN]))
    if missing:
        raise ValueError(f"assignable complexes missing port area geometry: {', '.join(missing)}")
    return areas.loc[areas[_PORT_COLUMN].isin(eligible)].copy(), eligible


def _fetch_noaa_enc_role(
    role: str,
    port_areas: gpd.GeoDataFrame,
    eligible_port_ids: list[str],
    *,
    get=requests.get,
) -> gpd.GeoDataFrame:
    frames = []
    for service, layer in NOAA_ENC_ROLE_LAYERS[role]:
        source_layer = f"{service}/{layer}"
        frames.append(
            fetch_arcgis_features(
                NOAA_ENC_QUERY.format(service=service, layer=layer),
                port_areas,
                eligible_port_ids=eligible_port_ids,
                source_layer=source_layer,
                get=get,
            )
        )
    nonempty = [frame for frame in frames if len(frame)]
    if not nonempty:
        return gpd.GeoDataFrame(columns=[_PORT_COLUMN, "source_layer", "geometry"], geometry="geometry", crs="EPSG:4326")
    out = gpd.GeoDataFrame(pd.concat(nonempty, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    out["source_role"] = role
    return out


def _fetch_usace_docks(
    port_areas: gpd.GeoDataFrame,
    eligible_port_ids: list[str],
    *,
    get=requests.get,
) -> gpd.GeoDataFrame:
    docks = fetch_arcgis_features(
        USACE_DOCK_QUERY,
        port_areas,
        eligible_port_ids=eligible_port_ids,
        source_layer="usace_navigation_facilities",
        where="FAC_TYPE = 'Dock'",
        out_fields="NAV_UNIT_ID,NAV_UNIT_NAME,FAC_TYPE,PORT_NAME,PSA_NAME,STATE,BERTHING_TOTAL,PURPOSE,COMMODITIES",
        get=get,
    )
    if not len(docks):
        return docks
    area_by_port = port_areas.set_index(_PORT_COLUMN).geometry
    docks = docks.loc[
        [geometry.within(area_by_port[port_id]) for geometry, port_id in zip(docks.geometry, docks[_PORT_COLUMN], strict=True)]
    ].copy()
    docks["source_role"] = "navigation_facility_dock"
    return docks


def _fetch_noaa_channels(
    port_areas: gpd.GeoDataFrame,
    eligible_port_ids: list[str],
    *,
    get=requests.get,
) -> gpd.GeoDataFrame:
    channels = fetch_arcgis_features(
        NOAA_CHANNEL_QUERY,
        port_areas,
        eligible_port_ids=eligible_port_ids,
        source_layer="marine_transportation/1",
        out_fields="OBJECTID,OBJNAM,FAIRWAY,DSNM,SORDAT",
        get=get,
    )
    channels["source_role"] = "maintained_channel"
    return channels


def _source_snapshot(role: str, features: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Retain only fields needed to reproduce the frozen zone construction."""
    fields = [_PORT_COLUMN, "source_role", "source_layer", "NAV_UNIT_ID", "NAV_UNIT_NAME", "COMMODITIES", "PURPOSE", "geometry"]
    snapshot = features.copy()
    snapshot["source_role"] = role
    for field in fields:
        if field not in snapshot.columns:
            snapshot[field] = pd.NA
    return snapshot.loc[:, fields]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_new_paths(paths: list[Path]) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError("immutable state-geometry artifact already exists: " + ", ".join(existing))


def freeze_national_state_zones(
    *,
    port_areas_path: Path | str = DEFAULT_PORT_AREAS,
    assignment_coverage_path: Path | str = DEFAULT_ASSIGNMENT_COVERAGE,
    source_output_path: Path | str = DEFAULT_ZONE_SOURCES,
    zones_output_path: Path | str = DEFAULT_ZONES,
    coverage_output_path: Path | str = DEFAULT_ZONE_COVERAGE,
    provenance_output_path: Path | str = DEFAULT_PROVENANCE,
    get=requests.get,
) -> dict[str, Path]:
    """Retrieve official geometry once and freeze the reproducible state-zone inputs."""
    outputs = [Path(path) for path in (source_output_path, zones_output_path, coverage_output_path, provenance_output_path)]
    _require_new_paths(outputs)
    port_areas, eligible_port_ids = load_assignable_port_areas(port_areas_path, assignment_coverage_path)

    anchors = _fetch_noaa_enc_role("official_anchorage", port_areas, eligible_port_ids, get=get)
    berth_points = _fetch_noaa_enc_role("charted_berth_point", port_areas, eligible_port_ids, get=get)
    land = _fetch_noaa_enc_role("land_exclusion", port_areas, eligible_port_ids, get=get)
    docks = _fetch_usace_docks(port_areas, eligible_port_ids, get=get)
    channels = _fetch_noaa_channels(port_areas, eligible_port_ids, get=get)

    zones = build_state_zones(
        port_areas,
        anchors=anchors,
        berth_points=berth_points,
        docks=docks,
        channels=channels,
        land=land,
        eligible_port_ids=eligible_port_ids,
    )
    coverage = assess_state_zone_coverage(eligible_port_ids, zones)
    source_snapshot = gpd.GeoDataFrame(
        pd.concat(
            [
                _source_snapshot("official_anchorage", anchors),
                _source_snapshot("charted_berth_point", berth_points),
                _source_snapshot("land_exclusion", land),
                _source_snapshot("navigation_facility_dock", docks),
                _source_snapshot("maintained_channel", channels),
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs="EPSG:4326",
    )

    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
    source_snapshot.to_file(outputs[0], driver="GeoJSON")
    zones.to_file(outputs[1], driver="GeoJSON")
    coverage.to_csv(outputs[2], index=False)
    provenance = {
        "schema_version": "national-state-zones-v1",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "eligible_port_complex_ids": eligible_port_ids,
        "excluded_by_port_area_assignment": sorted(
            set(gpd.read_file(port_areas_path)[_PORT_COLUMN]) - set(eligible_port_ids)
        ),
        "sources": {
            "noaa_enc": {
                "query_template": NOAA_ENC_QUERY,
                "layers": {role: [f"{service}/{layer}" for service, layer in layers] for role, layers in NOAA_ENC_ROLE_LAYERS.items()},
            },
            "noaa_coastal_maintained_channels": {"query_url": NOAA_CHANNEL_QUERY, "layer": "marine_transportation/1"},
            "usace_navigation_facilities": {"query_url": USACE_DOCK_QUERY, "where": "FAC_TYPE = 'Dock'"},
        },
        "feature_counts": source_snapshot.groupby("source_role", sort=True).size().to_dict(),
        "artifacts": {
            "source_features": {"path": outputs[0].name, "sha256": _sha256(outputs[0])},
            "state_zones": {"path": outputs[1].name, "sha256": _sha256(outputs[1])},
            "coverage": {"path": outputs[2].name, "sha256": _sha256(outputs[2])},
        },
    }
    outputs[3].write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"sources": outputs[0], "zones": outputs[1], "coverage": outputs[2], "provenance": outputs[3]}


def rebuild_national_state_zones_from_snapshot(
    source_snapshot_path: Path | str = DEFAULT_ZONE_SOURCES,
    *,
    port_areas_path: Path | str = DEFAULT_PORT_AREAS,
    assignment_coverage_path: Path | str = DEFAULT_ASSIGNMENT_COVERAGE,
    zones_output_path: Path | str = DEFAULT_ZONES,
    coverage_output_path: Path | str = DEFAULT_ZONE_COVERAGE,
    provenance_output_path: Path | str = DEFAULT_PROVENANCE,
    source_retrieved_at_utc: str | None = None,
    source_definitions: dict | None = None,
) -> dict[str, Path]:
    """Regenerate only derived zone artifacts from an already-frozen source snapshot."""
    outputs = [Path(path) for path in (zones_output_path, coverage_output_path, provenance_output_path)]
    _require_new_paths(outputs)
    source_snapshot_path = Path(source_snapshot_path)
    if not source_snapshot_path.is_file():
        raise FileNotFoundError(f"frozen state-zone source snapshot is missing: {source_snapshot_path}")

    port_areas, eligible_port_ids = load_assignable_port_areas(port_areas_path, assignment_coverage_path)
    source_snapshot = gpd.read_file(source_snapshot_path)
    zones = build_state_zones_from_snapshot(port_areas, source_snapshot, eligible_port_ids=eligible_port_ids)
    coverage = assess_state_zone_coverage(eligible_port_ids, zones)
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
    zones.to_file(outputs[0], driver="GeoJSON")
    coverage.to_csv(outputs[1], index=False)

    provenance = {
        "schema_version": "national-state-zones-v1",
        "derived_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_snapshot": {"path": source_snapshot_path.name, "sha256": _sha256(source_snapshot_path)},
        "zone_export_precision_grid_degrees": _GEOJSON_PRECISION_GRID_DEGREES,
        "eligible_port_complex_ids": eligible_port_ids,
        "excluded_by_port_area_assignment": sorted(
            set(gpd.read_file(port_areas_path)[_PORT_COLUMN]) - set(eligible_port_ids)
        ),
        "source_feature_counts": source_snapshot.groupby("source_role", sort=True).size().to_dict(),
        "artifacts": {
            "state_zones": {"path": outputs[0].name, "sha256": _sha256(outputs[0])},
            "coverage": {"path": outputs[1].name, "sha256": _sha256(outputs[1])},
        },
    }
    if source_retrieved_at_utc:
        provenance["source_retrieved_at_utc"] = source_retrieved_at_utc
    if source_definitions:
        provenance["sources"] = source_definitions
    outputs[2].write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"zones": outputs[0], "coverage": outputs[1], "provenance": outputs[2]}


def main() -> None:
    """Freeze one official-source snapshot; immutable outputs make reruns fail safely."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-areas", type=Path, default=DEFAULT_PORT_AREAS)
    parser.add_argument("--assignment-coverage", type=Path, default=DEFAULT_ASSIGNMENT_COVERAGE)
    parser.add_argument("--source-output", type=Path, default=DEFAULT_ZONE_SOURCES)
    parser.add_argument("--zones-output", type=Path, default=DEFAULT_ZONES)
    parser.add_argument("--coverage-output", type=Path, default=DEFAULT_ZONE_COVERAGE)
    parser.add_argument("--provenance-output", type=Path, default=DEFAULT_PROVENANCE)
    args = parser.parse_args()
    paths = freeze_national_state_zones(
        port_areas_path=args.port_areas,
        assignment_coverage_path=args.assignment_coverage,
        source_output_path=args.source_output,
        zones_output_path=args.zones_output,
        coverage_output_path=args.coverage_output,
        provenance_output_path=args.provenance_output,
    )
    for name, path in paths.items():
        print(f"{name}={path}")


if __name__ == "__main__":
    main()
