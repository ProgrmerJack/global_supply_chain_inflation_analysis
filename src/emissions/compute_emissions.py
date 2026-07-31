"""
Bottom-up hoteling emissions from mode-resolved vessel time (IMO 4th GHG 2020).

For each vessel-port-month we have hours in each mode (anchor/berth/manoeuvre/transit).
Congestion-driven emissions are the AUXILIARY ENGINE + BOILER load during hoteling
(main engine is off at anchor/berth). For each mode:
    E_pollutant = hours × ( aux_kW × EF_aux + boiler_kW × EF_boiler )
aux/boiler power come from IMO Table 17 (by vessel class × size × phase), weighted across
the IMO classes each NMEA cargo/tanker group maps to. EFs are fuel-specific (North
American ECA regime for LA/LB). ME excluded (≈0 at hoteling; not the congestion signal).

Outputs per (Port, YearMonth, mode): CO2, NOx, SOx, PM2.5 (tonnes).
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import config.emission_factors as ef  # noqa: E402

# unknown_hoteling = SOG<0.5 outside charted zones: still hoteling -> berth-phase power,
# but kept as its own mode so it never inflates the anchor (congestion) figure.
MODES = ["anchor", "berth", "manoeuvre", "transit", "unknown_hoteling"]
MODE_PHASE_IDX = {"anchor": 1, "berth": 0, "manoeuvre": 2, "transit": 3, "unknown_hoteling": 0}
MODE_COL = {m: f"{m}_hours" for m in MODES}


def impute_size(length, beam, draft, is_container):
    L = float(length) if length and length > 0 else 200.0
    if is_container:
        return max(200.0, 3.5e-4 * L ** 3)          # length(m)->TEU (monotonic; 300m~9.5k, 400m~22k)
    B = float(beam) if beam and beam > 0 else L * 0.15
    T = float(draft) if draft and draft > 0 else L * 0.05
    return max(500.0, 0.615 * L * B * T)             # ~displacement×0.8 (Cb 0.75) -> DWT


def _lookup(imo_class, size, phase_idx):
    for upper, boiler, aux in ef.TABLE17[imo_class]:
        if size <= upper:
            return boiler[phase_idx], aux[phase_idx]
    last = ef.TABLE17[imo_class][-1]
    return last[1][phase_idx], last[2][phase_idx]


@lru_cache(maxsize=200_000)
def _vessel_power_cached(grp, L, B, T, year):
    sp = ef.shore_power_share(year) if year is not None else 0.0
    boiler = [0.0] * 4; aux = [0.0] * 4
    for cls, w in ef.CLASS_WEIGHTS[grp].items():
        size = impute_size(L, B, T, cls == "Container")
        for pi in range(4):
            b, a = _lookup(cls, size, pi)
            if pi == 0 and cls in ef.SHORE_POWER_CLASSES:
                a *= (1.0 - sp)
            boiler[pi] += w * b; aux[pi] += w * a
    return boiler, aux


def vessel_power(vessel_type, length, beam, draft, year=None):
    """Weighted (boiler_kW[4], aux_kW[4]); shore-power reduces berth aux for container/reefer.
    Cached on rounded dims so the 268k-row full run stays fast."""
    grp = "cargo" if 70 <= vessel_type <= 79 else "tanker"
    L = round(float(length)) if length and length > 0 else 200
    B = round(float(beam)) if beam and beam > 0 else 0
    T = round(float(draft) * 2) / 2 if draft and draft > 0 else 0
    b, a = _vessel_power_cached(grp, L, B, T, year)
    return np.array(b), np.array(a)


def _efs(year: int):
    """Per-kWh emission factors for aux engine and boiler this year (fuel/ECA + NOx tier)."""
    fuel, s = ef.fuel_for_year(year)
    cf = ef.CO2_CF[fuel]
    # BUG FIX: the operating fleet in year Y is a MIX of build years (mostly pre-2016 =
    # Tier I/II), not all Tier III. Use a build-year-weighted fleet NOx EF: Tier III only
    # for the ~(year-2016) newest cohort. Shares are rough fleet-turnover approximations.
    f3 = 0.0 if year < 2016 else min(0.45, 0.05 * (year - 2015))   # ~5%/yr Tier III since 2016
    f2 = 0.55 if year >= 2011 else 0.15                            # Tier II bulk of 2011+ fleet
    f1 = max(0.0, 1 - f2 - f3)
    aux_nox = (f1 * ef.nox_ef("I", ef.N_RPM["aux"]) + f2 * ef.nox_ef("II", ef.N_RPM["aux"])
               + f3 * ef.nox_ef("III", ef.N_RPM["aux"]))
    aux = {
        "CO2": ef.SFC["aux"][fuel] * cf,
        "SOx": ef.SFC["aux"][fuel] * ef.SOX_S_TO_SOX * s,
        "NOx": aux_nox,
        "PM25": ef.PM10_EF[fuel] * ef.PM25_FRACTION,
    }
    boiler = {
        "CO2": ef.SFC["boiler"][fuel] * cf,
        "SOx": ef.SFC["boiler"][fuel] * ef.SOX_S_TO_SOX * s,
        "NOx": 2.0,                       # boilers: low, ~2 g/kWh (not engine Tier)
        "PM25": ef.PM10_EF[fuel] * ef.PM25_FRACTION,
    }
    return aux, boiler


def compute(mode_df: pd.DataFrame) -> pd.DataFrame:
    """mode_df: per-vessel-month rows with MMSI, Port, YearMonth, VesselType, Length, Width,
    Draft, and *_hours columns. Returns per (Port, YearMonth, mode) emissions in tonnes."""
    df = mode_df.copy()
    df["year"] = df["YearMonth"].str[:4].astype(int)
    df["vt"] = pd.to_numeric(df["VesselType"], errors="coerce").fillna(70).astype(int)
    # cache power per unique (vt-group, size-bin) is complex; vectorize per row (fast enough).
    recs = []
    for (year,), g in df.groupby(["year"]):
        aux_ef, boi_ef = _efs(year)
        for _, r in g.iterrows():
            boiler_kw, aux_kw = vessel_power(r["vt"], r.get("Length"), r.get("Width"), r.get("Draft"), year=year)
            for mode in MODES:
                h = float(r.get(f"{mode}_hours", 0) or 0)
                if h <= 0:
                    continue
                pi = MODE_PHASE_IDX[mode]
                ak, bk = aux_kw[pi], boiler_kw[pi]
                for pol in ["CO2", "NOx", "SOx", "PM25"]:
                    grams = h * (ak * aux_ef[pol] + bk * boi_ef[pol])
                    recs.append((r["Port"], r["YearMonth"], mode, pol, grams / 1e6))  # -> tonnes
    out = pd.DataFrame(recs, columns=["Port", "YearMonth", "mode", "pollutant", "tonnes"])
    return out.groupby(["Port", "YearMonth", "mode", "pollutant"])["tonnes"].sum().reset_index()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode-file", required=True)
    ap.add_argument("--out", default="outputs/emissions_by_mode.csv")
    ap.add_argument("--port")
    ap.add_argument("--year-min", type=int); ap.add_argument("--year-max", type=int)
    a = ap.parse_args()
    m = pd.read_csv(a.mode_file)
    if a.port:
        m = m[m.Port == a.port]
    if a.year_min:
        m = m[m.YearMonth.str[:4].astype(int).between(a.year_min, a.year_max or a.year_min)]
    res = compute(m)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    res.to_csv(a.out, index=False)
    print(f"wrote {a.out} ({len(res)} rows)")
