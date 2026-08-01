"""InMAP ISRM exposure surface for the SPB port emissions (§11/§12 — modelled screen only).

Closes the "needs InMAP binary + multi-GB matrix" blocker WITHOUT a Go binary, a full download, or any login:
reads the public InMAP Source-Receptor Matrix (ISRM v1.2.1) directly from anonymous S3 via zarr, pulling only
the ONE source-cell row for the port (~MB). PM2.5(receptor) = Σ_precursor SR[layer0, port_src, :] × emission.
Emissions = 2021 LA/LB hoteling inventory (NOx/SOx/primary-PM). Maps receptors to LA tracts for conditional,
modelled resident- and workplace-weighted exposure summaries. It is not observed or policy-effect validation.

Run: python src/analysis/inmap_exposure.py
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/deep_case_SPB"
PORT_LL = (-118.20, 33.72)                      # lon, lat
INMAP_PROJ = ("+proj=lcc +lat_1=33 +lat_2=45 +lat_0=40 +lon_0=-97 +x_0=0 +y_0=0 "
              "+a=6370997 +b=6370997 +to_meter=1 +no_defs")
# 2021 LA/LB hoteling emissions (t/yr) from emissions_result.md; t/yr -> ug/s
T_PER_YR_TO_UG_PER_S = 1e12 / (365.25 * 24 * 3600)
EMIS_T = {"PrimaryPM25": 115.0, "pNO3": 2766.0, "pSO4": 234.0, "pNH4": 0.0, "SOA": 0.0}


def _isrm():
    import s3fs, zarr
    fs = s3fs.S3FileSystem(anon=True)
    return zarr.open(s3fs.S3Map("inmap-model/isrm_v1.2.1.zarr", s3=fs), mode="r")


def compute() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    g = _isrm()
    src = g["source"][:]                         # grid-cell index per SR source
    rcp = g["receptor"][:]
    N, S, E, W = g["N"][:], g["S"][:], g["E"][:], g["W"][:]   # full-grid cell bounds (m, LCC)
    to_lcc = pyproj.Transformer.from_crs("EPSG:4326", INMAP_PROJ, always_xy=True)
    px, py = to_lcc.transform(*PORT_LL)
    # port source cell = SR source whose grid-cell bounds contain the port
    sb = src
    mask = (W[sb] <= px) & (px < E[sb]) & (S[sb] <= py) & (py < N[sb])
    i = int(np.where(mask)[0][0])
    print(f"port source SR index: {i} (cell bounds {W[sb[i]]:.0f}..{E[sb[i]]:.0f} x {S[sb[i]]:.0f}..{N[sb[i]]:.0f})")

    # PM2.5 at every receptor from the port source (layer 0 = ground)
    pm = np.zeros(len(rcp), dtype="float64")
    for var, t in EMIS_T.items():
        if t == 0:
            continue
        row = g[var][0, i, :].astype("float64")          # ug/m3 per ug/s, for this source
        pm += row * (t * T_PER_YR_TO_UG_PER_S)
    print(f"port-attributable PM2.5: peak {pm.max():.3f} ug/m3, mean {pm.mean():.4f}, receptors {len(pm)}")

    # receptor centroids -> lat/lon; keep the LA basin
    rb = rcp
    cx, cy = (E[rb] + W[rb]) / 2, (N[rb] + S[rb]) / 2
    to_ll = pyproj.Transformer.from_crs(INMAP_PROJ, "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(cx, cy)
    rec = pd.DataFrame({"lon": lon, "lat": lat, "pm25": pm})
    la = rec[(rec.lat.between(33.5, 34.3)) & (rec.lon.between(-118.7, -117.6))].copy()
    la.to_csv(OUT / "inmap_receptor_pm25.csv", index=False, lineterminator="\n")
    print(f"LA-basin receptors: {len(la)}, PM2.5 peak {la.pm25.max():.3f}")
    return la


def equity(la: pd.DataFrame) -> None:
    import geopandas as gpd
    from shapely.geometry import Point
    ces = gpd.read_file("zip://data/external/calenviroscreen/calenviroscreen50_shp.zip!"
                        "calenviroscreen50results_F_070126.shp/CES5_final_shapefile.shp").to_crs("EPSG:4326")
    tcol = [c for c in ces.columns if c.lower() in ("tract", "geoid")][0]
    pts = gpd.GeoDataFrame(la, geometry=[Point(xy) for xy in zip(la.lon, la.lat)], crs="EPSG:4326")
    j = gpd.sjoin(pts, ces[[tcol, "geometry"]], how="inner", predicate="within")
    tract_pm = j.groupby(tcol)["pm25"].mean().reset_index()
    tract_pm["tract"] = tract_pm[tcol].astype("Int64").astype(str).str.zfill(11)
    acs = pd.read_csv(ROOT / "data/external/acs/acs5_2022_port_county_tracts.csv")
    acs = acs[acs.complex_id == "san_pedro_bay"]
    for c in ["median_hh_income", "total_pop"]:
        acs[c] = pd.to_numeric(acs[c], errors="coerce"); acs.loc[acs[c] < 0, c] = np.nan
    acs["geoid"] = acs["geoid"].astype(str).str.zfill(11)
    resident = acs.merge(tract_pm[["tract", "pm25"]], left_on="geoid", right_on="tract", how="inner").dropna(
        subset=["pm25", "total_pop"])
    m = resident.dropna(subset=["median_hh_income"]).copy()
    m["inc_q"] = pd.qcut(m["median_hh_income"], 5, labels=["Q1_low", "Q2", "Q3", "Q4", "Q5_high"])
    grp = m.groupby("inc_q").apply(lambda d: np.average(d.pm25, weights=d.total_pop))
    print("\nInMAP-modelled port PM2.5 exposure by income quintile (ug/m3):")
    print(grp.round(5).to_string())
    print(f"Q1_low/Q5_high ratio: {grp.iloc[0]/grp.iloc[-1]:.2f}x")
    grp.rename("inmap_pm25_by_income").to_csv(OUT / "inmap_equity.csv", lineterminator="\n")

    wac = pd.read_csv(ROOT / "data/external/lodes/ca_wac_S000_JT00_2022.csv.gz",
                      usecols=["w_geocode", "C000"], dtype={"w_geocode": str})
    wac["tract"] = wac["w_geocode"].str.zfill(15).str[:11]
    workers = wac.groupby("tract", as_index=False)["C000"].sum().merge(
        tract_pm[["tract", "pm25"]], on="tract", how="inner")
    workers = workers[workers["tract"].str.startswith("06037")]
    resident_mean = np.average(resident.pm25, weights=resident.total_pop)
    worker_mean = np.average(workers.pm25, weights=workers.C000)
    pd.DataFrame([
        {"weight_basis": "resident_population", "tracts": len(resident),
         "weight_total": int(resident.total_pop.sum()),
         "modelled_pm25_ug_m3": resident_mean},
        {"weight_basis": "workplace_employment", "tracts": len(workers),
         "weight_total": int(workers.C000.sum()), "modelled_pm25_ug_m3": worker_mean},
    ]).to_csv(OUT / "inmap_resident_worker_exposure.csv", index=False, float_format="%.6f",
              lineterminator="\n")
    print(f"Resident-weighted mean: {resident_mean:.5f} ug/m3; workplace-weighted mean: {worker_mean:.5f} ug/m3")


if __name__ == "__main__":
    cached = OUT / "inmap_receptor_pm25.csv"
    equity(pd.read_csv(cached) if cached.exists() else compute())
