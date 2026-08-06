# H5 baseline equity characterization (§12) — port communities vs LA County

**Confirmatory** under `prereg/deep_case_SPB_preregistration.md`. Covers the pre-registered concepts
**baseline burden + susceptibility + distribution** (concept 2, *incremental policy-attributable exposure*,
requires the concentration model that the AQ result shows is not yet established — see caveat). ACS 5-yr 2022 +
CalEnviroScreen 5.0 (join on tract; ACS sentinels dropped).

Reproduction is now explicit: `src/analysis/equity_baseline.py` applies the frozen locality-name rule to the
archived ACS/CES inputs and writes `H5_equity_baseline.csv`. The published "median income" column is the
population-weighted mean of tract-level ACS median household income; CES and PM2.5 columns are tract means.

## Finding — SPB port-adjacent communities are disproportionately burdened
| Group | tracts | pop | median HH income | % Hispanic | % Black | CES burden pctile | PM2.5 |
|---|---|---|---|---|---|---|---|
| **Port communities** (Wilmington, San Pedro, Long Beach, Carson, Harbor, Terminal Is.) | 183 | 729,650 | **$84,278** | 47.9 | **11.9** | **69.4** | **10.9** |
| LA County (all) | 2,498 | 9,936,690 | $89,470 | 48.7 | 7.9 | 65.1 | 10.4 |

Port-adjacent communities have **higher pollution burden** (CalEnviroScreen 69th vs 65th percentile), a **~1.5×
higher Black population share** (11.9% vs 7.9%), higher **PM2.5** (10.9 vs 10.4 µg/m³), at somewhat **lower
income** ($84k vs $89k). This supports the environmental-justice framing: the SPB burden falls on communities
that are already more polluted and more heavily minority than the county as a whole.

## Honest scope (what this is / is NOT)
- **IS:** baseline pollution burden (CES), population susceptibility (income/race), and the distribution of who
  lives near the port — three of the four §12 concepts.
- **IS NOT:** the **incremental, policy-attributable** exposure change (concept 2 — how much of the burden is
  *caused by* port activity, and how a reform redistributes it). That needs a validated emissions→concentration
  surface (InMAP), which is gated on the AQ link (currently a confounded null) and Pillar-B state emissions.
- A conditional worker-location screen is now complete: on the same LA County tract universe, the point-source
  ISRM surface gives a workplace-weighted mean of 0.04567 µg/m³ versus 0.04603 µg/m³ resident-weighted (0.8%
  difference). LODES WAC counts jobs at workplaces, not worker residences or demographics, and the comparison
  remains modelled and total-port—not an incremental policy-attributable exposure result.

## Status
**H5 baseline = ESTABLISHED** (disproportionate baseline burden on more-minority, more-polluted port
communities). **H5 incremental (policy-attributable redistribution) = BLOCKED** on the concentration model +
Pillar B. The equity story has a solid baseline but cannot yet attribute exposure change to the intervention.
