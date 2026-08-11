# `data/` — catalog (canonical inputs only)

Everything here is either a canonical product read by the guard scripts or a raw public source.
Superseded per-year analyses, old index variants, and the synthetic "massive linked data" were moved to
`_REMOVE/data/` (inspect there, then delete — but read the warning at the end of this file first).

## Read this first: there are THREE AIS ping corpora and they are NOT copies of each other

The most common misreading of this repository is treating the three ping stores as duplicates or as
versions of one another. They are **three different spatial definitions of "a port"**, built by three
pipeline generations, with three incompatible column conventions, belonging to different papers.

| Corpus | Path | Size | Spatial scope | Columns | Papers |
|---|---|---|---|---|---|
| Five-port dwell census | `processed/ais_dwell_census_mode/port_pings/` | 2.1 GB | 5 complexes, wide port box | `MMSI, LAT, LON, SOG, VesselType, Port, mode` | A |
| National 15-complex census | `interim/national_pings/` | 5.8 GB | 15 complexes, narrow USACE port areas | `mmsi, lat, lon, sog, vessel_type, port_complex_id` | B |
| Coastal 0–300 nm census | `interim/nature_recovery/coastal_pings/` | 9.3 GB | national coastline, both coasts | as national + `length, width, draft, imo, status` | C, D |

**The scope difference is measurable and it matters.** San Pedro Bay, October 2021:

| Corpus | Pings | MMSIs | Latitude | Longitude |
|---|---|---|---|---|
| Five-port census (`LA_Long_Beach`) | 1,109,505 | 373 | 33.65–33.78 | −118.29 … −118.10 |
| National census (`san_pedro_bay`) | 619,588 | 350 | 33.71–33.78 | −118.28 … −118.18 |

The national box is strictly narrower and retains ~56% of the pings for the same complex-month. This is
the concrete origin of the Paper A / Paper C disagreement over unresolved-state share (2.7% against
60.85%): the studies do not disagree about a classifier, they measure different areas. Do not
"reconcile" those numbers by treating either corpus as a corrected version of the other.

**`interim/` is a historical name, not a status.** `DEPOSIT_PACKAGE.md` states that the canonical
national data "remain in `data/interim/national_pings/`", and `interim/nature_recovery/coastal_pings/`
is registered evidence for a frozen gate. Neither is scratch and neither may be cleared. Genuine
scratch (`duck_tmp/`, `duckdb_spill/`) was removed on 2026-08-05 and is now git-ignored.

## `data/processed/` — canonical census products
| Item | Size | What | Written by | Read by |
|---|---|---|---|---|
| `ais_dwell_census/` | 168 KB | **monthly dwell CSVs only** (pre-mode) | `build_dwell_census{,_fgdb}.py` (both default `--out-dir` here) | `src/index/build_dwell_index.py` |
| `ais_dwell_census_mode/` | 2.1 GB | 2015–2025 dwell + mode CSVs + `port_pings/` (134.5M pings) | `build_dwell_census.py --mode-output` | emissions, segmentation, mode guards; deposit |
| `ais_dwell_census_mode_2009_2014/` | 18 MB | 2009–2014 dwell + mode CSVs | `build_dwell_census_fgdb.py` | emissions, segmentation guards; deposit |
| `ais_dwell_census_mode_2009_2014_v2/` | 903 MB | 2009–2014 `port_pings_fgdb/` (75.0M pings) | `build_dwell_census_fgdb.py` | 5 guards + publication verifier; deposit |
| `analysis_dataset_dwell.csv` | 62 KB | US monthly panel: CPI/GSCPI/IndPro/oil + LA dwell | `src/index/build_dwell_index.py` | `state_lp.py`, `price_robustness.py`, `inference.py`, `unit_root.py`, `ais_qc.py`, `port_call_segmentation.py`; deposit |
| `analysis_dataset.csv` | 51 KB | macro panel before the dwell merge | `src/index/build_macro_panel.py` | `build_dwell_index.py` |
| `vessel_characteristics.csv` | 604 KB | NOAA-derived per-MMSI modal type and median dimensions | `build_vessel_characteristics.py` | national state/emissions/At-Berth pipelines |
| `carb_atberth_2024_tanker_arrivals.csv` | 32 KB | Type-matched 2024 POLA/POLB tanker-arrival comparator with table/page and source hashes | acquisition | `analysis/atberth_tanker_event.py` |

**`ais_dwell_census/` looks like dead weight and is not.** It is the most-referenced item in the data
tree and the only dwell input to the analysis panel. It once got staged into `_REMOVE/` for deletion
while live code still wrote and read it, which severed the Paper A macro chain. It holds only four
small CSVs because its pings live in the `_mode` sibling directory.

