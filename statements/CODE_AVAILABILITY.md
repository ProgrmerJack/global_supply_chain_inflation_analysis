# Code availability

All code for the AIS dwell/mode census, emissions calibration, and analysis is available at
<https://github.com/ProgrmerJack/global_supply_chain_inflation_analysis> and archived with the dataset at
Zenodo (DOI 10.5281/zenodo.21203605), under the MIT license. It runs on Python >= 3.10 with the
dependencies pinned in `requirements.txt`.

Ten standing, assert-guarded scripts fail loudly on regression and regenerate every headline from the
deposited data:

- **Six validate the dataset:** `src/emissions/calibrated_emissions.py`, `src/emissions/era_seam_qc.py`,
  `src/emissions/per_teu.py`, `src/process_ais/ais_qc.py`, `src/process_ais/port_call_segmentation.py`,
  `src/process_ais/mode_validation.py`.
- **Four validate the analysis:** `src/models/state_lp.py`, `src/models/price_robustness.py`,
  `src/models/inference.py`, `src/models/unit_root.py`.

Figures regenerate via `src/emissions/descriptor_figures.py`, `src/process_ais/port_map.py`, and
`src/emissions/reform_event_study.py`. The retained curated pings enable full local re-derivation without
re-downloading the ~1 TB of raw national AIS files.
