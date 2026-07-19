"""Derive berth/anchor state zones from LOCAL authoritative geometry (Pillar B; no download).

Pillar B resolved only 30.4% of stationary episodes to berth/anchor because only ANCHOR polygons existed.
Here berth := (USACE port working area) MINUS (charted NOAA anchorages); anchor := the anchorages. Both are
local and authoritative. Anchorage polygons exist for SPB / NY-NJ / Savannah (Seattle too, not a gateway);
other gateways get a berth zone only (anchor unresolved there — a documented limitation).

Output: data/processed/state_zones_derived.geojson  [complex_id, zone_type in {berth,anchor}, geometry].
Consumable by pillar_b_state_validation.reconstruct_episodes as the zones layer.

Run: python src/process_ais/derive_berth_zones.py
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
PORT_AREAS = ROOT / "config/geometry/port_areas_usace.geojson"
ANCHORAGES = ROOT / "config/geometry/noaa_anchorages.geojson"
OUT = ROOT / "data/processed/state_zones_derived.geojson"
# NOAA anchorage 'Port' -> registry complex_id
PORT_TO_COMPLEX = {"LA_Long_Beach": "san_pedro_bay", "NY_NJ": "new_york_new_jersey", "Savannah": "savannah_ga"}


def derive(out: Path = OUT) -> gpd.GeoDataFrame:
    areas = gpd.read_file(PORT_AREAS).to_crs("EPSG:4326")
    anch = gpd.read_file(ANCHORAGES).to_crs("EPSG:4326")
    anch["complex_id"] = anch["Port"].map(PORT_TO_COMPLEX)
    rows = []
    for _, a in areas.iterrows():
        cid = a["port_complex_id"]
        port_geom = a.geometry
        my_anch = anch.loc[anch["complex_id"] == cid]
        if len(my_anch):
            anch_union = unary_union(my_anch.geometry.values)
            berth = port_geom.difference(anch_union)               # wharf areas = port minus anchorage
            for g in getattr(my_anch, "geometry"):
                rows.append({"complex_id": cid, "zone_type": "anchor", "geometry": g})
        else:
            berth = port_geom                                      # no anchorage layer -> whole port = berth
        if not berth.is_empty:
            rows.append({"complex_id": cid, "zone_type": "berth", "geometry": berth})
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    gdf.to_file(out, driver="GeoJSON")
    print(gdf.groupby(["complex_id", "zone_type"]).size().to_string())
    print(f"\n-> {out} ({len(gdf)} zones)")
    return gdf


if __name__ == "__main__":
    derive()