**The pre-mode and mode censuses disagree, by design.** `ais_dwell_census/monthly_dwell.csv` and
`ais_dwell_census_mode/monthly_dwell.csv` cover the same 660 port-months but differ materially
(`TotalObservations` by up to 144,401, `MedianDwellDays` by 1.20 days) because the mode census
re-derives dwell after mode-zone assignment. The 2009–2014 files differ only by floating-point noise
(< 1e-13). Any script comparing dwell numbers must state which census it read.

Removed 2026-08-05 as redundant — all unreferenced, and each `_v2` was byte-identical to its canonical
sibling: `monthly_mode_time_v2.csv`, `monthly_mode_time.v1_oldzones.csv`,
`monthly_mode_time_2009_2014.{pre_dedupe,v1_oldzones}.csv`, `monthly_dwell_2009_2014.v2.csv`, and ten
aria2/azure/fgdb run logs. All were tracked in git and remain recoverable from history.

## The Paper A macro chain — two stages, run in order

```
data/raw/{cpi_us,cpi_goods,cpi_services,indpro,oil_price}.csv    FRED monthly levels
data/raw/gscpi_raw.xlsx                                          NY Fed GSCPI
        |  src/index/build_macro_panel.py                        (stage 1)
        v
data/processed/analysis_dataset.csv
        |  src/index/build_dwell_index.py                        (stage 2)
        |     + processed/ais_dwell_census/monthly_dwell{,_2009_2014}.csv
        v
data/processed/analysis_dataset_dwell.csv
```

`gscpi_raw.xlsx` is a legacy OLE2 `.xls` despite its extension: it needs `engine="xlrd"`, and the sheet
is `"GSCPI Monthly Data"` (not `"History"`). A loader that cannot read it must **fail loudly** and must
never substitute a generated series.

## `data/raw/` — raw public source series (provenance)
Macro inputs to the chain above: `cpi_us.csv`, `cpi_goods.csv`, `cpi_services.csv`,
`ppi_us.csv` (US BLS), `indpro.csv`, `oil_price.csv` (Federal Reserve), `gscpi_raw.xlsx` (NY Fed GSCPI).
Plus the AIS download helpers `Download-AISData-{Enhanced,Historical}.ps1`.

## `data/external/`
- `la_monthly_teu.csv` — Port of LA monthly container TEU (read by `per_teu.py`; deposited).
- `macro_controls.csv` — FRED import-price, deep-sea-freight PPI, medical-care & shelter CPI (read by `price_robustness.py`; self-heals from FRED if absent; deposited).
- `pola_teu.csv` — the upstream Socrata TEU export it was derived from (provenance).
- `City-of-long-beach/` — eight exact City Public Records Center releases under `C030684-071526`: a pier outline, 2014–2024 POLB/POLA historical aerials and the Harbor District ownership map. `source_manifest.csv` fixes filenames, sizes, SHA-256 hashes and release provenance. The 2024 aerial is an Esri GeoPDF with embedded State Plane California V georeferencing; the package is geometry/history evidence, not operational validation.
- `g1_v2_geometry_sources/` — outcome-free, immutable copies of verified public terminal-map documentation plus per-file sidecar and aggregate SHA-256 provenance. `src/process_ais/g1_v2_geometry_sources.py` resumes only when those hashes match. This is preparation evidence, not a terminal-boundary layer and not comparator data. The released 2024 Long Beach GeoPDF is ingested through the existing authorized-file path; the SC Ports documents remain explicitly recorded as unavailable in `config/g1_v2_geometry_source_registry_draft.csv`.
- `spb_emissions_inventories/` — 15 immutable official documents: POLA and POLB annual air-emissions inventories for 2018–2024 plus joint methodology v5, each retained once with source URL, retrieval timestamp, byte count and SHA-256. `src/acquire/spb_emissions_inventories.py` verifies and resumes without re-downloading. The 2024 boundary audit is development evidence; the separately registered 2018 one-shot component decision is indexed in `results/deep_case_SPB/emissions_component_validation_result.md`.
- `ab617_wcwlb_metadata/` — South Coast AQMD/CARB WCWLB design archive: nine monitor locations, the
  CAMP-declared pollutant scope, CAMP/appendices, QAPP, and AQview community/inventory/date/count metadata.
  AQview verifies 35,085 hourly NO2 records in 2020–2024 without opening a concentration value.
- `ab617_wcwlb_observations/` — immutable official chart responses opened only after public OSF registration `j6utx`; 84 declared series with raw-response hashes. The endpoint returned only 16–23 July 2026 values, leaving zero observations in the frozen 2020–2024 window and failing feasibility before modelling.
- `nature_recovery_metadata/` — outcome-blind NASA TEMPO V03/V04 service definitions and user guide plus the
  CARB OGV2025 workbook landing page. No TEMPO pixel, concentration observation or workbook cell was opened.
