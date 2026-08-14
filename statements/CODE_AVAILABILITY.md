# Code availability

All code for the AIS dwell/mode census, emissions calibration, and analysis is public at
<https://github.com/ProgrmerJack/global_supply_chain_inflation_analysis> under the MIT license (`LICENSE`),
which is the development source. The citable frozen copy is `code_and_protocols.zip` in the national
deposit, **DOI 10.5281/zenodo.21936231 (version 1.1.0)**: 321 files covering the whole of `src/`
(acquire, process_ais, emissions, models, index, analysis, governance), `scripts/`, the `tests/` suite,
the `config/` tree, the decision records under `results/`, `requirements.txt`, `LICENSE` and the Paper B
claim table.

The five-port deposit (DOI 10.5281/zenodo.21820262, version 2.0.0) ships the data together with
`emission_factors.py` only, so reproducing Paper A takes two records: its data from 21820262 and the code
from 21936231.

Version 1.0.0 of the national deposit (`10.5281/zenodo.21653033`) carried a much smaller snapshot —
`src/process_ais` only, under the pre-2026-08-06 flat `config/` layout — and did not contain
`src/emissions`, `src/models` or `src/index`. Use 1.1.0 for code.

Dependencies are pinned in `requirements.txt`; the released results were produced and re-verified with
CPython 3.14. Extracting the 1.1.0 archive and running the focused test set behind the national release
(`tests/test_national_panel.py`, `test_ais_ingest.py`, `test_vessel_characteristics.py`,
`test_national_state_zones.py`, `test_g1.py`) gives 46 passed, 0 failed with no other files needed; the
full suite from the archive alone gives 211 passed, 22 failed, 3 skipped, the failures being assertions
against the unpublished preregistration bundle and manuscript sources.

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
