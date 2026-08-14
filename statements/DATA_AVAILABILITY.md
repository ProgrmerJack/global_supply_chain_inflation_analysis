# Data availability

The five-port vessel-level dwell/mode census, curated in-port AIS pings, CARB-calibrated LA/LB
idling-emissions layer, mode-zone polygons, macro-price panel and monthly TEU series are
public at Zenodo under CC BY 4.0: **DOI 10.5281/zenodo.21820262** (version 2.0.0, published 2026-08-06,
13 files, 2,869,894,549 bytes; file list and byte total re-verified against the Zenodo API on 2026-08-14).

Cite the **version** DOI above, not version 1.0.0 (`10.5281/zenodo.21203605`) and not the concept DOI
(`10.5281/zenodo.21203604`). Version 1.0.0 predates the recovery of four mode-census months and reproduces
17-year totals about 2% lower; the concept DOI always resolves to the latest version and is therefore not a
stable reproduction pin.

The FRED macro controls are **not** in the deposit, and an earlier revision of this statement wrongly said
they were. `src/models/price_robustness.py` uses four public FRED series — `IR`, `PCU483111483111`,
`CPIMEDSL` and `CUSR0000SAH1` — which it retrieves from FRED's keyless CSV endpoint when the cached copy at
`data/external/macro_controls.csv` is absent. No API key is needed, and naming the four series means the
control file can be rebuilt by hand.

The distinct 15-complex 2015--2025 national census described in Paper B is published at Zenodo DOI
**10.5281/zenodo.21653033** (version 1.0.0, published open access, 20 files, 4,752,450,838 bytes, of which
eleven are the annual AIS archives 2015--2025 with no year missing; confirmed the latest version via the
Zenodo API on 2026-08-14). Its concept DOI is `10.5281/zenodo.21653032`. It requires no reviewer
credentials.

Underlying public sources:

- NOAA Marine Cadastre AIS (US Coast Guard Nationwide AIS, US Government public domain),
  <https://marinecadastre.gov/ais/>
- NY Fed Global Supply Chain Pressure Index (GSCPI)
- US Bureau of Labor Statistics CPI and PPI
- Federal Reserve industrial-production and oil-price series (via FRED)
- Port of Los Angeles container (TEU) statistics
- California Air Resources Board, *Emissions Impact of Recent Congestion at the California Ports* (2021)
