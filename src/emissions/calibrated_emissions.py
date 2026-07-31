"""
CARB-calibrated anchorage emissions — SINGLE consistent basis (supersedes all bottom-up numbers).

Denominator (pinned): EFFECTIVE container-equivalent congested ship-days at anchor =
    cargo_ship_days + 0.4 * tanker_ship_days   (tanker aux ~0.4x container, IMO Table 17).
CARB is container-only; at LA/LB cargo(70-79) is ~all container, so cargo ≈ container.

Intensities per effective ship-day at anchor:
  NOx  = 1.09 t   (CARB March-2021 container-at-anchor excess 7.5 tpd / 6.9 excess cargo-ship-days)
  PM2.5= 29 kg    (CARB 0.2 tpd / 6.9)
  CO2  = 54 t     (CARB-NOx x physical aux+boiler CO2/NOx ratio ~50; see CO2_NOX_RATIO). METHOD-DEPENDENT
         band [24,69]: lo = Vukic & Lai 2022 generic-fleet inventory (~24, omits reefer), mid = CARB-
         empirical, hi = Zhang 2024 all-source ceiling (Oct-peak OGV = 79% of 2,001 t/day). CARB is central.
Decomposition caveat: at the 2021 peak, in-box ~29 ships x 54 ~= V&L 86 (incl. offshore) x 24 ~= Zhang
2,001 -> the peak TOTAL is robust but the count x intensity split is not; our terrestrial box undercounts
the offshore queue so 2021 is a lower bound. The BASELINE/17-yr absolute is the most method-exposed (~2x
lower at the V&L intensity). Relative change is an activity ratio (intensity cancels) -> robust; LEAD with it.

Caveat: intensity is anchored to CARB's 2021 (0.1%-S, partial-shore-power, mixed-NOx-tier) fleet and
applied flat across 2009-2025, so early-period PM/SOx/NOx (pre-2015 higher-S fuel + Tier 0/I engines)
are conservative (biased low); relative change and 2021 values are unaffected.
"""
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

NOX_PER_SD = 7.5 / 6.9          # t per effective cargo-ship-day (CARB, empirical anchor)
PM_PER_SD = 0.2 / 6.9          # t
TANKER_FRAC = 0.4
ZHANG_PEAK_TPD = 2001.0
# CO2 is derived from CARB-NOx * a PHYSICAL aux+boiler CO2/NOx ratio (not a hand-set Zhang share).
# Reproducible midpoint (config/emission_factors.py, MDO at anchor):
#   aux:    CO2 = SFC 185 * CO2CF 3.206 = 593 g/kWh ; NOx ~12-14 g/kWh (Tier I/II medium-speed, 720rpm)
#           -> aux ratio ~42-49
#   boiler: CO2 = SFC 320 * 3.206 = 1026 g/kWh      ; NOx ~2 g/kWh (auxiliary boiler)
#           -> boiler ratio ~500
#   at anchor the boiler is ~10-15% of hoteling energy, which lifts the aux-dominated blend from ~45
#   to ~50 (mid). The bottom-up model's own ratio (~122) is NOT used: its NOx is the term that failed
#   CARB validation, so CARB-NOx is the anchor and only the RATIO comes from EF physics.
# Zhang's all-source peak is a LOOSE CEILING (OGV < all-source): OGV CO2 at the Oct peak must be < 2,001
# t/day, i.e. ratio < ~62. NOTE: Zhang's EXCESS is landside-dominated (trucks dominate excess CO2), so OGV
# is a MINORITY of 2,001 -- this bounds the top, it is NOT an "~80% subset". CARB-central sits ABOVE
# generic fleet-avg OGV because of LA/LB reefer load (van Duin 2019); we lead with relative change.
# NOTE: the CO2 band below reflects RATIO uncertainty only; CARB's NOx (and hence all three pollutants)
# is a single modelled point estimate whose own uncertainty would scale all pollutants proportionally.
CO2_NOX_RATIO = (45.0, 50.0, 62.0)       # (lo, mid, hi) physical aux+boiler CO2/NOx at anchor
NOX_UNCERT = 0.25              # +/-1sigma on CARB's modelled NOx excess (no published CI; activity-
                               # based OGV inventory uncertainty per IMO 4th GHG Study / port-inventory
                               # discussions). Scales NOx, PM and CO2 absolutes; relative change cancels it.
