# H1 result — offshore mass balance around the 2021-11-16 SPB queue reform

> **SUPERSEDED — do not cite as current evidence.** This all-vessel-presence analysis is preserved for audit
> only. Use `H1_cargo_result.md` and `results/deep_case_SPB/README.md`; neither establishes offshore *waiting*.

**Confirmatory** under `prereg/deep_case_SPB_preregistration.md` (frozen 2026-07-16). Run once. Table:
`H1_offshore_massbalance.csv`; code `src/analysis/h1_offshore_massbalance.py`.

## Finding
At the reform (pre = 12 mo before, post = 12 mo after 2021-11-16): **near-port waiting −18.7%** (LA/LB
anchor-hours) while **offshore presence +5.9%** across 0–300 nm, concentrated in the **far 150–300 nm ring
(+19.9%)** — the band matching the reform's ~150 nm "safe queuing area." At **placebo** dates near-port and
offshore move *together* (2019-11 both ≈ +9%; 2022-11 near −27% / offshore −7%); only at the reform do they
**diverge** (near-port down, far-offshore up). Relocation ratio R = 1 − (offshore%/near-port%) = **1.32**
(> 1 ⇒ offshore rose while near-port fell).

## Current verdict

This all-vessel analysis cannot fire the survival rule because its near-port and offshore quantities have
different populations and constructs. Its former relocation verdict is withdrawn. The registered daily
speed-bin replacement at [OSF 5sc3v](https://osf.io/5sc3v/) subsequently failed the required timing condition;
see `NS_G1_direct_measurement_report.md`. The table remains only as an auditable historical calculation.

## Honest caveats (bound the strength of the claim)
1. **All-vessel presence.** GFW presence is not cargo- or waiting-specific; the far-ring rise could include
   general traffic. The cargo-filter + slow-speed (loitering) refinement is the pre-registered sensitivity and
   would sharpen (or weaken) the estimate. Treat R = 1.32 as indicative, not final.
2. **Unit mismatch in R.** Near-port = anchor-hours (a specific waiting state); offshore = presence-hours (all
   vessels). R conflates them; a like-for-like waiting measure offshore (needs Pillar-B state offshore, which
   is blocked) would be cleaner. The *directional divergence vs placebos* is the robust part.
3. **Designs still to add (pre-registered):** synthetic control (donor = matched control sectors / other
   gateways) and randomization inference. Pre/post + placebo is done; these strengthen identification.
4. **State-resolved interpretation is BLOCKED** — offshore presence cannot be separated into individual
   operational waiting and transit, and the aggregate replacement did not pass its complete gate.

## Status
H1 all-vessel verdict = **WITHDRAWN/SUPERSEDED**. Descriptive values are retained; no operational relocation
claim survives this file.
