# H1 hardening — far-vs-near ring difference-in-differences

> **SUPERSEDED — do not cite as current evidence.** This all-vessel synthetic-control framing predates the
> cargo-only absolute accounting. Its named generator is not retained in `src/analysis/`; preserve as audit
> history only, not a reproducible confirmatory result.

**Confirmatory** under `prereg/deep_case_SPB_preregistration.md` (synthetic-control / matched-sector design).
Table `H1_synthetic_control_DiD.csv`. The reform's "safe queuing area" is **far** (~150 nm+), so a clean test
is whether the **far ring (150–300 nm) rises relative to the near ring (0–50 nm)** at the reform but not at
placebos. The ratio cancels the common SoCal offshore level/trend (a within-SPB difference-in-differences).

## Result — the far-offshore jump is reform-specific
Change in log(far/near) presence ratio (pre vs post, 12 mo):

| window | Δ far/near | Δ far/mid |
|---|---|---|
| **EVENT 2021-11** | **+21%** | **+12%** |
| placebo 2019-11 | −17% | −21% |
| placebo 2020-11 | −8% | −1% |
| placebo 2022-11 | −11% | −14% |

At the reform the far ring rose **+21% relative to the near ring**; at **every** placebo date it *fell*
(−8% to −17%). The relocation toward the far queue is therefore **specific to the reform period**, net of the
common offshore trend — exactly the identifying pattern the placebo design was pre-registered to detect.

## Interpretation
This **strengthens H1**: the offshore relocation is not an artefact of a general rise in offshore traffic
(which would move near and far together and cancel in the ratio). The 2021 queue reform pushed waiting vessels
into the 150–300 nm safe-queuing band relative to the near approach — a clean, placebo-validated relocation
signal, complementing the levels result (near-port −18.7% / offshore +5.9%).

## Remaining refinement
Still all-vessel GFW presence; the cargo/slow-speed (loitering) refinement would confirm the shifted presence
is the container queue specifically. The DiD structure is robust to this unless non-cargo traffic
differentially shifted far-vs-near exactly at the reform (implausible — the fee/queue policy targeted the
container fleet). **H1 = SUPPORTED and hardened.**