- `aqs_hourly/aqs_hourly_no2_los_angeles_2023_2025.csv` — one hash-manifested EPA AirData retrieval of the
  complete 2023--2025 Los Angeles County hourly NO2 files, retaining POC/method/QA fields for the frozen
  system-level At-Berth design.
- `noaa_wind/noaa_hourly_wind_spb_2025_ghcnh_continuation.csv` — co-located USW00023129 GHCNh continuation
  after the legacy ISD archive ended in August 2025; observed ISD fields retain priority and GHCNh fills only
  missing components.
- `hms_smoke/` — immutable NOAA HMS annual 2023--2025 smoke-polygon bundles and SHA-256 manifest; medium/heavy
  monitor-hour intersections are the frozen primary wildfire exclusion.
- `carb_atberth/` — 31 immutable official CARB regulation/design/plan artifacts plus per-file and aggregate hashes. The archived dashboard shell excludes its embedded outcome payload; terminal plans are design evidence, not compliance observations.
- `policy_documents/labour_disruption_2014_2015/` — three immutable official chronology snapshots (GovInfo, ILWU/PMA and the archived White House), per-file sidecars and an aggregate manifest for the prospectively frozen 2014–2015 spatial replication. These are design inputs only; the protected GFW outcome was opened only after OSF `x96np` became public and approved.
- `gfw/spb_labour_speed_bins/` — the 28 hash-manifested 2012–2015 cargo-presence artifacts acquired after OSF `x96np` approval: four years by seven official speed bins, 836,736 rows and 2,190,553 reported presence-hours. The invalid first builder output is preserved separately; the registered correction at OSF `mbu46` fails its approach-specificity and fixed-placebo conditions.
- `product_port_metadata/` — 11 outcome-blind Census/BLS schema and classification artifacts plus SHA-256
  sidecars and a source manifest. It includes no port-HS values or CPI observations. The metadata screen found
  the direct competitor's deposited HS4-item bridge but failed on validated-shock and executable-novelty
  conditions, so product and price outcomes remain deliberately unacquired.

## `data/interim/national_pings/`

The complete 2015–2025 retained NOAA census: 4,018 daily parquet files plus an append-only ingestion ledger.
Earlier failed attempts remain in the ledger, but every expected 2017–2025 date has a later `ok` record and its
retained parquet. DuckDB-based builders stream this tree under a memory cap; no raw-terabyte re-download is
needed.

## `data/interim/pillar_b_or/`

Append-only operational-record contact artifacts for the separately registered Pillar-B-OR route: the 96-row
classifier-blind request packet, private request-ID mapping, hash manifest, and transmission ledger. Returned
operational records are not present until a holder supplies them and must remain separate from public request
artifacts.

## `data/interim/nature_recovery/`

Registration-guarded coastal AIS for the independent At-Berth recovery protocol. The retained tree is
`coastal_pings/year=YYYY/month=MM/`, produced once by the existing national downloader/parser using the frozen
outer rows of `config/carb_atberth_recovery_coastal_domains.geojson`. It is separate from and does not replace
`national_pings/`. Acquisition began after immutable OSF submission `jh3ea`; while contributor approval is
pending, the recovery guard permits only this coastal-ping tree and blocks every outcome/gate path. Its
append-only manifest and immutable daily parquet make interruption/resumption auditable.

## Regenerating from raw
The `port_pings*` parquet lets every derived product regenerate without re-downloading ~1 TB of raw
national AIS files. The census build pipeline is `src/process_ais/`.

## What must NOT be deleted

Items with **no live code reference are frequently still evidence**, bound by a hash. A reference count
of zero is not permission to delete:

- `processed/pillar_b_route_a_v21/`, `pillar_b_route_a_v22/` — bound by
  `prereg/pillar_b_route_a_v2{1,2}_freeze_receipt.json`
- `processed/national_ais_release_manifest.csv` — bound by the Zenodo deposit
- `*.manifest.json` siblings — retrieval provenance for the parquet beside them
- everything under `external/` — retrieval-hashed third-party source documents
- `interim/national_pings/`, `interim/nature_recovery/coastal_pings/` — canonical despite living
  under `interim/` (see the note at the top of this file)

Before deleting anything under `data/`, check it against `manuscript/<bundle>/claims.csv`
(`evidence_path` + `evidence_sha256`) and `prereg/*_freeze_receipt.json`. A deletion that breaks a
frozen receipt cannot be repaired by regenerating the file, because the receipt hashes the exact bytes.
