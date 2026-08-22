"""
Unit-root / spurious-regression decision for the concentration result (fifth standing guard).

The co-movement r (LA dwell vs GSCPI) correlates in levels/cycle but ATTENUATES in first differences -
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


def classify(x, name):
    """Report the integration order, and say when a KPSS p-value is a BOUND rather than a point.

    statsmodels interpolates KPSS p-values inside [0.01, 0.10] and returns the nearest bound with an
    InterpolationWarning when the statistic falls outside its lookup table. This script used to call
    warnings.simplefilter("ignore") at import, which swallowed that warning and let a bound be read as a
    point estimate: LA dwell printed "KPSS p=0.100" when the honest statement is "p > 0.10". That reading
    reached the manuscript, where a referee caught it. The warning is now caught and reported, never
    suppressed.
    """
    x = np.asarray(x, float)
    adf_stat, adf_p = adfuller(x, regression="c", autolag="AIC")[:2]   # H0: unit root
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        kpss_stat, kpss_p = kpss(x, regression="c", nlags="auto")[:2]  # H0: stationary
    truncated = any("outside of the range" in str(w.message) for w in caught)
    # A truncated value never flips the verdict: the true p lies further from 0.05 than the number
    # returned, so the I(0)/I(1) decision below is unaffected either way.
    bound = ">" if truncated and kpss_p >= 0.10 else ("<" if truncated else "=")
    if adf_p < 0.05 and kpss_p > 0.05:
        order = "I(0)"
    elif adf_p > 0.05 and kpss_p < 0.05:
        order = "I(1)"
    else:
        order = "ambiguous"
    note = "  [KPSS stat outside table: p is a BOUND, not a point]" if truncated else ""
    print(f"  {name:22s}: ADF p={adf_p:.3f} (stat {adf_stat:+.2f})  "
          f"KPSS p{bound}{kpss_p:.3f} (stat {kpss_stat:.3f})  -> {order}{note}")
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
        print("  spuriousness - differencing I(0) data induces a near-unit-root MA and destroys the low-")
        print("  frequency variance that carries the signal. Correlating I(0) series is valid.")
        print("\nSentence for the manuscript:")
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
        print("\nSentence for the manuscript (I(1) branch): report the cointegration outcome. Do NOT fall")
        print("  back on the cross-port pattern -- see the note below on why that is not evidence.")

    # An earlier version printed a "shield" here: that spurious trending would inflate all five port
    # series rather than one, so the cross-port pattern rules out spuriousness. That argument does not
    # hold and has been removed rather than reworded. Spurious correlation depends on the persistence of
    # EACH pair, so a shared low-frequency nuisance inflates whichever series carries business-cycle
    # variance and leaves flat series flat; the four nulls are equally consistent with "only LA/LB has a
    # low-frequency component available to be matched". The defence against spuriousness is the
    # integration order tested above plus survival of linear detrending -- not the cross-port contrast,
    # which the difference test (inference.py section 1d) declines to claim in any case.
    print("\nNote: the cross-port pattern is NOT evidence against spuriousness (see the comment here).")
    print("  The integration order above, plus survival of linear detrending, is.")


if __name__ == "__main__":
    main()
