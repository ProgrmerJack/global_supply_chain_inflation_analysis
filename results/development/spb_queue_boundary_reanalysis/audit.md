# Independent scientific audit of the queue-boundary reanalysis

## Verdict

The component **fails** as a queue-reform causal design. The failure is not caused by acquisition corruption,
the year-end support bug, the initial aggregation-order bug or an unreported model exception.

## What is physically supported

- All 35 GFW hashes validate; 1,310,199 rows and 4,292,599 cargo vessel-hours are retained.
- Unsupported 31 December dates are excluded rather than imputed as zero. Re-running the old NS-G1 logic on
  corrected support leaves its failure unchanged.
- The west 125–175-nmi low-versus-movement triple difference is positive: 0.621 (95% HAC CI 0.054–1.187).
- Broad `<2`-knot activity declines by 652.75 mean daily vessel-hours within 0–50 nmi (eight-week block CI
  −907.23 to −339.99) and increases by 106.50 within 150–300 nmi (17.18–159.02).
- Total 0–300-nmi `<2` activity declines by 525.77 hours (−813.09 to −211.92). The far increase is therefore
  partial redistribution alongside a larger measured-system reduction, not mass-balance closure.
- The broad accounting signs survive 4-, 8- and 12-week bootstrap blocks; the `<4` boundary sensitivity is
  positive. These support a physical redistribution pattern.

## Why causal specificity fails

1. The co-primary weekly low-speed outer share has only 40 pre and 38 mature observations; the frozen minimum
   is 39 per phase. It is unestimable and the threshold is not relaxed.
2. Seven of 27 admissible dates have an absolute triple-difference coefficient at least as large as the true
   date, giving a two-sided rank p-value of 0.286.
3. The fixed 16 November 2022 placebo is larger than the true-date estimate: 0.926 (95% CI 0.519–1.333;
   Holm p=0.000025).
4. The 78-week estimate is 0.136 (−0.118–0.390), while the 26-week estimate is imprecise and negative. The
   positive result is not stable to the predeclared bandwidths.
5. The south-sector diagnostic is also strongly positive (1.236, 0.603–1.870). Because the rule also addressed
   north/south arrivals this is not a clean untreated placebo, but it prevents a uniquely west-boundary story.

The observed 52-week coefficient may reflect a genuine physical response, but seasonal/network changes and
later shipping adjustments can generate equal or larger discontinuities. A causal queue-reform claim is not
admissible. The result may be used only as transparent, post-outcome-known mechanistic/descriptive evidence.

## Execution integrity

The first call stopped before any output because nonlinear quantities were calculated before weekly
aggregation. The hash-recorded correction changed only aggregation order and added a regression test. The
second call exposed the genuine 38-week share shortfall but crashed instead of recording it; the second
hash-recorded correction changed only fail-closed reporting. Dates, bands, thresholds, models and decision
rules were not changed. The completed decision was mechanically converted from Python `NaN` tokens to strict
JSON `null` without altering a scientific value.

## Consequence for the programme

The 2021 intervention is demoted to physical accounting and mechanism context. It cannot supply the required
causal-policy pillar. The independent 2025 CARB At-Berth system-level observed-pollution design must therefore
carry identification; if that design fails, the current Nature Sustainability route stops.
