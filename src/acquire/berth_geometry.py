"""Acquire container-terminal / quay geometry from OpenStreetMap (Overpass) for the gateways (NS-G1 / Pillar B).

Pillar B currently resolves only 30.4% of stationary episodes to berth/anchor because only ANCHOR polygons
exist (noaa_anchorages.geojson). This pulls quays / port-industrial / named container-terminal features near
each gateway (bbox from config/geometry/port_areas_usace.geojson) so a buffered berth zone can be built, lifting
berth/anchor resolution toward the frozen >=90% gate. No auth.

Run: python src/acquire/berth_geometry.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_util import GATEWAY_COUNTIES, ROOT

OUT = ROOT / "data/external/berth_geometry"
OVERPASS = "https://overpass-api.de/api/interpreter"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0",
       "Accept": "application/json, */*", "Content-Type": "application/x-www-form-urlencoded"}


def _bboxes() -> dict[str, tuple[float, float, float, float]]:
    """Per-gateway bbox (s,w,n,e) from the USACE port-area polygons, padded slightly."""
    gj = json.loads((ROOT / "config/geometry/port_areas_usace.geojson").read_text())
    out = {}
    for f in gj["features"]:
        cid = f["properties"].get("port_complex_id")
        if cid not in GATEWAY_COUNTIES:
            continue
        xs, ys = [], []
        def walk(coords):
            if isinstance(coords[0], (int, float)):
                xs.append(coords[0]); ys.append(coords[1])
            else:
                for c in coords:
                    walk(c)
        walk(f["geometry"]["coordinates"])
        pad = 0.03
        out[cid] = (min(ys) - pad, min(xs) - pad, max(ys) + pad, max(xs) + pad)
    return out


def _query(s, w, n, e) -> list[dict]:
    q = f"""[out:json][timeout:90];
(
 way["man_made"="quay"]({s},{w},{n},{e});
 way["industrial"="port"]({s},{w},{n},{e});
 way["landuse"="industrial"]["name"~"[Tt]erminal|[Cc]ontainer|APM|Maersk|Wharf|Marine",i]({s},{w},{n},{e});
 way["harbour"="yes"]({s},{w},{n},{e});
);
out geom;"""
    import urllib.parse
    body = urllib.parse.urlencode({"data": q}).encode()
    req = urllib.request.Request(OVERPASS, data=body, headers=_UA, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=120).read()).get("elements", [])


def acquire(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    features, manifest = [], []
    for cid, (s, w, n, e) in _bboxes().items():
        try:
            els = _query(s, w, n, e)
        except Exception as ex:
            print(f"  ! {cid}: {str(ex)[:60]}"); time.sleep(2); continue
        n_feat = 0
        for el in els:
            geom = el.get("geometry")
            if not geom:
                continue
            coords = [[p["lon"], p["lat"]] for p in geom]
            closed = len(coords) > 3 and coords[0] == coords[-1]
            features.append({"type": "Feature",
                             "properties": {"complex_id": cid, "osm_id": el.get("id"),
                                            **{k: v for k, v in el.get("tags", {}).items()
                                               if k in ("name", "man_made", "industrial", "harbour", "landuse")}},
                             "geometry": {"type": "Polygon" if closed else "LineString",
                                          "coordinates": [coords] if closed else coords}})
            n_feat += 1
        manifest.append({"complex_id": cid, "features": n_feat, "bbox": f"{s:.3f},{w:.3f},{n:.3f},{e:.3f}"})
        print(f"  + {cid}: {n_feat} terminal/quay features")
        time.sleep(1.5)                      # be gentle to Overpass
    dest = out / "terminals_osm.geojson"
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    import pandas as pd
    man = pd.DataFrame(manifest)
    man["source"] = "OpenStreetMap Overpass"; man["access_date"] = date.today().isoformat()
    man["sha256"] = hashlib.sha256(dest.read_bytes()).hexdigest()
    man.to_csv(out / "manifest.csv", index=False, lineterminator="\n")
    print(f"  = {len(features)} features -> {dest.name}")


if __name__ == "__main__":
    acquire()
