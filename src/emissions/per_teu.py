"""
Per-TEU normalisation (the 3.4x headline) — standing, deposit-reproducible.

Container-consistent ratio: CARGO (container) anchor ship-days per million container-TEU, 2021 vs the
2009-2016 baseline (baseline window set by TEU-data availability). Sources are BOTH in the deposit:
the mode census (cargo anchor ship-days) and data/external/la_monthly_teu.csv (Port of LA container
stats). Emission intensity does not enter -> this is a pure activity ratio.

Run: python src/emissions/per_teu.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd
from calibrated_emissions import eff_shipdays


def main():
    sd = eff_shipdays()                                   # cargo/tanker anchor ship-days/month (deposited census)
    sd["yr"] = sd.YearMonth.str[:4].astype(int)
    teu = pd.read_csv("data/external/la_monthly_teu.csv")  # deposited TEU
    m = sd.merge(teu, on="YearMonth", how="inner")
    base = m[m.yr <= 2016]; y21 = m[m.yr == 2021]
    per = lambda df: df.cargo.sum() / (df.monthly_teu.sum() / 1e6)   # cargo ship-days per MTEU
    b, a = per(base), per(y21)
    ratio = a / b
    print(f"per-TEU (cargo container ship-days / MTEU): 2009-16 {b:.0f}  2021 {a:.0f}  -> {ratio:.2f}x")
    print(f"  (baseline months {len(base)}, 2021 months {len(y21)})")
    assert 3.0 <= ratio <= 3.8, f"per-TEU ratio {ratio:.2f} off the reported 3.4x -> check TEU/census sources"
    print("PASS: 2021 anchorage burden ~3.4x the 2009-2016 baseline per unit container cargo.")


if __name__ == "__main__":
    main()
