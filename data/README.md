# `data/` — catalog (canonical inputs only)

Everything here is either a canonical product read by the ten guard scripts or a raw public source.
Superseded per-year analyses, old index variants, and the synthetic "massive linked data" were moved to
`_REMOVE/data/` (inspect there, then delete).

## `data/processed/` — canonical census (deposited to Zenodo)
| Item | Size | What | Read by |
|---|---|---|---|
| `ais_dwell_census_mode/` | 2.2 GB | 2015–2025 dwell + mode CSVs + `port_pings/` (134.5M pings, parquet) | all guards; deposit |
| `ais_dwell_census_mode_2009_2014/` | 27 MB | 2009–2014 dwell + mode CSVs | guards; deposit |
| `ais_dwell_census_mode_2009_2014_v2/` | 912 MB | 2009–2014 `port_pings_fgdb/` (75.0M pings, parquet) | guards; deposit |
| `analysis_dataset_dwell.csv` | 62 KB | US monthly panel: CPI/GSCPI/IndPro/oil + LA dwell | `state_lp.py`, `price_robustness.py`, `inference.py`, `unit_root.py`; deposit |

## `data/raw/` — raw public source series (provenance)
Macro inputs to `analysis_dataset_dwell.csv`: `cpi_us.csv`, `cpi_goods.csv`, `cpi_services.csv`,
`ppi_us.csv` (US BLS), `indpro.csv`, `oil_price.csv` (Federal Reserve), `gscpi_raw.xlsx` (NY Fed GSCPI).
Plus the AIS download helpers `Download-AISData-{Enhanced,Historical}.ps1`.

## `data/external/`
- `la_monthly_teu.csv` — Port of LA monthly container TEU (read by `per_teu.py`; deposited).
- `macro_controls.csv` — FRED import-price, deep-sea-freight PPI, medical-care & shelter CPI (read by `price_robustness.py`; self-heals from FRED if absent; deposited).
- `pola_teu.csv` — the upstream Socrata TEU export it was derived from (provenance).

## Regenerating from raw
The `port_pings*` parquet lets every derived product regenerate without re-downloading ~1 TB of raw
national AIS files. The census build pipeline is `src/process_ais/`.
