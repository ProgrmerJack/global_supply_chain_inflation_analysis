# `outputs/` — catalog

## Why this exists, and is not part of `results/`

They are two tiers, and merging them would be harmful in both directions:

| | `outputs/` | `results/` |
|---|---|---|
| contents | regenerable analysis artifacts | decision records for registered gates |
| lifecycle | delete and rebuild freely | append-only; a gate fires once |
| protection | none | `results/confirmatory/` is access-gated |
| if deleted | re-run the guard script | a registration is destroyed |

`src/governance/access.py` names `results/confirmatory` in `PROTECTED_ROOTS` and refuses to open
anything beneath it without a verified unlock receipt. Folding `outputs/` into `results/` would put
freely-regenerable files inside an access-gated evidence tree; folding the other way would strip the
gate. Everything in this directory can be deleted and rebuilt by the command at the bottom of this file.
Nothing in `results/confirmatory/` can.

## Contents

Analysis products written by the guard scripts and the macro chain. **No manuscript figure lives here.**
Every display item for every paper is in its bundle at `manuscript/<bundle>/figures/` as a `paper{A,B,C,D}_*` PNG + vector-PDF
pair, built by `scripts/build_publication_figures.py`. (Until 2026-08-05 Paper A's figures were written
to `outputs/figures/` and included by relative path, which is why they escaped the publication verifier's
figure checks. That directory no longer exists.)

## Data products

| File | Written by | Used by |
|---|---|---|
| `emissions_carb_calibrated_LALB_anchor.csv` | `src/emissions/calibrated_emissions.py` | Paper A Fig 2; the deposit (carries per-row assumption/source columns) |
| `la_dwell_segmented.csv` | `src/process_ais/port_call_segmentation.py` | segmentation robustness (Paper A SI S9) |
| `monthly_dwell_segmented_sensitivity.csv` | `src/process_ais/dwell_segmentation_sensitivity.py` | per-port segmentation sensitivity |
| `irf_results_dwell_{goods,services,headline}.csv` | dwell local projections | `src/models/inference.py::lp_bands` |
| `dwell_validation.json` | `src/index/build_dwell_index.py` | concentration QC record (r vs GSCPI per dwell measure) |
| `source_manifest.csv` | `src/process_ais/source_manifest.py` | NOAA raw-file provenance (4,378 files) |
| `GATE_G6_cpi.md` | `src/analysis/final_gate_claim_audit.py` | frozen gate record |

`diagnostics/` holds non-manuscript plots (currently `dwell_vs_gscpi.png`, from the macro chain).
Nothing there is cited by a paper; it exists so a rebuild can be eyeballed.

## Regenerating

```powershell
# figures for every paper (Paper A's are byproducts of its assert-guarded analyses)
python scripts/build_publication_figures.py --paper all

# the data products above
python src/emissions/calibrated_emissions.py
python src/process_ais/port_call_segmentation.py
python src/process_ais/dwell_segmentation_sensitivity.py
python src/process_ais/source_manifest.py
```

The macro chain feeding the price and concentration guards is two stages and must run in order:
`src/index/build_macro_panel.py`, then `src/index/build_dwell_index.py`. See `data/README.md`.
