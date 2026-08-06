# Emissions — vessel-year-mode hoteling inventory for LA/LB (§9, H2)

**Modelled development result** under `prereg/deep_case_SPB_preregistration.md`. It is retained for audit and
conditional scenario work; the failed direct-measurement gate and unresolved semantic-state validation prevent
confirmatory state-resolved interpretation. Table: `emissions_vessel_year_mode.csv`;
code reuses `src/emissions/compute_emissions.py` (IMO 4th GHG 2020 Table 17 aux+boiler power × ECA fuel EFs,
main engine excluded — hoteling is the congestion-relevant term). Vessel type/size from
`vessel_characteristics.csv` joined to mode-resolved time (`monthly_mode_time.csv`, 37,166 LA/LB vessel-months).

## Finding — hoteling CO₂ tracks congestion, with a large but honest uncertainty band
LA/LB annual hoteling CO₂ (tonnes), point estimate + Monte-Carlo 95% band (propagating aux/boiler power ±20%,
load ±15%, EF/fuel ±10%, size/tier ±12%):

| year | CO₂ point | 95% band |
|---|---|---|
| 2019 | 227,696 | 116k – 375k |
| 2020 | 189,922 | 97k – 313k (COVID dip) |
| **2021** | **383,708** | **196k – 633k (congestion peak)** |
| 2022 | 310,224 | 158k – 511k |
| 2023 | 226,500 | 116k – 373k |
| 2024 | 274,224 | 140k – 452k |

The modelled 2021–2019 contrast is **+156,011 t CO₂ (+69%)**. The classifier-assigned anchor component rises
from about 72k to 126k t, but that component is not validated as pure operational waiting. The contrast is a
conditional activity-model output, not a validated climate cost or a policy-attributable effect.

## Uncertainty is real, not cosmetic
The ±~50% Monte-Carlo band reflects genuine unknowns (installed aux power, load factor, fuel/tier by vessel).
The old flat "54 t CO₂/ship-day" central value is **not** used; this is the vessel-year-mode replacement the
plan (§9) requires, with the distribution reported rather than a single number.

## What remains (NS-G3 gate)
- **The official 2024 numerical check is complete.** Against combined POLA/POLB stationary OGV tables, annual
  error is −19.3% (within ±20%) and berth-share error is −8.09 points (within ±10). This does **not** fire NS-G3:
  the official population includes cruise/all OGVs while the AIS population is cargo/tanker, official CO₂e is
  compared with model CO₂, and state attribution still depends on Pillar B. See
  `emissions_heldout_validation_result.md`.
- **State-resolved (anchor vs berth) attribution** inherits the Pillar-B block for its *state* precision,
  though the mode-time here comes from the validated LA/LB pilot classifier (not the failed national one).

## Decomposition of the +69% (review Priority 4) — activity-driven, EF-robust
Counterfactual (2021 activity with 2019 emission factors) splits the +156,012 t increase:
- **activity + composition (mode-hours +91%, fleet/state mix): +158,173 t (101%)**
- **emission-factor / fuel / tier: −2,161 t (−1%)** (2019 & 2021 both post-2015 ECA 0.1%-S — no fuel-regime jump)

Within this model, the **+69% is driven by the input activity increase (+91% mode-hours), not the year-specific
emission-factor term.** This is a decomposition conditional on unvalidated state assignments; it is not
empirical validation of either the mode-hours or the emissions. Composition (fleet/state mix) slightly
*dampens* the pure-hours effect (pure +91% hours would give +208k; modelled +156k).
A finer activity-vs-fleet-vs-state split needs more counterfactuals.

## Status (framing corrected per review)
**Emissions vessel-year-mode = MODELLED (not validated).** The relative +69% is stable to the tested
year-specific EF decomposition, but remains conditional on the activity/state model. The **absolute tonnage is
a modelled estimate with INCOMPLETE OFFSHORE
COVERAGE** (safer than "lower bound": it omits offshore + main-engine — non-negative — so it under-covers the
*system total*, but the near-port component itself has unquantified two-sided uncertainty from power/load/tier/
size assumptions, some of which could bias upward). The 2024 official comparison passes its numeric tolerances
but is not population-matched, so the formal gate remains blocked. **Keep the absolute total OUT of the
abstract** pending Pillar B and an exact cargo/tanker CO₂ comparator or a defensible official crosswalk.