SCC_CO2 = 190.0                # USD/t, EPA SC-GHG 2023 (2% near-term)
COST_NOX, COST_PM = 13000.0, 600000.0   # USD/t central health damages (near-source urban marginal damages)
# Health-damage per-ton RANGES (USD/t, ~2019-2020$) from reduced-complexity air-quality models
# (EASIUR / AP3 / InMAP) and EPA benefit-per-ton, near-source urban emissions. NOx enters as a secondary
# PM2.5/O3 precursor; primary PM2.5 near a dense coastal population (San Pedro Bay EJ communities) sits in
# the upper part of the sectoral range. Used to BAND the social cost, not to hand-pick it.
COST_NOX_RANGE = (5000.0, 20000.0)      # USD/t NOx  (precursor marginal damage, urban)
COST_PM_RANGE = (300000.0, 1500000.0)   # USD/t primary PM2.5, near-source urban
BASELINE_YEARS = range(2016, 2020)       # normal-year baseline = the four pre-pandemic non-crisis years
                                         # (2016-2019), i.e. strictly AFTER the 2014-15 ILWU slowdown and
                                         # BEFORE the 2020+ COVID surge. 2015 is a known congestion year
                                         # (ILWU) and is excluded so it does not anchor "normal"; normal-
                                         # year anchorage CO2 is itself noisy (0.6-1.3x the window mean),
                                         # so we LEAD with the crisis-vs-normal contrast, which is an
                                         # order of magnitude larger than this baseline noise.
# Independent cross-check (Vukic & Lai 2022, J.Ship.Trade 7:25 = PMC 9684847; peer-reviewed San Pedro
# Bay congestion inventory, Nov-2021): ~45-48 kt CO2 over 86 ships x 22 d = ~24 t CO2/ship-day, using
# fleet-avg aux 1123 kW + boiler 559 kW at 80% LF, EXPLICITLY OMITTING reefer-container load. CARB's
# The CO2 gap is ~2x (V&L's higher assumed CO2/NOx ratio partly offsets their lower power). It reflects
# V&L's fleet-avg power with reefers omitted (LA/LB = top US reefer gateway) + a larger/higher-load LA/LB
# fleet. (Aside: our ORIGINAL generic bottom-up under-counted NOx ~5x vs CARB -- a different, earlier gap;
# don't conflate.) So V&L generic = method LOWER
# bound (~24), CARB-empirical = central (~54); the band spans BOTH. NOTE the 2021-PEAK decomposition is
# ambiguous: our in-box ~29 ships x 54 ~= V&L's 86 (anchor+offshore) x 24 ~= Zhang 2,001 -> similar peak
# TOTAL, different count x intensity. The BASELINE/17-yr absolute is the most method-exposed (in-box count
# x intensity; ~2x lower if the V&L intensity is right). Relative change cancels intensity -> robust.
XCHECK_CO2_PER_SD = 24.0                  # V&L generic-fleet empirical lower bound (t CO2/ship-day)


def _vtype_lookup():
    """MMSI->VesselType from BOTH ping eras (2015-25 CSV pings + 2009-14 FGDB pings).
    Using only the 2015-25 pings drops ~89% of 2009-2014 vessels (they never reappear),
    which zeroed out early-period cargo/tanker ship-days. Union both sources."""
    frames = []
    for path in ("data/processed/ais_dwell_census_mode/port_pings",
                 "data/processed/ais_dwell_census_mode_2009_2014_v2/port_pings_fgdb"):
        d = ds.dataset(path, format="parquet", partitioning="hive")
        frames.append(d.to_table(columns=["MMSI", "VesselType"]).to_pandas())
    vt = pd.concat(frames, ignore_index=True)
    vt["VesselType"] = pd.to_numeric(vt.VesselType, errors="coerce")
    # keep the modal (most frequent) valid type per MMSI; prefer any 70-89 code
    vt = vt.dropna(subset=["VesselType"])
    return vt.groupby("MMSI").VesselType.agg(lambda s: s.mode().iloc[0]).reset_index()


def eff_shipdays():
    a = pd.read_csv("data/processed/ais_dwell_census_mode/monthly_mode_time.csv")
    b = pd.read_csv("data/processed/ais_dwell_census_mode_2009_2014/monthly_mode_time_2009_2014.csv")
    mt = pd.concat([a, b], ignore_index=True)
    mt = mt[mt.Port == "LA_Long_Beach"].copy()
    mt = mt.merge(_vtype_lookup(), on="MMSI", how="left")
    mt["grp"] = np.where(mt.VesselType.between(70, 79), "cargo",
                         np.where(mt.VesselType.between(80, 89), "tanker", "o"))
    sd = mt.groupby(["YearMonth", "grp"])["anchor_hours"].sum().div(24).unstack("grp").fillna(0)
    for c in ("cargo", "tanker"):
        sd[c] = sd.get(c, 0.0)
    sd["eff"] = sd["cargo"] + TANKER_FRAC * sd["tanker"]
    return sd.reset_index()


