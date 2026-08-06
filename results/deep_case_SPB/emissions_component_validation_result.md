# Prospective 2018 freight-OGV component validation

## Decision

**NS-G3 failed.** The prospective design was registered publicly before protected-value access at
[OSF p5vqs](https://osf.io/p5vqs/). The 2019–2024 development executable was then frozen by hash, and the
combined POLA/POLB 2018 holdout was fired once at `2026-07-18T18:57:40.245056Z`.

| Frozen condition | Result | Decision |
| --- | ---: | --- |
| Source hashes, table uniqueness and class crosswalk | 16/16 published-total checks reproduced; no incomplete activity-observed freight row | Pass |
| Source-date coverage | 100% in every 2018 month | Pass |
| Total stationary freight-vessel hours | official 276,305.7 h; AIS 308,706.7 h; **+11.73%** error (maximum 10%) | Fail |
| Resolved berth share | official 72.50%; AIS 61.59%; **−10.92 percentage points** (maximum 10 points) | Fail |
| Stationary freight CO2e | not identifiable from the public tables | Fail |
| Represented official freight classes | 7 (minimum 5) | Pass |
| Class-level stationary-emissions ordering | not identifiable from the public tables | Fail |
| AIS unresolved stationary share | 0.59% (maximum 10%) | Pass |

The emissions conditions are non-identifiable because the reports publish port-wide shore-power and alternative-
control participation margins, not the class-by-control joint cells required by the registered official-method
reconstruction. The protocol expressly forbids inferring those cells by combining marginal tables.

## Verification and interpretation

The official activity calculation uses the frozen crosswalk: auto carrier, bulk carrier, containership, general
cargo, reefer, ro-ro and tanker; cruise, miscellaneous and ocean tugboat are excluded. Berth hours are arrivals
times the same-report mean berth-hotelling duration. Anchorage hours are same-report anchorage count times mean
anchorage duration. AIS uses the retained NMEA 70–89 census, SOG below 0.5 knots, the existing two-hour interval
cap, and all 366 source dates. Independent recomputation from the immutable output tables reproduces the values
above.

The close numerical misses do not authorize a threshold, class or denominator change. In particular, the
unusually long POLB ro-ro duration is explicitly reported as a home-based/ready-reserve feature in the official
inventory and cannot be removed after seeing the gate. The result validates neither absolute vessel emissions
nor anchor-versus-berth semantics and does not alter Pillar B.

## Permitted consequence

Absolute vessel-emissions claims are inadmissible. Transparent relative activity contrasts and explicitly
labelled emissions scenarios may remain, with parameter and boundary uncertainty. The earlier 2024 comparison
remains a development boundary audit only; it cannot override this prospective failure.

Immutable machine-readable artifacts are in
`results/confirmatory/spb_emissions_component_validation/`, whose completion receipt binds the gate, four
component tables and their SHA-256 hashes. The development and holdout-execution freezes are retained in
`prereg/spb_emissions_component_validation_development_freeze.json` and
`prereg/spb_emissions_component_validation_holdout_execution_freeze.json`.
