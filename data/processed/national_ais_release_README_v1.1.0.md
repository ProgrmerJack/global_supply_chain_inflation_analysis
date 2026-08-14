# National port AIS census release

**Version:** 1.1.0  
**Coverage:** 2015-01-01 through 2025-12-31 UTC  
**Repository:** Zenodo, DOI `10.5281/zenodo.21653033` (concept DOI `10.5281/zenodo.21653032`)  
**License:** CC BY 4.0 for the derived release; the code snapshot is MIT; NOAA source records are
United States Government data.

## What changed in 1.1.0

Data are **unchanged** from 1.0.0: the same 4,018 daily partitions, the same 463,113,836 retained
reports, the same 11 annual archives, byte-for-byte. Only the two documentation and code artifacts
changed:

1. `code_and_protocols.zip` now contains the **complete** analysis pipeline. The 1.0.0 snapshot held
   `src/process_ais` only, so no deposit carried `src/emissions`, `src/models` or `src/index` and the
   emissions and price analyses could not be rebuilt from any archive.
2. This README replaces one whose reproduction commands were wrong (`--paper 1`; the verifier accepts
   `A`, `B`, `C`, `D` or `all`) and which cited the superseded five-port DOI
   `10.5281/zenodo.21203605` instead of version 2.0.0.

If you already hold 1.0.0 you do not need to re-download the annual archives.

## Scope

This release contains 463,113,836 retained terrestrial-AIS position reports from 23,392 MMSIs assigned to 15
declared United States port-complex geometries. It covers all 4,018 UTC days in 2015--2025. It is a census of
records retained from the declared daily NOAA Marine Cadastre sources and frozen geometries, not a census of
every vessel or every United States port.

The 11 `national_port_ais_YYYY.zip` files preserve the Hive-style path `year=YYYY/month=MM/` and contain one
parquet file per UTC day. Extract any years needed and query the resulting parquet tree with DuckDB, Arrow,
Polars or another partition-aware engine. Loading the full corpus into one in-memory data frame is unnecessary.

## Ping schema

| Field | Type | Meaning |
|---|---|---|
| `mmsi` | integer | Reported Maritime Mobile Service Identity; transmitter identity is not independently resolved. |
| `timestamp` | UTC timestamp | Normalized source message time. |
| `lon`, `lat` | floating point | WGS84 longitude and latitude in decimal degrees. |
| `sog` | floating point | Source speed over ground in knots. |
| `cog` | floating point | Source course over ground in degrees. |
| `vessel_type` | floating point | Reported AIS vessel-type code; missing values remain missing. |
| `source_file` | text | NOAA daily source filename. |
| `port_complex_id` | text | Identifier of the frozen assigning port complex. |

## Companion files

- `ingestion_manifest.csv`: append-only acquisition attempts and completion receipts.
- `national_activity_month.csv`: 1,980 complex-month rows with unique vessels, reports, ship-days and
  24-hour gap-defined call starts.
- `vessel_characteristics.csv`: sparse same-source NOAA characteristics summarized per MMSI.
- `port_areas_usace.geojson`, `port_area_assignment_coverage.csv` and
  `national_state_zone_provenance.json`: spatial definitions, eligibility and provenance.
- `code_and_protocols.zip`: the complete versioned pipeline — `src/` (acquire, process_ais, emissions,
  models, index, analysis, governance), `scripts/`, `tests/`, `config/`, `requirements.txt`, `LICENSE`
  and the repository indexes and availability statements.
- `national_ais_release_manifest.csv`: byte sizes and SHA-256 hashes for every other deposited file.

## Interpretation boundary

Unique vessels, ship-days and gap-defined call starts are distinct activity products. They are not cargo
throughput or congestion. The release does not establish berth, anchor, waiting, delay, fuel use, emissions,
concentration, exposure, health or policy effects. Any downstream state or emissions product requires its own
validation. The separate five-port 2009--2025 dataset at DOI `10.5281/zenodo.21820262` (version 2.0.0) is a
predecessor with a different port universe, era and processing contract and is not silently concatenated
here. Cite that version DOI rather than its superseded 1.0.0 (`10.5281/zenodo.21203605`), which predates the
recovery of four mode-census months and reproduces 17-year totals about 2% lower.

## Reproduction

Every command below was run against this exact snapshot on 2026-08-14; the counts stated are what it
produced. Results in the accompanying Data Descriptor were produced with CPython 3.14.

**1. From the code archive alone.** Extract `code_and_protocols.zip` and run from its root:

```
pip install -r requirements.txt
python -m pytest -q tests/test_national_panel.py tests/test_ais_ingest.py \
    tests/test_vessel_characteristics.py tests/test_national_state_zones.py tests/test_g1.py
```

These are the focused tests behind this release's claims: **46 pass, 0 fail**, with no other files needed.

Running the whole suite (`python -m pytest -q`) gives **211 passed, 22 failed, 3 skipped**. The 22
failures are not defects: they assert against the preregistration bundle, the planning documents and the
manuscript sources, none of which is published while the papers are under review. The archive includes
`results/` — the decision records, including the failed gates — and `manuscript/paper_B_scidata/claims.csv`,
the evidence ledger for this deposit, but no manuscript text or figures.

**2. Claim-level evidence check.** `claims.csv` binds each claim to an evidence file and its SHA-256.
Three of the six (`D04`, `D05`, `D06`) resolve inside the archive; the other three (`D01`, `D02`, `D03`)
need files from this deposit, so download `ingestion_manifest.csv` to
`data/interim/national_pings/`, and `national_activity_month.csv` and `vessel_characteristics.csv` to
`data/processed/`. Then:

```python
import csv, hashlib, pathlib
for r in csv.DictReader(open("manuscript/paper_B_scidata/claims.csv", encoding="utf-8")):
    p = pathlib.Path(r["evidence_path"])
    got = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "MISSING"
    print(("ok " if got == r["evidence_sha256"] else "BAD"), r["claim_id"], r["evidence_path"])
```

**3. Full-corpus check.** Extract the annual archives so the parquet tree lands at
`data/interim/national_pings/year=YYYY/month=MM/`, then:

```
python scripts/verify_publication_packages.py --paper B --deep
```

This streams the complete corpus and verifies the registered totals
`(463113836 reports, 23392 MMSIs, 15 complexes, 4018 UTC days)`. Note that `--run-tests` and the static
check on the same script additionally read the manuscript bundle and therefore cannot run against this
archive alone; use the pytest command in step 1 instead.