def main():
    sd = eff_shipdays()
    sd["yr"] = sd.YearMonth.str[:4].astype(int)
    # activity split (Check 1): raw cargo/tanker anchor ship-days; congestion is cargo-driven
    cargo, tank = sd.cargo.sum(), sd.tanker.sum()
    raw = cargo + tank
    print(f"denominator: effective ship-days = cargo + 0.4*tanker")
    print(f"RAW anchor ship-days {raw:,.0f} = cargo {cargo:,.0f} ({cargo/raw*100:.0f}%) + "
          f"tanker {tank:,.0f} ({tank/raw*100:.0f}%); EFFECTIVE {sd.eff.sum():,.0f}")
    # CO2 intensity = CARB-NOx * physical aux+boiler CO2/NOx ratio (mid). Band combines RATIO spread
    # with CARB-NOx uncertainty (+/-25%) in quadrature; Zhang all-source peak caps the top.
    co2_mid = NOX_PER_SD * CO2_NOX_RATIO[1]
    ratio_rel = (CO2_NOX_RATIO[2] - CO2_NOX_RATIO[0]) / (2 * CO2_NOX_RATIO[1])   # ~0.17
    co2_rel = (ratio_rel ** 2 + NOX_UNCERT ** 2) ** 0.5                           # ~0.30 combined
    oct_eff_per_day = sd.loc[sd.YearMonth == "2021-10", "eff"].iloc[0] / 31
    zhang_ceiling = ZHANG_PEAK_TPD / oct_eff_per_day   # max CO2/ship-day if OGV = 100% of Zhang
    # band low = the lower of (within-CARB statistical low) and (V&L generic empirical bound), so the
    # reported band CONTAINS the only peer-reviewed empirical estimate for this port/episode.
    co2_lo = min(co2_mid * (1 - co2_rel), XCHECK_CO2_PER_SD)
    co2_hi = min(co2_mid * (1 + co2_rel), zhang_ceiling)
    print(f"Oct-2021 peak = {oct_eff_per_day:.1f} eff-ship-days/day; Zhang ceiling = {zhang_ceiling:.0f} t/ship-day")
    print(f"CO2 intensity {co2_mid:.0f} t/ship-day  band [{co2_lo:.0f},{co2_hi:.0f}]  method-dependent: "
          f"lo = V&L generic ({XCHECK_CO2_PER_SD:.0f}, no reefer), mid = CARB-empirical, hi = Zhang ceiling")
    print(f"  (CO2/NOx = {CO2_NOX_RATIO[1]:.0f}; within-CARB stat unc +/-{co2_rel*100:.0f}%; "
          f"Oct-peak OGV = {co2_mid*oct_eff_per_day/ZHANG_PEAK_TPD*100:.0f}% of Zhang)")
    print(f"NOx {NOX_PER_SD:.2f} t/ship-day (+/-{NOX_UNCERT*100:.0f}%), PM2.5 {PM_PER_SD*1000:.0f} kg/ship-day  (CARB)")

    out = pd.DataFrame({"YearMonth": sd.YearMonth, "yr": sd.yr, "eff_ship_days": sd.eff,
                        "anchor_NOx_t": sd.eff * NOX_PER_SD, "anchor_PM25_t": sd.eff * PM_PER_SD,
                        "anchor_CO2_t_mid": sd.eff * co2_mid,
                        "anchor_CO2_t_lo": sd.eff * co2_lo, "anchor_CO2_t_hi": sd.eff * co2_hi})
    # assumption/provenance columns so the calibration choices travel WITH the data (not only in prose):
    # this is a CARB-CALIBRATED, method-banded reuse layer for LA/LB anchorage, not a bottom-up inventory.
    out["tanker_weight"] = TANKER_FRAC
    out["NOx_t_per_ship_day_source"] = "CARB 2021 San Pedro Bay container-at-anchor excess (7.5 tpd / 6.9 ships)"
    out["PM25_t_per_ship_day_source"] = "CARB 2021 (0.2 tpd / 6.9 ships)"
    out["CO2_t_per_ship_day_low_source"] = "Vukic & Lai 2022 generic-fleet (~24 t; omits reefer)"
    out["CO2_t_per_ship_day_mid_source"] = "CARB-NOx x physical aux+boiler CO2/NOx ratio ~50 (~54 t)"
    out["CO2_t_per_ship_day_high_source"] = "Zhang et al. 2024 all-source ceiling, Oct peak (~69 t)"
    out["calibration_reference"] = ("CARB (2021) Emissions Impact of Recent Congestion at the California "
                                    "Ports; IMO Fourth GHG Study 2020")
    out.to_csv("outputs/emissions_carb_calibrated_LALB_anchor.csv", index=False)

    ann = out.groupby("yr").agg(eff=("eff_ship_days", "sum"), CO2=("anchor_CO2_t_mid", "sum"),
                                NOx=("anchor_NOx_t", "sum"), PM=("anchor_PM25_t", "sum"))
    base = ann.loc[list(BASELINE_YEARS), "CO2"].mean()
    tot_eff = out.eff_ship_days.sum()
    print(f"\n=== 17-yr LA/LB anchorage totals (calibrated) ===")
    print(f"  effective ship-days {tot_eff:,.0f}; CO2 {ann.CO2.sum()/1e6:.2f} Mt [{ann.CO2.sum()*co2_lo/co2_mid/1e6:.2f}-{ann.CO2.sum()*co2_hi/co2_mid/1e6:.2f}]; "
          f"NOx {ann.NOx.sum():,.0f} t; PM2.5 {ann.PM.sum():,.0f} t")
    print(f"\n=== LEAD: anchorage emissions vs {BASELINE_YEARS.start}-{BASELINE_YEARS.stop-1} baseline ===")
    for y in [2015, 2019, 2021, 2022, 2024]:
        r = ann.loc[y]
        print(f"  {y}: {r.CO2/base:.2f}x   (CO2 {r.CO2/1000:5.0f} kt, NOx {r.NOx:5.0f} t, PM2.5 {r.PM:4.0f} t)")
    y21 = ann.loc[2021]
    sc = (y21.CO2 * SCC_CO2 + y21.NOx * COST_NOX + y21.PM * COST_PM) / 1e6
    base_sc = (base * SCC_CO2 + ann.loc[list(BASELINE_YEARS), "NOx"].mean() * COST_NOX
               + ann.loc[list(BASELINE_YEARS), "PM"].mean() * COST_PM) / 1e6
    # social-cost BAND: propagate CO2 method band + the health-damage per-ton ranges
    sc_lo = (y21.CO2 * co2_lo / co2_mid * SCC_CO2 + y21.NOx * COST_NOX_RANGE[0] + y21.PM * COST_PM_RANGE[0]) / 1e6
    sc_hi = (y21.CO2 * co2_hi / co2_mid * SCC_CO2 + y21.NOx * COST_NOX_RANGE[1] + y21.PM * COST_PM_RANGE[1]) / 1e6
    print(f"\n  2021 environmental social cost ~${sc:.0f}M vs baseline ~${base_sc:.0f}M "
          f"(+${sc-base_sc:.0f}M); damage-factor + CO2 band -> [{sc_lo:.0f}, {sc_hi:.0f}] M")
    print(f"    breakdown (central): CO2 ${y21.CO2*SCC_CO2/1e6:.0f}M, NOx ${y21.NOx*COST_NOX/1e6:.0f}M, "
          f"PM2.5 ${y21.PM*COST_PM/1e6:.0f}M")
    print(f"  per-congested-ship-day: {co2_mid:.0f} t CO2, {NOX_PER_SD:.2f} t NOx, {PM_PER_SD*1000:.0f} kg PM2.5")
    print("wrote outputs/emissions_carb_calibrated_LALB_anchor.csv")

    # invariants (money/physical path): denominator, ratio, Zhang ceiling, early-period not dropped
    assert abs((sd.cargo + TANKER_FRAC * sd.tanker).sum() - sd.eff.sum()) < 1, "eff != cargo+0.4*tanker"
    assert abs(co2_mid / NOX_PER_SD - CO2_NOX_RATIO[1]) < 0.1, "CO2/NOx ratio drift"
    assert co2_mid * oct_eff_per_day <= ZHANG_PEAK_TPD, "OGV CO2 exceeds Zhang all-source ceiling"
    assert sd.loc[sd.yr <= 2014, "cargo"].sum() > 3000, "2009-2014 cargo dropped (VesselType merge bug)"


if __name__ == "__main__":
    main()
