"""Engine-correctness checks for the kill-test interaction LP (src/models/kill_test.py).

These validate the ESTIMATOR on synthetic data with a KNOWN answer — they do not assert any substantive
scientific outcome (the kill-test legitimately reports PASS or DEMOTED depending on the real data).

Run: python tests/test_kill_test.py   (or: pytest tests/test_kill_test.py)
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "models"))
from kill_test import fit_bD  # noqa: E402


def _synthetic(planted_bD, n=240, seed=0):
    """Monthly panel where log(cpi_goods) responds to a shock ONLY in the high-regime, by `planted_bD`
    per unit shock at horizon 1 (cumulative). Returns a frame with the columns fit_bD needs."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2005-01-01", periods=n, freq="MS")
    shock = rng.standard_normal(n)
    regime_lvl = pd.Series(rng.standard_normal(n)).rolling(3, min_periods=1).mean()
    F = (regime_lvl > regime_lvl.median()).astype(float).values
    # price change responds to (F*shock) ONE MONTH AHEAD, so the effect is at horizon 1 and is NOT
    # mechanically inside the contemporaneous own_diff control (which carries only the lagged interaction)
    dchg = 0.002 + 0.0005 * rng.standard_normal(n)
    dchg[1:] += (planted_bD / 100.0) * (F[:-1] * shock[:-1])
    g = np.cumsum(dchg)
    d = pd.DataFrame({
        "date": dates,
        "cpi_goods": np.exp(g) * 100,
        "indpro": np.exp(np.cumsum(0.001 + 0.001 * rng.standard_normal(n))) * 100,
        "oil_price": np.exp(np.cumsum(0.002 * rng.standard_normal(n))) * 60,
    })
    d["d_log_indpro"] = np.log(d.indpro).diff()
    d["d_log_oil"] = np.log(d.oil_price).diff()
    zshock = (shock - shock.mean()) / shock.std()
    return d, zshock, regime_lvl


def test_recovers_planted_positive():
    # engine correctness = recovering the PLANTED coefficient (significance depends on SNR, not the engine)
    ests = []
    for s in range(8):
        d, shock, lvl = _synthetic(planted_bD=1.5, seed=1 + s)
        ests.append(fit_bD(d, "cpi_goods", shock, (lvl > lvl.median()),
                           ["d_log_indpro", "d_log_oil"], h=1)["bD"])
    mean = float(np.mean(ests))
    assert 0.9 < mean < 2.1, f"engine failed to recover planted +1.5%: mean bD={mean:+.2f}% over 8 draws"
    print(f"  recover planted +1.5%: mean bD={mean:+.2f}% over 8 draws  OK")


def test_null_when_absent():
    # no planted interaction -> bD should be small and typically not significant
    hits = 0
    for s in range(20):
        d, shock, lvl = _synthetic(planted_bD=0.0, seed=100 + s)
        r = fit_bD(d, "cpi_goods", shock, (lvl > lvl.median()), ["d_log_indpro", "d_log_oil"], h=1)
        hits += (r["p"] < 0.05)
    assert hits <= 3, f"false-positive rate too high with no planted effect: {hits}/20"
    print(f"  null case false positives: {hits}/20 (<=3 expected)  OK")


if __name__ == "__main__":
    test_recovers_planted_positive()
    test_null_when_absent()
    print("PASS: kill-test interaction engine recovers a known effect and is well-calibrated under the null.")
