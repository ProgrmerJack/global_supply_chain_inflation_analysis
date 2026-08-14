# Index — four papers from one AIS programme

One terrestrial-AIS programme produced four papers with deliberately separate evidence. This file is the
single map of what each one claims, what it refuses to claim, and which code in this repository produces it.

The manuscripts and their claim ledgers are held outside this repository while the papers are under review;
the analysis code, the derived products and the decision records are here. Registrations are public at OSF
under parent protocol [htdqp](https://osf.io/htdqp/); data is at the Zenodo DOIs below.

## The four papers

| | Scientific object | Target | Evidence contract |
|---|---|---|---|
| **A** | Coupled congestion externalities at five port complexes, 2009–2025 | *Communications Earth & Environment* | ten assert-guarded scripts |
| **B** | National 15-complex AIS data descriptor, 2015–2025 | *Scientific Data* | hashed evidence per claim |
| **C** | Measurement validity and registered falsification | *TRIP* | hashed evidence per claim |
| **D** | San Pedro Bay bounded sustainability audit | *Ocean & Coastal Management* | hashed evidence per claim |

## A — coupled congestion externalities

A 2009–2025 vessel-level account of anchorage idling emissions and sectoral goods prices at five US port
complexes. One physical measure — vessel dwell time — quantifies two externalities at once.

**Supported:** the dwell census, anchorage activity ratios, mode composition. Absolute anchorage CO₂ is
*calibrated and banded* (CARB-calibrated central 54 t/ship-day, method band [24, 69]); the
relative-to-baseline ratio is the robust primary. The state-dependent goods-CPI response is
**associational, not causal** — an interaction effect surviving controls, an alternative shock, Bonferroni
correction and placebo ports.

**Refused:** the anchor/berth split is a geometric assignment, not validated operational state. The
November-2021 near-port decline is an **upper bound** on avoided emissions, never a lower bound — waiting
relocated offshore. The co-movement does not "concentrate" at LA/LB: only 2 of 4 pairwise contrasts survive
the difference test, so the supported phrasing is that LA/LB is the only complex reaching a *significant*
co-movement. Do not merge this five-port corpus with the national census.

**Code:** `src/emissions/{calibrated_emissions,era_seam_qc,per_teu}.py`,
`src/process_ais/{ais_qc,port_call_segmentation,mode_validation}.py`,
`src/models/{state_lp,price_robustness,inference,unit_root}.py`. Macro chain runs in order:
`src/index/build_macro_panel.py` → `src/index/build_dwell_index.py`.

## B — national AIS data descriptor

An auditable 2015–2025 daily census for 15 spatially assignable US port complexes: 463,113,836 retained
position reports, 23,392 MMSIs, 4,018 daily partitions, a 1,980-row complex-month activity panel, and a
NOAA-derived vessel-characteristics table.

**Supported:** dates, reports, MMSIs, complexes, schema, monthly activity products, static-field
missingness. Ship-days and 24-hour gap-defined call starts are **algorithmic** — reproducible but
definition-dependent.

**Refused:** berth, anchor, waiting, fuel use, emissions, concentration and delay are not validated truth.
The separately versioned five-port corpus is documented but never silently concatenated with this one.

**Code:** `src/process_ais/{build_national_panel,extract_port_observations,build_vessel_characteristics}.py`.
Spatial ontology: `config/geometry/port_areas_usace.geojson`, fixed by
`config/registries/port_area_assignment_coverage.csv`.

## C — measurement validity and falsification

A cross-design methods paper showing that internal reliability, construct validity, unit of analysis and
causal specificity are separate properties. It reports **four registered failures as results**.

**Supported:** split-half reliability 0.993 (Spearman–Brown 0.997) across 1,980 complex-months. Baltimore
B-G1 validates the physical obstruction measurement. The arrival gate is usable at complex level.

**Refused:** G1 is a failed proxy relationship, not proof that raw AIS is invalid. The San Pedro Bay
estimate supports a spatial description, not an identified queue-policy effect. B-G2 fails: a larger
response appears in negative-control ports. The 1.74% combined arrival agreement is produced by two
offsetting port errors and must **never** be cited as validation of port-resolved counts. A failed
falsification is not an "almost pass".

**Code:** `src/process_ais/g1_diagnostics.py`, `src/analysis/queue_boundary_reanalysis.py`,
`src/analysis/baltimore_infrastructure_shock.py`. Decisions: `results/development/G1_ais_fullcensus/`,
`results/confirmatory/{baltimore_shock,nature_recovery}/`.

## D — San Pedro Bay bounded sustainability audit

A boundary-first case study linking four layers without pretending they form a validated causal chain:
cargo-presence accounting, official five-sector emissions inventories, observed NO₂ falsification, and a
descriptive environmental-justice baseline.

**Supported:** between roughly two-fifths and four-fifths of the near-ring cargo-presence decline reappears
in the two offshore rings, the spread reflecting which presence product is used and whether transit is
filtered out; the full 0–300 nm total falls 3.2%. Official 2018–2024 CO₂e and local-pollutant totals move
differently across the complete five-sector boundary. Port-adjacent communities have a higher-burden
descriptive baseline.

**Refused:** no individual waiting, queue-policy causality, validated absolute AIS emissions, observed
port-attributable concentration, exposure or health effect, policy-attributable environmental justice,
incidence, optimisation or welfare claim. The withdrawn offshore CO₂ closure stays excluded. Public NO₂
designs identify neither the hypothesised benefit nor an informative bounded null.

**Code:** `src/analysis/{equity_baseline,h1_offshore_cargo,spb_ring_speed_robustness}.py`,
`src/emissions/spb_freight_boundary.py`. Decisions: `results/deep_case_SPB/`.

## Constraints that cross all four

**Three corpora, not three versions.** The five-port 2009–2025 census, the five-port mode census and the
national 15-complex census cover different port *areas*. They are not interchangeable and must not be
concatenated or reconciled as if one corrected another. Read `data/README.md` before using any of them.

**Failed gates are reported as failures.** `results/` holds the stop audits, the invalidated first
executions and the negative controls that killed a design, alongside what survived. Read the record for a
component before quoting it.

**Paths are load-bearing.** Freeze receipts hash exact bytes at exact paths; moving a file is a scientific
act, not a tidy-up. See the "Why the directory layout cannot be reorganised" section of `README.md`.

## Data

| Record | Version | Contents |
|---|---|---|
| [10.5281/zenodo.21653033](https://doi.org/10.5281/zenodo.21653033) | 1.0.0 | national 15-complex census — 20 files, 4,752,450,838 bytes, 11 annual archives 2015–2025 |
| [10.5281/zenodo.21820262](https://doi.org/10.5281/zenodo.21820262) | 2.0.0 | five-port corpus — 13 files, 2,869,894,549 bytes |

Cite the **version** DOIs above. Version 1.0.0 of the five-port record
(`10.5281/zenodo.21203605`) predates the recovery of four mode-census months and reproduces 17-year totals
about 2% lower; concept DOIs always resolve to the latest version and are not stable reproduction pins.
Both records re-verified against the Zenodo API on 2026-08-14.
