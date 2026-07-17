"""Acquire BTS Port Performance operational series (no auth): monthly container-vessel dwell times +
weekly ships-awaiting-berth. Feeds Pillar B (duration reference) and the offshore queue / mass-balance (NS-G2).

Run: python src/acquire/bts_ops.py
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/external/bts_ops"
_UA = {"User-Agent": "Mozilla/5.0"}
SERIES = {
    "monthly_container_vessel_dwell": "nfsh-p62e",   # Monthly Avg Container Vessel Dwell Times (top US ports)
    "weekly_ships_awaiting_berth": "iiy2-kmkn",      # Weekly # container ships awaiting berth (LA/LB, Savannah)
}


def _get(resource: str) -> pd.DataFrame:
    url = f"https://data.bts.gov/resource/{resource}.json?$limit=50000"
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=90) as r:
        return pd.DataFrame(json.load(r))


def acquire(out: Path = OUT) -> pd.DataFrame:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, rid in SERIES.items():
        df = _get(rid)
        dest = out / f"{name}.csv"
        df.to_csv(dest, index=False, lineterminator="\n")
        rows.append({"name": name, "resource": rid, "rows": len(df), "cols": ",".join(df.columns),
                     "source": f"BTS Port Performance (data.bts.gov {rid})",
                     "access_date": date.today().isoformat(),
                     "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
        print(f"  + {name}: {len(df)} rows -> {dest.name}")
    man = pd.DataFrame(rows)
    man.to_csv(out / "manifest.csv", index=False, lineterminator="\n")
    return man


if __name__ == "__main__":
    acquire()
