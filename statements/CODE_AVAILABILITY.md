# Code availability

All code for the AIS dwell/mode census, emissions calibration, and analysis is available at
<https://github.com/ProgrmerJack/global_supply_chain_inflation_analysis> and archived with the dataset at
the Zenodo dataset (DOI 10.5281/zenodo.21820262, version 2.0.0), under the MIT license. The versioned national
extractor/protocol snapshot is published in DOI 10.5281/zenodo.21653033. The code runs on Python >= 3.10 with the
dependencies pinned in `requirements.txt`.

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
