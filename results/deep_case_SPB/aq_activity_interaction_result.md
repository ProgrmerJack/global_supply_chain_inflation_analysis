# AQ activity-interaction (§11 refinement) — observed link NOT convincingly rescued

**Confirmatory** under `prereg/deep_case_SPB_preregistration.md`. Table `aq_activity_interaction.csv`; code
`src/analysis/aq_activity_interaction.py`. Tests whether the within-month downwind−upwind NO₂ **gap** (which
differences out the monthly marine/urban air-mass level that sank the naive contrast) **widens with port
congestion**, net of monitor + calendar-month fixed effects. Pre-registered falsification: **future** congestion
must not predict the current gap.

## Result
- n = 164 monitor-months; mean gap = **−8.18 ppb** (downwind still lower in level — marine air).
- **β(gap on current congestion) = +0.110 ppb per 1,000 anchor-hrs, r = +0.12** — positive but **weak**
  (explains ~1.5% of variance; ≈ +2.8 ppb at the 2021 peak of ~25k anchor-hrs, vs a −8 ppb baseline gap).
- **Falsification FAILS (effectively):** β(gap on *future* congestion, +3 mo) = **+0.085 (r = +0.10)** — future
  predicts the gap **77% as strongly** as current. For a clean contemporaneous port plume this should be ≈ 0.
  Congestion is highly autocorrelated month-to-month, so the weak positive is consistent with a shared slow
  trend, **not** a causal port effect.

## Honest verdict
The activity-interaction gives a **weak positive association that does not survive its own pre-registered
falsification.** The observed NO₂→port link at SPB is therefore **NOT established** — the naive null (confounded)
and this refinement agree: at the available north-side monitors the port's NO₂ contribution is not separable
from the urban background and shared trends.

## Consequence (NS-G4)
Per `plan.md` NS-G4, **observed-health claims stay demoted.** Remaining paths, in order of promise:
1. **InMAP** modelled concentration (open-source; gives an ocean-side/seaward exposure surface the sparse AQS
   monitors cannot) — the most likely route to a defensible incremental-exposure field.
2. **PM2.5 / secondary nitrate** (slower-decaying tracer) rather than primary NO₂.
3. High-frequency **event-window** design around individual large-ship berth events (vessel-specific timing)
   rather than monthly congestion.
4. If none survive: the paper reports emissions + offshore relocation + **baseline** equity, and explicitly
   does **not** claim an observed concentration/health effect — an honest boundary, not a failure to hide.
