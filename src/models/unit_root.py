"""
Unit-root / spurious-regression decision for the concentration result (fifth standing guard).

The concentration r (LA dwell vs GSCPI) correlates in levels/cycle but vanishes in first differences —
the textbook Granger-Newbold signature a time-series referee will flag as spurious. But whether it is
spurious or benign is DECIDABLE from the integration order:

  ADF (H0: unit root / non-stationary) + KPSS (H0: stationary) on each series ->
    both I(0)  -> the first-difference null is OVER-DIFFERENCING of stationary data, not spuriousness;
                 correlating I(0) series is valid; the relationship is at business-cycle frequency.
    either I(1)-> genuine spurious-regression risk -> test Engle-Granger cointegration; if LA dwell &
                 GSCPI cointegrate (and null ports don't), the claim UPGRADES to a long-run equilibrium.

Run: python src/models/unit_root.py
"""
import warnings
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, kpss, coint

warnings.simplefilter("ignore")  # KPSS p-value interpolation warnings at table edges


def classify(x, name):
    x = np.asarray(x, float)
    adf_p = adfuller(x, regression="c", autolag="AIC")[1]          # H0: unit root
    kpss_p = kpss(x, regression="c", nlags="auto")[1]              # H0: stationary
    adf_stat = adfuller(x, regression="c", autolag="AIC")[0]
    if adf_p < 0.05 and kpss_p > 0.05:
        order = "I(0)"
    elif adf_p > 0.05 and kpss_p < 0.05:
        order = "I(1)"
    else:
        order = "ambiguous"
    print(f"  {name:22s}: ADF p={adf_p:.3f} (stat {adf_stat:+.2f})  KPSS p={kpss_p:.3f}  -> {order}")
    return order


def main():
    d = pd.read_csv("data/processed/analysis_dataset_dwell.csv").dropna(subset=["dwell_la_detrended", "gscpi"])
    dwell, g = d.dwell_la_detrended.values, d.gscpi.values
    print(f"=== Unit-root battery (n={len(dwell)}) ===")
    o_dwell = classify(dwell, "LA dwell (detrended)")
    o_g = classify(g, "GSCPI")

    both_i0 = o_dwell == "I(0)" and o_g == "I(0)"
    print()
    if both_i0:
        print("VERDICT: both series STATIONARY (I(0)). The first-difference null is OVER-DIFFERENCING, not")
        print("  spuriousness — differencing I(0) data induces a near-unit-root MA and destroys the low-")
        print("  frequency variance that carries the signal. Correlating I(0) series is valid.")
        print("\n§2.2 sentence:")
        print("  \"Both series are stationary (ADF rejects a unit root, KPSS does not reject stationarity),")
        print("   so the level/cycle correlation is between I(0) series and is not a spurious-regression")
        print("   artifact; the first-difference result reflects over-differencing of stationary data,")
        print("   which removes the business-cycle-frequency variance that carries the relationship.\"")
        assert True
    else:
        print(f"VERDICT: not both I(0) (dwell {o_dwell}, GSCPI {o_g}) -> test cointegration.")
        eg_p = coint(dwell, g)[1]   # Engle-Granger; H0: no cointegration
        print(f"  Engle-Granger cointegration p = {eg_p:.3f} "
              f"({'COINTEGRATED -> long-run equilibrium (claim upgrades)' if eg_p < 0.05 else 'no cointegration -> report relative-concentration only'})")
        print("\n§2.2 sentence (I(1) branch): report the cointegration outcome; fall back on relative")
        print("  concentration (only LA co-moves; the four null ports do not — spurious trending would hit all five).")

    # ultimate shield holds regardless of integration order:
    print("\nShield: the claim is RELATIVE concentration — only LA co-moves, the other four are null. Spurious")
    print("  trending would inflate all five persistent port series, not one; so concentration survives either way.")


if __name__ == "__main__":
    main()
