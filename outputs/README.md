# `outputs/` — catalog (current, canonical artifacts only)

Everything here is produced by the ten standing guard scripts and the figure renderers, and is referenced
by the manuscripts (`manuscript/*.tex`). Superseded artifacts were moved to `_REMOVE/` (see its README).

## Data
| File | Produced by | Used by |
|---|---|---|
| `emissions_carb_calibrated_LALB_anchor.csv` | `src/emissions/calibrated_emissions.py` | Papers A & B; Fig 2; the deposit (incl. per-row assumption/source columns) |
| `source_manifest.csv` | `src/process_ais/source_manifest.py` | NOAA raw-file provenance (4,378 files) |
| `monthly_dwell_segmented_sensitivity.csv` | `src/process_ais/dwell_segmentation_sensitivity.py` | per-port segmentation sensitivity |
| `la_dwell_segmented.csv` | `src/process_ais/port_call_segmentation.py` | segmentation robustness (SI S9) |
| `dwell_validation.json` | dwell census validation | QC record |
| `irf_results_dwell_{goods,services,headline}.csv` | dwell local projections | `inference.py::lp_bands` |

## Figures (`figures/`)
| File | Produced by | Manuscript figure |
|---|---|---|
| `paperA_fig1_census.png` | `src/emissions/descriptor_figures.py` | A Fig 1 (census + GSCPI concentration) |
| `paperA_fig3_emissions.png` | `descriptor_figures.py` | A Fig 2 (relative + banded absolute emissions) |
| `paperA_fig_map.png` | `src/process_ais/port_map.py` | A Fig 3 (LA/LB anchorage/berth map) |
| `paperA_fig_irf.png` | `src/models/state_lp.py` | A Fig 4 (state-dependent sectoral IRF) |
| `reform_event_study.png` | `src/emissions/reform_event_study.py` | A Extended Data Fig 1 (Nov-2021 reform DiD) |
| `descriptor_fig4_coverage.png` | `descriptor_figures.py` | B Fig 1 (coverage/data-structure matrix) |
| `descriptor_fig3_mode_composition.png` | `descriptor_figures.py` | B Fig 2 (mode composition) |
| `descriptor_fig5_era_seam.png` | `descriptor_figures.py` | B Fig 3 (era-seam continuity) |
| `descriptor_fig2_dwell_census.png` | `descriptor_figures.py` | (generated; not a manuscript figure — Paper B trimmed to 3) |

Regenerate everything: run the ten guard scripts (`calibrated_emissions.py`, `era_seam_qc.py`,
`per_teu.py`, `ais_qc.py`, `port_call_segmentation.py`, `mode_validation.py`, `state_lp.py`,
`price_robustness.py`, `inference.py`, `unit_root.py`) plus the figure renderers `descriptor_figures.py`,
`port_map.py`, `reform_event_study.py`, and the data-record generators `source_manifest.py` and
`dwell_segmentation_sensitivity.py`.
