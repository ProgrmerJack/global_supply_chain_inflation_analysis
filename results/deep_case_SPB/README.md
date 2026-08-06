# San Pedro Bay deep-case result index

Read this file before citing an item in this directory. The reviewed scientific record is
`docs/deep_case_review_dossier.md`; the Route-A amendment is in
`prereg/amendments/2026-07-17_deep_case_freeze_integrity_and_route_a.md`.

| Claim/output | Status and permitted use |
|---|---|
| `NS_G1_direct_measurement_report.md` and companion CSV/JSON files | Registered one-shot decision under [OSF 5sc3v](https://osf.io/5sc3v/): GFW/BTS direction and movement-control specificity pass, timing fails; annual calls fail (0/4 within tolerance). Full NS-G1 does not pass, so the queue-policy spatial branch is blocked. |
| CARB At-Berth tanker route | Prospectively frozen independent 2025 intervention under public OSF registration [w6zsg](https://osf.io/w6zsg/). Its one-shot blind gate failed before effect estimation: berth-geometry coverage was 30.2% (required 80%) and the AIS 2024 call count differed from 634 official arrivals by 108.5% (allowed 20%). No treatment effect was opened; H4 is closed for this construct. |
| `H1_cargo_result.md` | Supported **cargo-presence** spatial accounting only; not offshore waiting and not a completed H1 waiting-survival pass. |
| `H1_result.md`, `H1_synthetic_control_result.md` | Superseded archival outputs; never cite. The synthetic-control generator is not retained. |
| `emissions_result.md` | Modelled vessel-year-mode estimate; relative activity contrast is modelled, absolute emissions are unvalidated. |
| `emissions_heldout_validation_result.md` | Official 2024 stationary-mode numerical tolerances pass, but formal NS-G3 remains blocked by population/quantity mismatch and Pillar B. |
| `emissions_component_validation_result.md` | Prospective OSF-registered 2018 like-population gate: source/coverage/class-count/unresolved-share checks pass, but stationary hours miss by +11.73%, berth share by −10.92 points, and official class-level emissions are non-identifiable. **NS-G3 fails; no absolute vessel emissions.** |
| `freight_boundary_result.md` | Reproducible official 2018–2024 five-sector SPB account (OGV, harbor craft, CHE, rail, HDV); 112/112 published totals reproduced. Descriptive system boundary only, not AIS validation or policy attribution. |
| `offshore_emissions_result.md` | Withdrawn circular/wrong-boundary material; never use as support for relocation or closure. |
| `aq_wind_oriented_result.md`, `aq_activity_interaction_result.md` | Honest observed-AQ nulls; no observed port-attributable concentration claim. |
| `inmap_exposure_result.md`, `H5_incremental_exposure_result.md` | Modelled screening, conditional on unvalidated emissions/state inputs; not observed validation. |
| `H5_equity_baseline_result.md` | Descriptive baseline disparity only. |
| `H6_labour_replication_result.md` | Independent congestion replication, not relocation replication. |
| Route-A-v2.2 computational silver | Five strict computational silver labels among eight pre-screened episodes; exploratory pipeline/QC evidence only. Not human labels, classifier validation, all-96 coverage, or a Pillar-B decision. See `prereg/pillar_b_route_a_v22_completion_receipt.json`. |

`emissions_vessel_year_mode.csv` remains a retained analysis output rather than the input to the official
comparison. `src/emissions/validate_spb_2024_inventory.py` independently reconstructs the 2024 model totals
from the retained mode-time and vessel-characteristics inputs, verifies the official PDF hashes, and extracts
the official mode tables. Its output is a rerunnable **numerical boundary audit**, not a formal NS-G3 decision.
The formal prospective replacement is registered at [OSF p5vqs](https://osf.io/p5vqs/) and implemented by the
hash-frozen development/holdout pair `src/emissions/spb_component_validation.py` and
`src/emissions/spb_component_holdout.py`. Its immutable one-shot artifacts are under
`results/confirmatory/spb_emissions_component_validation/`; the failed decision cannot be overridden by the
earlier 2024 audit.

The frozen GFW acquisition is catalogued at `data/external/gfw/spb_speed_bins/manifest.csv`: 35 verified
year-by-speed files, 1,310,199 daily-cell rows, all seven documented speed bins, and the disclosed smoke-test
date excluded. These files remain valid descriptive physical measurements even though their registered
aggregate operational-relevance gate failed.

The At-Berth source archive is `data/external/carb_atberth/`; the exact 2024 tanker-arrival extraction is
`data/processed/carb_atberth_2024_tanker_arrivals.csv`. `src/analysis/atberth_tanker_event.py` fails closed until
the external receipt is public, then writes the one-shot decision here. The immutable gate report is
`atberth_tanker_blind_gate.json` / `atberth_tanker_blind_gate.md`; it failed, so physical-panel construction and
H4 effect estimation remain prohibited. Its physical outcomes cannot establish visit-level shore-power/CAECS
use, compliance, emissions reduction, Pillar-B passage or individual waiting.
