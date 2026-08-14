# Port congestion, environmental burdens and supply-chain outcomes

A programme of four papers built from terrestrial AIS, covering vessel congestion at US ports and its
air-emissions and supply-chain consequences. Author: Abduxoliq Ashuraliyev (sole author,
ORCID 0009-0003-5482-5526).

## What is in this repository

The analysis code, the derived products the papers cite, and the decision records under `results/`.

The manuscripts, the planning and review documents, and the `prereg/` registration bundle are **not**
published here while the papers are under review. Files in this repository refer to them by path — a result
record naming `prereg/deep_case_SPB_preregistration.md` states which protocol governs it. Those are
provenance pointers, not broken links: the registrations are public at OSF under parent protocol
[htdqp](https://osf.io/htdqp/), and the data is public at the Zenodo DOIs below.

## Start here

| I want to… | Go to |
|---|---|
| see what all four papers claim and refuse to claim | **`INDEX.md`** |
| know which dataset is which | `data/README.md` — **read the three-corpora warning first** |
| see what a registered gate decided, including the failures | `results/README.md` |
| re-derive Paper A's headline numbers | the ten guard scripts below |
| understand how a directory is pinned | the `README.md` in that directory |

## The four papers

| Paper | Subject | Target |
|---|---|---|
| A | Coupled congestion externalities at five port complexes, 2009–2025 | *Communications Earth & Environment* |
| B | National 15-complex AIS data descriptor, 2015–2025 | *Scientific Data* |
| C | Measurement validity and registered falsification | *TRIP* |
| D | San Pedro Bay bounded sustainability audit | *Ocean & Coastal Management* |

## Reproducing

```powershell
python -m pip install -r requirements.txt

# Paper A's ten guards: each re-derives its own headline numbers and exits non-zero on regression
python src/emissions/calibrated_emissions.py
python src/models/inference.py
# ...and the remaining eight listed below
```

`scripts/build_publication_figures.py`, `scripts/verify_publication_packages.py` and
`scripts/check_pinned_paths.py` are included, but they read the manuscript bundles and the `prereg/`
receipts and therefore cannot run against this repository alone.

Papers B, C and D bind each headline to a hashed evidence artifact in a claim ledger held with the
manuscripts. Paper A's contract is instead the ten standing guard scripts, which assert their own headline
numbers and fail loudly on regression. Nine run from this repository plus the Zenodo deposit;
`price_robustness.py` additionally retrieves four public FRED series when no cached copy is present:

| Script | Checks |
|---|---|
| `src/emissions/calibrated_emissions.py` | emissions intensity, band, 17-yr totals, social-cost band |
| `src/emissions/era_seam_qc.py` | FGDB→CSV era-boundary continuity |
| `src/emissions/per_teu.py` | per-TEU ratio |
| `src/process_ais/ais_qc.py` | AIS anomaly audit (MMSI, position spikes; dwell–GSCPI r invariant) |
| `src/process_ais/port_call_segmentation.py` | concentration survives port-call segmentation |
| `src/process_ais/mode_validation.py` | mode SOG-threshold + anchorage-buffer sensitivity |
| `src/models/state_lp.py` | state-dependent price interaction LP |
| `src/models/price_robustness.py` | controls, anchor-shock, placebos, Bonferroni |
| `src/models/inference.py` | concentration r, detrending, anchor-time cross-check, reform DiD |
| `src/models/unit_root.py` | ADF/KPSS stationarity |

Paper A's macro inputs are built in two ordered stages before those run:

```
src/index/build_macro_panel.py   ->  data/processed/analysis_dataset.csv
src/index/build_dwell_index.py   ->  data/processed/analysis_dataset_dwell.csv
```

## Repository layout

```
src/
  process_ais/ AIS download, extraction, dwell census, mode classification, zone building
  emissions/   CARB-calibrated emissions, per-TEU, era-seam QC, Paper A figures
  models/      local projections, inference, unit-root, robustness
  index/       the two-stage macro chain (build_macro_panel -> build_dwell_index)
  analysis/    deep-case and national analytical drivers
  acquire/     one-shot external-source acquisition with hash manifests
  governance/  confirmatory-access lock
scripts/       figure builder, publication verifier, protocol validator, deposit upload
config/        port/mode geometry, anchorages, emission factors, registries
data/          three AIS corpora + macro sources + external evidence (see data/README.md)
outputs/       analysis products (no manuscript figures — those live in each paper bundle)
results/       development, confirmatory and deep-case decision records
statements/    data and code availability statements
tests/         pytest suite
```

## Data availability

The five-port package is public at Zenodo DOI **10.5281/zenodo.21820262** (version 2.0.0). Cite that version
DOI, not v1.0.0 `10.5281/zenodo.21203605` — v1 predates the four-month mode-census recovery and reproduces
17-year totals ~2% lower. The 15-complex national census is a separate product published at DOI
**10.5281/zenodo.21936231** (v1.1.0, open access, latest version), which also carries the citable frozen
snapshot of this code. Its v1.0.0 `10.5281/zenodo.21653033` stays public with byte-identical data and
differs only in the record README and the code archive. Both records verified against the Zenodo API
on 2026-08-14.

Sources: NOAA Marine Cadastre AIS (public domain), NY Fed GSCPI, US BLS CPI, Federal Reserve IndPro and
oil, Port of Los Angeles TEU, CARB congestion inventory.

## Licence

Code in this repository is MIT (`LICENSE`). The data products at Zenodo are CC BY 4.0, not MIT; NOAA Marine
Cadastre source records are US Government data. Neither deposit carries the full pipeline — see
`statements/CODE_AVAILABILITY.md` for exactly what each one ships.

## Why the directory layout cannot be reorganised

Three mechanisms key on **exact paths**, so moving a file is a scientific act, not a tidy-up:

1. **`prereg/` freeze receipts** store a path beside a SHA-256, and several are externally timestamped or
   OSF-registered. 64 files in `results/`, 18 in `config/` and 9 in `docs/` are named this way.
2. **Claim ledgers** (`manuscript/<bundle>/claims.csv`) bind each headline to an `evidence_path` and
   hash — including `data/README.md` itself, which is evidence for Paper B claim D06.
3. **`src/governance/access.py`** keys a fail-closed confirmatory lock on the literal roots
   `data/interim`, `data/holdout` and `results/confirmatory`, matching by path ancestry. Renaming one of
   those directories raises nothing; it silently removes the protection.

`scripts/check_pinned_paths.py` verifies all 353 pins — 44 of them via a declared relocation whose hash is
re-verified, 1 prospective, plus 26 governance roots — and runs in the test suite. It needs the `prereg/`
receipts, so it runs in the full working tree rather than against this repository alone. Each of `results/`,
`outputs/`, `config/`, `data/` and `data/{interim,processed,external}/` has a README stating its tier and
what pins it. To change something registered, write a dated amendment in `prereg/amendments/` — never edit
a receipt.

## Scope discipline

The claim boundaries are deliberately narrow and several registered gates failed. Failed gates are reported
as failures, not softened — `results/` contains the stop audits, the invalidated first executions and the
negative controls that killed a design, alongside the results that survived. Read the record for a component
before quoting it.
