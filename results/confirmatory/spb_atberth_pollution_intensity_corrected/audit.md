# Corrected At-Berth pollution-intensity audit

## Decision

**FAIL / INCONCLUSIVE.** The component does not support an observed 2025 At-Berth pollution benefit and does
not produce an informative bounded null. The distributional, TEMPO-rescue, emissions-benefit and integrated
counterfactual branches remain closed.

The result is a failure of source attribution and policy identification, not a coverage or acquisition
failure. Eight Los Angeles County NO2 monitors pass the frozen availability rule; the analysis retains 1,089
UTC dates and 142,107 site-hours after medium/heavy HMS smoke exclusion.

## Bug-versus-science audit

The first execution is invalid and preserved in the sibling
`spb_atberth_pollution_intensity/` directory. GHCNh missing direction `999` entered plume geometry, and the
future-activity diagnostic used the wrong wind hour. The deterministic corrections and invalid hashes are in
`prereg/amendments/2026-07-28_spb_atberth_first_execution_invalidation.md`. The corrected executable maps
directions outside 0--360 to missing and shifts activity before joining outcome-hour wind. No scientific
choice changed.

The corrected inputs then pass every source/measurement condition:

- NOAA station-record coverage: 98.54% (frozen minimum 85%);
- eligible NO2 monitors: 8 (minimum 3);
- pre/post concurrent site-hours before smoke exclusion: 95,178 / 47,205 (minimum 12,000 each);
- terminal-proximate tanker activity: present in all 158 study weeks;
- activity support: 84,947 terminal-proximate tanker stationary-hours, 600,575 cargo-control hours and
  146,866 offshore-tanker control hours under the primary construction.

The corrected scientific result nevertheless fails:

| Quantity | Result |
|---|---:|
| pre-policy tanker source response | -0.177 ppb per pre-period exposure SD |
| relative 2025 tanker-minus-cargo change | +0.583 ppb |
| seven-day block-bootstrap 95% CI | [-0.062, +1.203] ppb |
| date-clustered p | 0.0549 |
| implied post-policy tanker response | +0.0248 ppb |

The hypothesized policy benefit required a positive pre-policy source response and a negative relative 2025
change with an upper confidence bound below zero. Neither condition holds.

## Falsification and robustness record

- The 2024 pseudo-policy is null: -0.168 ppb, CI [-0.999, +0.708].
- The corrected future-activity effect is +0.579 ppb, CI [-0.105, +1.186]; it is not small enough under the
  frozen rule.
- The 180-degree rotated plume is null: +0.125 ppb, CI [-0.803, +0.879].
- The moving-tanker control is null: +0.181 ppb, CI [-0.059, +0.432].
- Every leave-one-monitor-out estimate remains positive (+0.316 to +1.145 ppb).
- Every activity construction remains positive: 0.75-km radius +0.540; one-hour cap +0.590; 2.5-km radius
  +0.712 ppb.
- Excluding all HMS smoke (+0.619) and retaining the full calendar (+0.583) preserve the positive sign.
- The predeclared <=30-km three-monitor sensitivity is null, not beneficial: +0.076 ppb, CI
  [-0.774, +0.972]; its pre-policy tanker response is weakly positive (+0.054 ppb).
- Post-result diagnostic lags of 0--4 hours do not reveal a stable hidden benefit. In the near-monitor subset,
  effects range from +0.076 to -0.282 ppb and every interval spans zero; in the full network, effects remain
  positive (+0.192 to +0.583 ppb) while the pre-policy tanker response remains negative.
- The residualized primary design matrix has condition number 15.95. The post tanker/cargo interactions are
  correlated (r=0.819), but the matrix is not numerically singular and the sign persists across the declared
  source constructions and monitor omissions.

These checks reject the explanations that the result arose from one monitor, the January 2025 fires, a single
terminal radius, the two-hour cap, an accidental 2024 discontinuity, an inverted plume, or a remaining
sentinel/time-alignment defect. They do not prove that the regulation had no effect; they show that this public
hourly design cannot identify a beneficial local NO2-intensity change.

## Programme consequence

The independent queue-boundary analysis supports partial physical redistribution but fails its causal gate.
This independent At-Berth analysis has complete support but fails the environmental/policy gate. Therefore
neither intervention supplies the required causal environmental foundation. Under the governing plan, no
policy-attributable resident/worker incidence, TEMPO rescue, policy optimizer or manuscript promotion is
admissible. The present repository is a rigorous negative/development record, not a Nature Sustainability-
ready paper.

