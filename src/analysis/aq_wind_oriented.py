"""Wind-oriented observed air quality near San Pedro Bay (§11, confirmatory).

Governed by `prereg/studies/deep_case_spb/deep_case_SPB_preregistration.md` (frozen): monitors <=25 km of the port, downwind =
wind bearing within +-45 deg of the port->monitor direction. Tests whether DOWNWIND NO2 exceeds UPWIND NO2
(the port plume) and whether the excess decays with distance (a pre-registered falsification). AQS hourly NO2
+ NOAA hourly wind (Long Beach). No health claim — concentration only.

Run: python src/analysis/aq_wind_oriented.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/deep_case_SPB"
PORT = (33.72, -118.20)


def _bearing(lat, lon):
    """Compass bearing PORT -> monitor (deg from north)."""
    dlon = np.radians(lon - PORT[1])
    y = np.sin(dlon) * np.cos(np.radians(lat))
    x = (np.cos(np.radians(PORT[0])) * np.sin(np.radians(lat))
         - np.sin(np.radians(PORT[0])) * np.cos(np.radians(lat)) * np.cos(dlon))
    return (np.degrees(np.arctan2(y, x)) + 360) % 360


def _km(lat, lon):
    R = 6371
    p1, p2 = np.radians(lat), np.radians(PORT[0])
    dp, dl = np.radians(PORT[0] - lat), np.radians(PORT[1] - lon)
    return R * 2 * np.arcsin(np.sqrt(np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2))


def analyse() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    # NO2 hourly, LA county, monitors <=25km
    a = pd.read_csv(ROOT / "data/external/aqs_hourly/aqs_hourly_no2_pm25_gatewaycounties_2019_2023.csv",
                    usecols=["State Code", "County Code", "Site Num", "Parameter Name", "Date GMT", "Time GMT",
                             "Sample Measurement", "Latitude", "Longitude"])
    a = a[(a["State Code"] == 6) & (a["County Code"] == 37) & a["Parameter Name"].str.contains("Nitrogen", na=False)]
    a["km"] = _km(a["Latitude"].values, a["Longitude"].values)
    a = a[a["km"] <= 25].copy()
    a["hour"] = pd.to_datetime(a["Date GMT"] + " " + a["Time GMT"], errors="coerce")
    a["bearing"] = _bearing(a["Latitude"].values, a["Longitude"].values)
    a = a.rename(columns={"Sample Measurement": "no2"}).dropna(subset=["hour", "no2"])

    # NOAA wind (Long Beach), hourly
    w = pd.read_csv(ROOT / "data/external/noaa_wind/noaa_hourly_wind_2019_2023.csv")
    w = w[w.complex_id == "san_pedro_bay"].copy()
    w["hour"] = pd.to_datetime(w["DATE"], errors="coerce").dt.floor("h")
    w = w.dropna(subset=["hour", "wind_dir_deg"]).groupby("hour")["wind_dir_deg"].mean().reset_index()

    a["hour"] = a["hour"].dt.floor("h")
    m = a.merge(w, on="hour", how="inner")
    # downwind: wind FROM direction within +-45 deg of (bearing + 180)
    downwind_from = (m["bearing"] + 180) % 360
    diff = (m["wind_dir_deg"] - downwind_from + 180) % 360 - 180
    m["downwind"] = diff.abs() <= 45
    m["upwind"] = ((m["wind_dir_deg"] - m["bearing"] + 180) % 360 - 180).abs() <= 45

    rows = []
    for site, g in m.groupby("Site Num"):
        dw, uw = g.loc[g.downwind, "no2"], g.loc[g.upwind, "no2"]
        rows.append({"site": site, "km_to_port": round(g["km"].iloc[0], 1), "n_hours": len(g),
                     "no2_downwind": round(dw.mean(), 2), "no2_upwind": round(uw.mean(), 2),
                     "downwind_excess": round(dw.mean() - uw.mean(), 2), "n_dw": len(dw), "n_uw": len(uw)})
    tab = pd.DataFrame(rows).sort_values("km_to_port")
    tab.to_csv(OUT / "aq_wind_oriented.csv", index=False, lineterminator="\n")
    print(tab.to_string(index=False))
    # distance-decay falsification: excess should shrink with distance
    corr = np.corrcoef(tab["km_to_port"], tab["downwind_excess"])[0, 1] if len(tab) > 2 else np.nan
    print(f"\nDownwind NO2 excess (downwind - upwind), all monitors: mean {tab.downwind_excess.mean():.2f} ppb")
    print(f"Distance-decay falsification: corr(km, excess) = {corr:.2f} (expect NEGATIVE -> plume decays)")
    return tab


if __name__ == "__main__":
    analyse()
