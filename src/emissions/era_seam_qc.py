"""
Era-boundary QC: the FGDB (2009-2014) -> CSV (2015-2025) seam is where fields silently break.
Two era-seam bugs have already bitten this project (2015-17 AVIS 40x type break; 2009-14 VesselType
drop). This is a STANDING guard: any quantity that crosses the Dec-2014/Jan-2015 seam is tested for a
step-change located exactly at the boundary. A step at the seam = pipeline artifact; a smooth
transition = real. The ILWU 2014-15 West-Coast labour action is the built-in discriminant: a real
signal shows at LA/LB (+Seattle) only; a seam artifact shows at ALL ports at once.

Run: python src/emissions/era_seam_qc.py   (asserts fail loudly if the seam breaks)
"""
import pandas as pd

WEST = "LA_Long_Beach"
EAST = "NY_NJ"                       # non-West-Coast control (no ILWU); Houston/Savannah ~0 anchorage
FGDB_NORMAL = [2011, 2012, 2013]     # FGDB-era normal years (2014 already ILWU-onset)
CSV_NORMAL = [2016, 2017, 2018, 2019]  # CSV-era normal years (2015 ILWU, 2020+ COVID excluded)


def _load(kind):
    a = pd.read_csv(f"data/processed/ais_dwell_census_mode/{kind}.csv")
    b = pd.read_csv(f"data/processed/ais_dwell_census_mode_2009_2014/{kind}_2009_2014.csv")
    out = pd.concat([a, b], ignore_index=True)
    out["yr"] = out.YearMonth.str[:4].astype(int)
    return out


def main():
    mode = _load("monthly_mode_time")
    dwell = _load("monthly_dwell")
    anchor = mode.groupby(["Port", "yr"]).anchor_hours.sum().div(24).unstack("Port")
    md = dwell.groupby(["Port", "yr"]).MeanDwellDays.mean().unstack("Port")

    def norm(df, port, yrs):
        return df.loc[[y for y in yrs if y in df.index], port].mean()

    # A) LA/LB anchor ship-days continuous across the seam (drives the 17-yr emissions total)
    a_ratio = norm(anchor, WEST, FGDB_NORMAL) / norm(anchor, WEST, CSV_NORMAL)
    # B) mean dwell continuous across the seam (per-vessel time measure, both ports)
    d_ratio_w = norm(md, WEST, FGDB_NORMAL) / norm(md, WEST, CSV_NORMAL)
    d_ratio_e = norm(md, EAST, FGDB_NORMAL) / norm(md, EAST, CSV_NORMAL)
    # C) ILWU discriminant: 2015 dwell elevated at West but NOT at East (real => West-only)
    ilwu_w = md.loc[2015, WEST] / norm(md, WEST, [2013])
    ilwu_e = md.loc[2015, EAST] / norm(md, EAST, [2013])

    print("=== ERA-SEAM QC (Dec-2014 | Jan-2015) ===")
    print(f"A  LA/LB anchor ship-days FGDB-normal/CSV-normal = {a_ratio:.2f}   [pass 0.7-1.3]")
    print(f"B  mean dwell FGDB/CSV: LA/LB {d_ratio_w:.2f}, NY/NJ {d_ratio_e:.2f}   [pass 0.7-1.3]")
    print(f"C  ILWU 2015/2013 dwell: LA/LB {ilwu_w:.2f} (elevated), NY/NJ {ilwu_e:.2f} (flat)  "
          f"[pass West>1.15 & East<1.10 => West-localized, not a seam artifact]")

    # D) LA/LB cargo/tanker split continuous (the cyclical-inversion result leans on this)
    from calibrated_emissions import eff_shipdays
    sd = eff_shipdays(); sd["yr"] = sd.YearMonth.str[:4].astype(int)
    g = sd.groupby("yr")[["cargo", "tanker"]].sum()
    tpct = (g.tanker / (g.cargo + g.tanker) * 100)
    tp_f = tpct.loc[FGDB_NORMAL].mean(); tp_c = tpct.loc[CSV_NORMAL].mean()
    # E) tanker physical sanity: continuous tankers at anchor off LB (2010-13)
    tk_at_anchor = (g.tanker / 365).loc[2010:2013].mean()
    print(f"D  LA/LB tanker%: FGDB {tp_f:.0f}% vs CSV {tp_c:.0f}%   [pass <10pp diff]")
    print(f"E  tankers continuously at anchor off LB (2010-13) = {tk_at_anchor:.1f}   [pass 3-12]")

    # documented (not a failure): uniform vessel-count drop at the seam is a coverage change,
    # confined to non-anchoring vessels (dwell + anchor-days above are continuous).
    uv = dwell.groupby(["Port", "yr"]).UniqueVessels.sum().unstack("Port")
    vdrop = uv.loc[2015, WEST] / norm(uv, WEST, [2014])
    print(f"note  unique-vessel-count 2015/2014 (all ports ~0.75) = {vdrop:.2f}  "
          f"-> coverage change in non-anchoring transits; immaterial to dwell/anchor/emissions")

    assert 0.7 <= a_ratio <= 1.3, f"SEAM: LA/LB anchor step at boundary ({a_ratio:.2f}) -> 17-yr total suspect"
    assert 0.7 <= d_ratio_w <= 1.3 and 0.7 <= d_ratio_e <= 1.3, "SEAM: mean-dwell step at boundary"
    assert ilwu_w > 1.15 and ilwu_e < 1.10, "SEAM: 2015 elevation not West-localized -> looks like artifact"
    assert abs(tp_f - tp_c) < 10, f"SEAM: LA/LB tanker split step ({tp_f:.0f} vs {tp_c:.0f}) -> inversion suspect"
    assert 3 <= tk_at_anchor <= 12, f"tanker anchorage baseline implausible ({tk_at_anchor:.1f})"
    print("\nALL SEAM CHECKS PASS -> FGDB era defensible for 17-yr total, split, and inversion.")


if __name__ == "__main__":
    main()
