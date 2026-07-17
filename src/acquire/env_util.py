"""Load .env credentials for the acquisition scripts (values never printed)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The 11 G1-v2 gateways -> primary county FIPS (state, county) for ACS / AQS scoping.
GATEWAY_COUNTIES = {
    "san_pedro_bay": [("06", "037")],                       # Los Angeles CA
    "new_york_new_jersey": [("34", "013"), ("34", "039"), ("36", "085")],  # Essex/Union NJ, Richmond NY
    "savannah_ga": [("13", "051")],                          # Chatham GA
    "norfolk_newport_news_va": [("51", "710"), ("51", "700"), ("51", "740")],  # Norfolk/Newport News/Portsmouth
    "houston_tx": [("48", "201")],                           # Harris TX
    "charleston_sc": [("45", "019")],                        # Charleston SC
    "baltimore_md": [("24", "510")],                         # Baltimore city MD
    "philadelphia_pa": [("42", "101")],                      # Philadelphia PA
    "jacksonville_fl": [("12", "031")],                      # Duval FL
    "miami_fl": [("12", "086")],                             # Miami-Dade FL
    "port_everglades_fl": [("12", "011")],                   # Broward FL
}


def load_env(path: str | Path | None = None) -> dict[str, str]:
    p = Path(path) if path else ROOT / ".env"
    env: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env
