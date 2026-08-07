# National port AIS census release

**Version:** 1.0.0  
**Coverage:** 2015-01-01 through 2025-12-31 UTC  
**Repository:** Zenodo, DOI `10.5281/zenodo.21653033`  
**License:** CC BY 4.0 for the derived release; NOAA source records are United States Government data.

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
- `code_and_protocols.zip`: the versioned extractor, panel builder, verification scripts, tests, requirements,
  manuscript evidence indexes and protocol documentation needed to audit the release.
- `national_ais_release_manifest.csv`: byte sizes and SHA-256 hashes for every deposited file.

## Interpretation boundary

Unique vessels, ship-days and gap-defined call starts are distinct activity products. They are not cargo
throughput or congestion. The release does not establish berth, anchor, waiting, delay, fuel use, emissions,
concentration, exposure, health or policy effects. Any downstream state or emissions product requires its own
validation. The separate five-port 2009--2025 dataset at DOI `10.5281/zenodo.21203605` is a historical
predecessor with a different spatial and processing contract and is not silently concatenated here.

## Reproduction

From the repository root:

```powershell
python scripts/verify_publication_packages.py --paper 1 --run-tests
python scripts/verify_publication_packages.py --paper 1 --deep
```

The first command verifies claim hashes, figures, references and focused tests. The second streams the complete
parquet corpus and verifies the registered report, MMSI, port and day totals.
