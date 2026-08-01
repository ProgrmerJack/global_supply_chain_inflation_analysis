"""Speed-filtered robustness check for the San Pedro Bay ring mass balance (Paper D, claim S01).

WHY THIS EXISTS. Paper D's headline ring account uses a cached GFW cargo-presence product that is
NOT speed-filtered, so "presence" mixes vessels waiting with vessels merely transiting. The offshore
rings (50-300 nm) mechanically contain far more through-traffic than the 0-50 nm ring, so the
"79% of the near-port decline reappears offshore" figure needs a check against a measure that can
distinguish loitering from transit. The registered speed-bin cache (same GFW presence dataset,
registration OSF 5sc3v) supports exactly that.

WHAT IT DOES. Loads the hash-verified speed-bin cache, assigns the same frozen rings and the same
+/-12-month windows around 2021-11-16, and recomputes the mass balance three ways: all speeds,
low speed only (<2 kn), and the wider registered low-speed variant (<4 kn). Because all three run on
one product with identical windows, the comparison isolates the speed filter.

This is a READ-ONLY robustness analysis. It does not refire the registered queue-boundary gate, does
not alter any frozen decision, and writes only to outputs/.

Run: python src/analysis/spb_ring_speed_robustness.py
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data/external/gfw/spb_speed_bins"
OUT = ROOT / "outputs/spb_ring_speed_robustness.csv"
sys.path.insert(0, str(ROOT / "src" / "analysis"))
sys.path.insert(0, str(ROOT / "src" / "acquire"))

from h1_offshore_cargo import CENTER, SMOKE_EXCLUSION  # noqa: E402

REF = pd.Timestamp("2021-11-16")
RINGS = ["0-50nm", "50-150nm", "150-300nm"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_cells() -> pd.DataFrame:
    """Hash-verified load of the registered speed-bin cache, with frozen ring assignment."""
    manifest = pd.read_csv(CACHE / "manifest.csv")
    frames = []
    for row in manifest.to_dict("records"):
        path = CACHE / row["artifact"]
        if _sha256(path) != row["sha256"]:
            raise RuntimeError(f"registered GFW speed-bin hash mismatch: {path.name}")
        df = pd.read_parquet(path)
        df["speed_bin"] = row["speed_bin"]
        frames.append(df)
    cells = pd.concat(frames, ignore_index=True)
    if SMOKE_EXCLUSION in set(cells["date"]):
        cells = cells[cells["date"] != SMOKE_EXCLUSION]

    lat, lon = cells["lat"].to_numpy(), cells["lon"].to_numpy()
    dphi, dl = np.radians(CENTER[0] - lat), np.radians(CENTER[1] - lon)
    a = (np.sin(dphi / 2) ** 2
         + np.cos(np.radians(lat)) * np.cos(np.radians(CENTER[0])) * np.sin(dl / 2) ** 2)
    nm = 6371.0 * 2 * np.arcsin(np.sqrt(a)) / 1.852
    cells["ring"] = np.select([nm <= 50, nm <= 150, nm <= 300], RINGS, default="beyond")
    cells["date"] = pd.to_datetime(cells["date"])
    return cells[cells.ring.ne("beyond")]


def balance(cells: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    d = cells[mask]
    pre = (d.date >= REF - pd.DateOffset(months=12)) & (d.date < REF)
    post = (d.date >= REF) & (d.date < REF + pd.DateOffset(months=12))
    rec = {"variant": label}
    for ring in RINGS:
        r = d.ring == ring
        rec[f"pre_{ring}"] = d[r & pre].hours.sum() / 12.0     # monthly mean vessel-hours
        rec[f"post_{ring}"] = d[r & post].hours.sum() / 12.0
        rec[f"chg_{ring}"] = rec[f"post_{ring}"] - rec[f"pre_{ring}"]
    near = rec["chg_0-50nm"]
    rec["offshore_gain"] = rec["chg_50-150nm"] + rec["chg_150-300nm"]
    rec["offset_pct"] = rec["offshore_gain"] / abs(near) * 100
    rec["total_chg"] = near + rec["offshore_gain"]
    rec["total_pct"] = rec["total_chg"] / sum(rec[f"pre_{x}"] for x in RINGS) * 100
    return rec


def main() -> None:
    cells = load_cells()
    print(f"loaded {len(cells):,} hash-verified speed-binned cell-days; reference point {CENTER}")
    rows = [
        balance(cells, pd.Series(True, index=cells.index), "all_speeds"),
        balance(cells, cells.speed_bin.eq("<2"), "low_speed_lt2kn"),
        balance(cells, cells.speed_bin.isin(["<2", "2-4"]), "low_speed_lt4kn"),
    ]
    out = pd.DataFrame(rows)
    os.makedirs(OUT.parent, exist_ok=True)
    out.round(1).to_csv(OUT, index=False)

    for r in rows:
        print(f"  {r['variant']:18s} near {r['chg_0-50nm']:+10,.0f}  offshore {r['offshore_gain']:+9,.0f}  "
              f"offset {r['offset_pct']:5.1f}%  total {r['total_chg']:+9,.0f} ({r['total_pct']:+.1f}%)")

    allsp = rows[0]["offset_pct"]
    low = rows[1]["offset_pct"]
    # The point of the check: transit inflates the apparent offset, so the low-speed offset must be
    # LOWER. If it were higher, the transit story would be wrong and the paper would need rewriting.
    assert low < allsp, (
        f"low-speed offset ({low:.1f}%) is not below the all-speed offset ({allsp:.1f}%); "
        "the transit-contamination argument in Paper D does not hold on this product.")
    # And the qualitative claim must survive: a substantial but partial offshore reappearance.
    assert 20 < low < 80, f"low-speed offshore offset {low:.1f}% is outside the reportable range"
    assert rows[1]["total_chg"] < 0, "low-speed total presence did not decline"
    print(f"\nPASS: restricting to low-speed presence lowers the offshore offset "
          f"{allsp:.1f}% -> {low:.1f}%, consistent with transit inflating the all-speed figure;")
    print(f"      the qualitative result (substantial but PARTIAL offshore reappearance, with a real "
          f"net decline of {rows[1]['total_pct']:.1f}%) survives the filter.")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
