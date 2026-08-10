"""
Anchor/berth zone builder: authoritative NOAA charted anchorages + data-driven berths.

The first-pass hand-drawn boxes mislabeled ~36% of hoteling time. Port geometry is too
varied for rectangles. This builds defensible zones per port:

  ANCHOR = NOAA charted Anchorage Areas (CFR Title 33), fetched from the NOAA hosted
           Anchorages FeatureServer (config/geometry/noaa_anchorages.geojson), dissolved and
           buffered ~450 m to absorb crisis overflow just outside charted edges.
  BERTH  = grid the retained SOG<0.5 hoteling pings (~150 m cells); occupied cells that
           fall OUTSIDE the anchor zone are the terminal berths, dissolved into polygons.

Ports with no charted anchorage in-box (e.g. Houston = ship-channel port) get an empty
anchor zone and all hoteling -> berth, which matches physical reality.

Output: config/geometry/port_mode_zones_v2.geojson (Port, zone_type in {anchor,berth}, geometry).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.compute as pc
import geopandas as gpd
from shapely.geometry import box
from shapely.ops import unary_union

PINGS = "data/processed/ais_dwell_census_mode/port_pings"
NOAA = "config/geometry/noaa_anchorages.geojson"
PORTS = {
    "LA_Long_Beach": (33.62, 33.82, -118.31, -118.09),
    "NY_NJ":         (40.57, 40.77, -74.13, -73.92),
    "Houston":       (29.62, 29.88, -95.08, -94.82),
    "Savannah":      (31.95, 32.18, -81.17, -80.92),
    "Seattle":       (47.48, 47.72, -122.48, -122.22),
}
SAMPLE = [(2021, 9), (2021, 10), (2021, 11), (2022, 1), (2015, 6), (2019, 6), (2024, 6)]
RES = 0.0015
MIN_CELL_PINGS = 200
ANCHOR_BUFFER_DEG = 0.004   # ~450 m overflow buffer on charted anchorages
BERTH_BUFFER_DEG = 0.0009   # merge adjacent berth cells (~100 m)


def hoteling_grid(dset, port, frame):
    lat0, lat1, lon0, lon1 = frame
    mfilt = None
    for (y, m) in SAMPLE:
        c = (pc.field("year") == y) & (pc.field("month") == m)
        mfilt = c if mfilt is None else (mfilt | c)
    t = dset.to_table(columns=["LAT", "LON"],
                      filter=(pc.field("Port") == port) & (pc.field("SOG") < 0.5) & mfilt).to_pandas()
    t = t.dropna()
    t = t[(t.LAT.between(lat0, lat1)) & (t.LON.between(lon0, lon1))]
    ij = pd.DataFrame({"i": ((t.LAT - lat0) / RES).astype(int), "j": ((t.LON - lon0) / RES).astype(int)})
    return ij.value_counts().rename("n").reset_index(), lat0, lon0


def main():
    dset = ds.dataset(PINGS, format="parquet", partitioning="hive")
    noaa = gpd.read_file(NOAA)
    recs = []
    for port, frame in PORTS.items():
        # anchor zone = charted anchorages (buffered), clipped to frame
        lat0, lat1, lon0, lon1 = frame
        frame_box = box(lon0, lat0, lon1, lat1)
        a = noaa[noaa.Port == port]
        anchor_geom = None
        if len(a):
            anchor_geom = unary_union(list(a.geometry)).buffer(ANCHOR_BUFFER_DEG).intersection(frame_box)
            recs.append({"Port": port, "zone_type": "anchor", "geometry": anchor_geom})
        # berth = dense hoteling cells outside the anchor zone
        grid, gla0, glo0 = hoteling_grid(dset, port, frame)
        occ = grid[grid.n >= MIN_CELL_PINGS]
        cells = [box(glo0 + j * RES, gla0 + i * RES, glo0 + (j + 1) * RES, gla0 + (i + 1) * RES)
                 for i, j in zip(occ.i, occ.j)]
        berth_geom = unary_union([c.buffer(BERTH_BUFFER_DEG) for c in cells]).buffer(-BERTH_BUFFER_DEG * 0.5)
        if anchor_geom is not None:
            berth_geom = berth_geom.difference(anchor_geom)
        if not berth_geom.is_empty:
            recs.append({"Port": port, "zone_type": "berth", "geometry": berth_geom})
        na = 1 if anchor_geom is not None and not anchor_geom.is_empty else 0
        print(f"{port:15s} anchor={'yes' if na else 'NONE'}  berth_cells={len(occ)}", flush=True)

    out = gpd.GeoDataFrame(recs, geometry="geometry", crs="EPSG:4326")
    out.to_file("config/geometry/port_mode_zones_v2.geojson", driver="GeoJSON")
    print("wrote config/geometry/port_mode_zones_v2.geojson  rows:", len(out))


if __name__ == "__main__":
    main()
