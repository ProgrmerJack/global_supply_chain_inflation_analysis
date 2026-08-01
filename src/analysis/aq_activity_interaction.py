"""AQ activity-interaction (§11 refinement) — does downwind NO2 rise WITH port congestion, net of the
marine/urban air-mass confound that sank the naive contrast?

The within-month downwind-minus-upwind gap differences out the monthly air-mass level (both measured the same
month). If that gap WIDENS when port congestion is high (net of monitor + calendar-month fixed effects), the
port plume is real net of the confound. Falsification: FUTURE congestion must not predict the current gap.

Governed by `prereg/studies/deep_case_spb/deep_case_SPB_preregistration.md` (beta on PortActivity×Downwind). Run once.
Run: python src/analysis/aq_activity_interaction.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/deep_case_SPB"
PORT = (33.72, -118.20)


def _bearing(lat, lon):
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


def _monthly_gap() -> pd.DataFrame:
    a = pd.read_csv(ROOT / "data/external/aqs_hourly/aqs_hourly_no2_pm25_gatewaycounties_2019_2023.csv",
                    usecols=["State Code", "County Code", "Site Num", "Parameter Name", "Date GMT", "Time GMT",
                             "Sample Measurement", "Latitude", "Longitude"])
    a = a[(a["State Code"] == 6) & (a["County Code"] == 37) & a["Parameter Name"].str.contains("Nitrogen", na=False)]
    a = a[_km(a["Latitude"].values, a["Longitude"].values) <= 25].copy()
    a["hour"] = pd.to_datetime(a["Date GMT"] + " " + a["Time GMT"], errors="coerce").dt.floor("h")
    a["bearing"] = _bearing(a["Latitude"].values, a["Longitude"].values)
    a = a.rename(columns={"Sample Measurement": "no2"}).dropna(subset=["hour", "no2"])

    w = pd.read_csv(ROOT / "data/external/noaa_wind/noaa_hourly_wind_2019_2023.csv")
    w = w[w.complex_id == "san_pedro_bay"].copy()
    w["hour"] = pd.to_datetime(w["DATE"], errors="coerce").dt.floor("h")
    w = w.dropna(subset=["hour", "wind_dir_deg"]).groupby("hour")["wind_dir_deg"].mean().reset_index()

    m = a.merge(w, on="hour", how="inner")
    m["downwind"] = (((m["wind_dir_deg"] - (m["bearing"] + 180) + 180) % 360 - 180).abs() <= 45)
    m["upwind"] = (((m["wind_dir_deg"] - m["bearing"] + 180) % 360 - 180).abs() <= 45)
    m["ym"] = m["hour"].dt.strftime("%Y-%m")
    rows = []
    for (site, ym), g in m.groupby(["Site Num", "ym"]):
        dw, uw = g.loc[g.downwind, "no2"], g.loc[g.upwind, "no2"]
        if len(dw) >= 20 and len(uw) >= 20:
            rows.append({"site": site, "ym": ym, "gap": dw.mean() - uw.mean()})
    return pd.DataFrame(rows)


def _congestion() -> pd.Series:
    d = pd.read_csv(ROOT / "data/processed/ais_dwell_census_mode/monthly_mode_time.csv")
    return d[d.Port == "LA_Long_Beach"].groupby("YearMonth")["anchor_hours"].sum().rename("congestion")


def _fe_ols(df, y, x):
    """Slope of y on x after removing site + calendar-month means (two-way FE), + Pearson r."""
    d = df.copy()
    d["cmon"] = d["ym"].str[5:7]
    for fe in ["site", "cmon"]:
        d[y] = d[y] - d.groupby(fe)[y].transform("mean")
        d[x] = d[x] - d.groupby(fe)[x].transform("mean")
    xv, yv = d[x].values, d[y].values
    beta = np.polyfit(xv, yv, 1)[0]
    r = np.corrcoef(xv, yv)[0, 1]
    return beta, r, len(d)


def analyse() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    gap = _monthly_gap()
    cong = _congestion()
    df = gap.merge(cong, left_on="ym", right_index=True, how="inner")
    df["congestion_k"] = df["congestion"] / 1000.0
    # future (lead) congestion for the falsification: congestion 3 months AHEAD, aligned to current ym
    lead = pd.DataFrame({"ym": (pd.to_datetime(cong.index + "-01") - pd.DateOffset(months=3)).strftime("%Y-%m"),
                         "congestion_lead3": cong.values})
    df = df.merge(lead, on="ym", how="left")
    df["congestion_lead3_k"] = df["congestion_lead3"] / 1000.0

    b, r, n = _fe_ols(df, "gap", "congestion_k")
    bl, rl, _ = _fe_ols(df.dropna(subset=["congestion_lead3_k"]), "gap", "congestion_lead3_k")
    df.to_csv(OUT / "aq_activity_interaction.csv", index=False, lineterminator="\n")
    print(f"n monitor-months: {n} | mean downwind-upwind gap: {df.gap.mean():.2f} ppb")
    print(f"beta(gap on congestion), site+month FE: {b:+.3f} ppb per 1000 anchor-hrs   (Pearson r={r:+.2f})")
    print(f"FALSIFICATION beta(gap on FUTURE congestion +3mo): {bl:+.3f} (r={rl:+.2f}) — should be ~0/weaker")
    verdict = ("PORT SIGNAL SURVIVES: downwind gap widens with congestion, future does not"
               if b > 0 and abs(b) > abs(bl) else
               "NOT RESCUED: gap does not rise with congestion net of confounds")
    print(f"Verdict: {verdict}")


if __name__ == "__main__":
    analyse()
