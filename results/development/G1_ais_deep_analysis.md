# G1 deep analysis — development evidence for designing G1-v2 (NOT a re-pass of G1-v1)

**Status:** DEVELOPMENT evidence, inspected after G1-v1 failed. It does **not** overturn the registered
G1-v1 failure and does **not** constitute a confirmatory pass. Its only role is to inform a preregistered
**G1-v2** protocol that must be frozen before any new comparator values are opened.
**Evidence window:** full 2015–2025 census (1,980 complex-months). **Date:** 2026-07-14.
**Inputs:** `national_activity_month.csv`, `capacity_weighted_activity.csv` (cargo-vessel capacity from
`vessel_characteristics.csv`, ~90% size coverage), `official_port_activity.csv` (Census `CNT_VAL_MO`, value),
`official_port_activity_cnt_wgt.csv` (Census `CNT_WGT_MO`, physical containerized weight).

## What the analysis eliminates (genuine progress)
- Sparse monthly sampling is not the cause (split-half reliability 0.99).
- Vessel counts were not the only physical measure — **capacity-weighting materially improves agreement**
  (normal-year 2017: count r≈0.20 → capacity r≈0.51).
- Seasonality does not explain the co-movement (deseasonalized ≈ raw).
- Under a capacity-vs-value specification, **all 15 complexes show positive monthly-anomaly correspondence**.
- A few complexes show strong monthly agreement.

This supports a narrower proposition only: *at some complexes, capacity-weighted AIS freight activity tracks
monthly containerized trade strongly enough to justify a preregistered operational-validation study.*

## Exact per-complex correlation — `deck_area` (capacity) vs Census value, operator `>= 0.80`

| complex | full r | full ≥.80 | deseasonalized r | deseas ≥.80 |
|---|---|---|---|---|
| mobile_al | 0.8862 | ✓ | 0.8969 | ✓ |
| new_york_new_jersey | 0.8541 | ✓ | 0.8584 | ✓ |
| norfolk_newport_news_va | 0.8465 | ✓ | 0.8487 | ✓ |
| philadelphia_pa | 0.8134 | ✓ | 0.8211 | ✓ |
| houston_tx | 0.8005 | ✓ | 0.7990 | — |
| baltimore_md | 0.7882 | — | 0.7972 | — |
| san_pedro_bay | 0.6670 | — | 0.6825 | — |
| savannah_ga | 0.6627 | — | 0.6489 | — |
| wilmington_nc | 0.5779 | — | 0.5894 | — |
| boston_ma | 0.5741 | — | 0.5827 | — |
| charleston_sc | 0.5645 | — | 0.5685 | — |
| new_orleans_la | 0.5309 | — | 0.5635 | — |
| miami_fl | 0.5026 | — | 0.5062 | — |
| port_everglades_fl | 0.4678 | — | 0.4825 | — |
| jacksonville_fl | 0.3606 | — | 0.3500 | — |

**FULL: 5/15 ≥ 0.80, median 0.6627. DESEASONALIZED: 4/15 ≥ 0.80, median 0.6489, 15/15 positive.**
(Correction: an earlier draft said "6/15 deseasonalized" — that rounded Houston 0.7990 and Baltimore 0.7972
up to 0.80; under the exact `>= 0.80` operator both fall below, so the deseasonalized count is 4.)

## Comparator comparison
Physical weight `CNT_WGT_MO` is **not** a better comparator than value: median 0.62 vs 0.65, and it goes
**negative** at New Orleans (−0.13) and Jacksonville (−0.23) — containerized weight depends on cargo density
and empty share, decoupling it from vessel capacity. Neither Census measure is the operationally-matched
comparator.

## Why the port pattern is NOT a clean "gateway vs small" split
The high group (Mobile, NY/NJ, Norfolk, Philadelphia, Houston) does **not** map cleanly onto "major container
gateways": **Mobile** (the strongest) is a mid-size diversified port, while **Savannah** and **San Pedro Bay**
— two of the largest US container gateways — sit at 0.66–0.68, and **Charleston** is weak. So the split is
NOT explained by container-gateway status. Candidate confounders that must be defined from **external** port
characteristics *before* being tested statistically: port-complex↔Census crosswalk accuracy, imports vs
exports, containerized vs bulk/tanker composition, loaded vs empty containers, vessel utilization,
arrival-to-handling lag, terminal coverage, transshipment, and the size of the USACE extraction polygon
(adjacent facilities inside a large polygon).

## Verdict
- **G1-v1 remains FAILED.** The literal gate (r ≥ 0.80 in ≥ 80% of ports) is not met even with the best AIS
  metric (capacity), a physical comparator (weight), the anomaly test (deseasonalized), or the full census —
  4–5 of 15 ports clear 0.80.
- **The registered motion-state failure (macro-F1 = 0.7289, below the 0.80 gate and 0.75 stop) remains
  binding and independent.** Nothing here revives anchorage, berth, offshore, state-specific emissions,
  air-quality-from-states, or policy-mechanism work.
- **These results justify BUILDING a preregistered G1-v2, not declaring one passed.** The observed
  median ≈ 0.65 cannot be used to set a 0.60 threshold now (that would be tailored to the result). Any
  G1-v2 rule and port population must be frozen from external criteria before new comparator data is opened.

## The only defensible next step
A matched-comparator registry + G1-v2 protocol, frozen before retrieval: gateway population from external
criteria; **primary comparator = official container-vessel calls** (matches reconstructed AIS calls directly);
TEU **secondary** (vessel capacity arriving ≠ TEU handled, because of utilization/empties/exports/transshipment/
timing); a multi-metric package (annual call coverage, deseasonalized anomaly, peak-month, event timing,
cross-port ranking, growth-rate bias, CIs); thresholds justified from downstream tolerance, not the observed
values; an untouched holdout; a timestamp; run once. This report is the design input to that protocol.
