# H1 (corrected) — cargo-only, absolute vessel-hours: PARTIAL relocation

**Current descriptive spatial-presence analysis.** This supersedes the all-vessel percentage framing in
`H1_result.md` / `H1_synthetic_control_result.md`; those files are retained only as superseded archival output.
Code `src/analysis/h1_offshore_cargo.py`; table `H1_cargo_massbalance.csv`. GFW presence is **filtered to
cargo** (`vessel_type='cargo'`, ~18% of all-vessel — measured) and expressed as **absolute vessel-hours**
across all rings. It does not satisfy the preregistered *waiting* survival criterion.

## Result — the mass-balance table (monthly mean, pre vs post 2021-11 reform)
| ring | pre (vhr/mo) | post | Δ absolute | Δ % |
|---|---|---|---|---|
| 0–50 nm | 49,265 | 38,242 | **−11,023** | −22.4% |
| 50–150 nm | 9,621 | 11,490 | +1,868 | +19.4% |
| 150–300 nm | 13,944 | 20,798 | **+6,855** | +49.2% |
| **total 0–300 nm** | 72,830 | 70,530 | **−2,300** | **−3.2%** |

**Near-port cargo presence fell −11,023 vhr/mo; the mid+far rings rose +8,723 (≈ 79% of the near-port loss);
total 0–300 nm fell −2,300 (−3.2%).** The far ring (150–300 nm, the "safe-queue" band) rose most (+49%).

### Explicit replacement accounting (resolves the 62% vs 79%)
| offset of the −11,023 near-port loss | vhr/mo | % of near-port loss |
|---|---|---|
| 150–300 nm (far ring) alone | +6,855 | **62%** |
| 50–150 nm (mid ring) | +1,868 | 17% |
| **all offshore rings (50–300 nm)** | **+8,723** | **79%** |
| genuine 0–300 nm reduction (residual) | −2,300 | 21% |
Far-ring-alone replaces **62%**; **all offshore rings together replace 79%**; the two are not interchangeable and
both are now stated. (These are cargo *presence* vhr, not waiting; the 0–50 nm ring is the near-port zone — I do
not have a finer port-vs-0–50 split from GFW.)

## What the correction changed (and why the reviewer was right)
- The earlier **all-vessel %** version reported "total offshore +5.9%", implying offshore *more than* offset the
  near-port fall. **That was an artifact** of (a) all-vessel presence (fishing/other diluting cargo) and (b)
  percentages on unequal baselines. With **cargo-only absolutes, total 0–300 nm slightly FELL (−3.2%).**
- **Defensible claim now:** the reform coincided with a near-port cargo-presence reduction, **~79% of which
  reappeared as increased mid/far-offshore cargo presence (partial relocation); ~21% was a genuine 0–300 nm
  reduction.** NOT "the reform increased total offshore waiting"; NOT "pure elimination".

## Placebo hardening (survives cargo-only)
Δlog(far/near) presence ratio: **EVENT 2021-11 = +0.652**; placebos 2019-11 −0.044, 2020-11 −0.728, 2022-11
+0.178. The far-vs-near shift is strongest and cleanest at the reform → the relocation is reform-specific, net
of common offshore trend.

## Throughput sensitivity (post-review descriptive check)

The same frozen 12-month pre/post contrast was divided by monthly official San Pedro Bay container throughput
(`data/external/g1v2_official/san_pedro_bay__container_teu_total.csv`). This is a sensitivity, not a new
confirmatory estimand: throughput can itself respond to congestion.

| ring | pre vhr / million TEU | post | Δ | Δ % |
|---|---:|---:|---:|---:|
| 0–50 nm | 29,142 | 23,545 | −5,597 | −19.2% |
| 50–150 nm | 5,673 | 7,076 | +1,403 | +24.7% |
| 150–300 nm | 8,223 | 12,645 | +4,422 | +53.8% |
| **total 0–300 nm** | **43,038** | **43,266** | **+228** | **+0.5%** |

Official throughput fell 3.4% between the two windows. Normalizing by it leaves the spatial result intact:
near-port presence per TEU fell, both offshore bands rose, and total 0–300 nm presence per TEU was essentially
flat (+0.5%). The machine-readable table is `H1_cargo_throughput_sensitivity.csv`.

## Caveats the reviewer required (kept explicit)
1. **Presence ≠ waiting.** The cached H1 product was not speed-filtered, although the GFW API supports
   categorical speed filters. This result therefore counts cargo *presence* (transiting + low-speed activity),
   especially inflating 0–50 nm. A separately frozen speed-bin analysis can isolate low-speed presence, but it
   still cannot identify every low-speed hour as individual operational waiting. So "relocation of *waiting*"
   is not established here — only relocation of cargo *presence*.
2. The throughput sensitivity is complete, but it is descriptive because throughput is potentially endogenous.
   The cached GFW product is ring-aggregated, so an approach-corridor restriction and a defensible synthetic
   control with uncertainty intervals still require a separately fixed spatial donor artifact; they are not
   inferred from these ring totals.
3. Near-port "waiting" (anchor-hours, terrestrial census) is a separate, more-specific measure; the ring table
   uses one consistent GFW cargo-presence measure to avoid unit mismatch.

## Status
**Supported evidence: partial relocation of cargo presence** (~79% of the near-port decline reappears offshore),
reform-specific by placebo. **H1's stronger waiting-relocation claim remains unconfirmed** because this cached
panel is not speed-filtered and low-speed presence would still not equal individual waiting. The former
“waiting relocated / total offshore rose” claim is retracted.
