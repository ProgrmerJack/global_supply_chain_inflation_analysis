# Code availability

All code for the AIS dwell/mode census, emissions calibration, and analysis is public at
<https://github.com/ProgrmerJack/global_supply_chain_inflation_analysis> under the MIT license (`LICENSE`),
which is the source of record. Neither deposit carries the full pipeline. The five-port deposit
(DOI 10.5281/zenodo.21820262, version 2.0.0) ships the data together with `emission_factors.py` only. The
national deposit (DOI 10.5281/zenodo.21653033) ships `code_and_protocols.zip`, a fixed snapshot of the
AIS-processing subtree — `src/process_ais`, both `scripts/` entry points, `requirements.txt`, the spatial
config and the Paper B claim table — but not `src/emissions`, `src/models` or `src/index`. That snapshot
predates the 2026-08-06 config reorganisation, so it carries the flat `config/` layout and is internally
consistent with it; repository paths differ.

Dependencies are pinned in `requirements.txt`; the released results were produced and re-verified with
CPython 3.14.

Ten standing, assert-guarded scripts fail loudly on regression and regenerate every headline. Nine read only
deposited files; `price_robustness.py` additionally uses four public FRED series (`IR`, `PCU483111483111`,
`CPIMEDSL`, `CUSR0000SAH1`), fetched keylessly if the cached copy is absent:

- **Six validate the dataset:** `src/emissions/calibrated_emissions.py`, `src/emissions/era_seam_qc.py`,
  `src/emissions/per_teu.py`, `src/process_ais/ais_qc.py`, `src/process_ais/port_call_segmentation.py`,
  `src/process_ais/mode_validation.py`.
- **Four validate the analysis:** `src/models/state_lp.py`, `src/models/price_robustness.py`,
  `src/models/inference.py`, `src/models/unit_root.py`.

Every figure regenerates through one entry point,
`python scripts/build_publication_figures.py --paper all`, which writes each display item into its
paper's bundle under `manuscript/` as a 300-dpi PNG and a vector PDF. For this paper it delegates to
`src/emissions/paper_a_figures.py`, `src/process_ais/port_map.py`, `src/models/state_lp.py` and
`src/emissions/reform_event_study.py`; the last two are guard scripts, so a figure that rebuilds is a
result that still reproduces. The retained curated pings enable full local re-derivation without
re-downloading the ~1 TB of raw national AIS files.
