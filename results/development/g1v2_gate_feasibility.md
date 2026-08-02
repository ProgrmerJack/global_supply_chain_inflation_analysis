# G1-v2 gate feasibility — DEVELOPMENT check on the acquired official comparators

**Status:** DEVELOPMENT feasibility (2026-07-16), run to decide whether further acquisition is worthwhile.
**NOT the frozen confirmatory one-shot** — holdout gateways (`charleston_sc`, `jacksonville_fl`) and years
(2024-25) are reported but excluded from the dev verdict; the one-shot remains unfired. Thresholds/population
unchanged.

## What was tested
The now-acquired **official** comparators (not the old Census import-value): monthly container TEU (BTS, 6
gateways, 2019-2023) and annual container-vessel calls (BTS 5rpz, 11 gateways, 2020-2023), vs the AIS
`national_activity_month.csv` (`cargo_port_calls`) and `capacity_weighted_activity.csv` (`deck_area_sum`).

## Pillar A — result: **currently FAILS** (both metrics)

**A5 metric 2 — monthly deseasonalized anomaly (threshold r ≥ 0.70), AIS vs official TEU:**
| gateway | calls·vs·TEU | deckarea·vs·TEU |
|---|---|---|
| houston_tx | 0.760 | **0.848** |
| norfolk_newport_news_va | 0.705 | 0.718 |
| new_york_new_jersey | 0.584 | 0.644 |
| san_pedro_bay | 0.538 | 0.593 |
| savannah_ga | 0.273 | 0.061 |

Dev (non-holdout) best-metric **median 0.644, 2/5 ≥ 0.70** — **no better than the old Census-value 0.65.**

**A5 metric 1 — annual call coverage (threshold ±20%), AIS calls / official calls:** dev **median ratio
1.89× (overcount)**, only **6% of gateway-years within ±20%**. Ranges by gateway:
- container-dominated (closest to 1): savannah 0.98-1.30, NY/NJ 1.17-1.50, charleston(holdout) 1.18-1.40, SPB 1.33-1.87
- diversified/non-container (far): **baltimore 3.3-5.4×** (auto/roro), houston 2.0-2.9× (energy/bulk),
  philadelphia 2.1-2.8×, miami/everglades/jacksonville ~2-2.9×

## Root cause (single, diagnosable)
Both failures share one cause: **the AIS metric counts ALL cargo vessels (AIS type 70-79) in the WHOLE USACE
port polygon, while the official comparator is CONTAINER vessels at CONTAINER terminals.** The overcount
tracks how diversified a port is (auto/roro/bulk/energy inflate AIS cargo calls). The frozen protocol A3
already specified "restricted to registered container terminals / restrict AIS to container terminals" — that
restriction has **not** been applied because per-gateway container-terminal geometry is not cleanly available
(OSM/Overpass is blocked from this environment; only whole-port USACE polygons + anchorages are local).

## Pillar B — result: **FAILS (already known + still blocked)**
Registered motion macro-F1 = 0.7289 (< 0.85 gate) is binding; berth/anchor resolved coverage was 30.4%
(anchor-only geometry). Needs the same container-terminal/berth geometry + two blinded annotators' labels.

## Verdict → what to do BEFORE more downstream acquisition
1. **G1-v2 does NOT pass as-is.** The blocker for BOTH pillars is the **container-terminal restriction**
   (geometry + container-vessel filtering), not the comparators (those are now correct and acquired).
2. **Highest-value next step is NOT more data — it is the container-terminal restriction**, then re-run this
   feasibility. If it brings annual coverage within ±20% and the anomaly ≥0.70 for the container-dominated
   gateways (savannah, NY/NJ, SPB, charleston), Pillar A is recoverable for that subset.
3. **The already-acquired offshore (GFW), air-quality (AQS), equity (ACS/LODES/CES) data is NOT wasted** even
   if national G1-v2 fails: it feeds the plan's explicit fallback (§5 "only San Pedro Bay passes" → deep LA/LB
   policy + observed-AQ + environmental-justice paper), which does not require the national state pipeline.
4. Container-terminal geometry is the shared unblocker; deriving/mapping it (or obtaining terminal polygons
   off this network) is the pivotal task. Only after Pillar A re-tests promising is it worth acquiring the
   remaining downstream (GFW SAR, OpenAQ, NOAA wind, CARB, engine-tier registry, 5-gateway monthly TEU).

## RECOVERY ATTEMPT (2026-07-16) — restrict AIS to container-class vessels by size (length ≥ 200 m)
Recomputed calls from the census (DuckDB, cargo type 70-79 joined to `vessel_characteristics.length_m`,
24 h-gap call segmentation), at length cuts 0 / 150 / 200 m.

**Annual call coverage → RECOVERED.** Ratio AIS/official container calls (avg 2020-23):
| gateway | L≥0 | L≥150 | **L≥200** |
|---|---|---|---|
| san_pedro_bay | 1.47 | 1.34 | **1.04 ✓** |
| new_york_new_jersey | 1.29 | 1.18 | **0.91 ✓** |
| savannah_ga | 1.21 | 1.14 | **0.86 ✓** |
| norfolk_newport_news_va | 1.39 | 1.31 | **1.03 ✓** |
| houston_tx | 2.18 | 1.77 | **0.98 ✓** |
| baltimore_md | 3.64 | 3.37 | 1.97 ✗ (auto/roro port; autos are also ~200 m) |
→ **5/6 within the frozen ±20% band** with a simple, defensible deep-sea-container size filter. The AIS annual
call reconstruction is a valid measurement.

**Monthly anomaly (r≥0.70) → NOT recovered** (L≥200): SPB 0.68 (up from 0.54), NY/NJ 0.59, Norfolk 0.61,
Houston 0.52 (down), **savannah −0.47** (goes negative), charleston(holdout) 0.20. Filtering does not fix it
and often worsens it. **Root cause is structural, not an AIS defect:** monthly vessel-*call counts* ≠ monthly
*TEU throughput* (a month can move more TEU with fewer, larger ships; TEU is booked at unload, not arrival).
The frozen A5 ties the monthly anomaly to a comparator (TEU) that genuinely differs from calls at monthly
resolution, and official monthly *calls* are published nowhere — so this component is effectively unmeetable.

## Revised verdict
- **AIS call measurement is annually VALID** (coverage recovered, 5/6 gateways) — national activity/policy-window
  claims at annual/low-frequency resolution are defensible; the deep LA/LB congestion signal already tracks GSCPI.
- **The monthly-anomaly-vs-TEU threshold is mis-specified** (calls-vs-TEU mismatch); it will fail the frozen
  one-shot for a reason that is not an AIS failure. Options for the user: (a) proceed on the validated annual
  coverage + deep case; (b) treat monthly-anomaly as diagnostic (comparator-mismatch caveat) in the run-once;
  (c) acquire monthly official *calls* (don't exist publicly) — not feasible.
- **Pillar B (state) remains the binding blocker** (motion F1 0.729; needs blinded labels + berth geometry).
- **Net for acquisition:** the AIS measurement is good enough that the acquired offshore/AQ/equity data is
  worth using — strongest for the LA/LB deep case, and usable for annual/policy national analyses.
