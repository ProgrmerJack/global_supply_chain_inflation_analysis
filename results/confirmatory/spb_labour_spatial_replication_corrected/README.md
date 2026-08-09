# 2014–2015 disruption spatial-mechanism replication — corrected decision

**Decision: component fail; NS-G7 not passed.**

The first execution under OSF `x96np` was invalid because string-indexed pivot series were aligned onto a
datetime-indexed frame, producing all-missing outcomes. Those files remain preserved with a hash-bound
invalidation receipt in `../spb_labour_spatial_replication/`.

The deterministic correction was frozen and publicly registered at
[OSF mbu46](https://osf.io/mbu46/) before any valid event coefficient was computed. The correction changes no
date, outcome, geometry, model, contrast or threshold. It fixes the index alignment, adds fail-closed integrity
checks and writes here.

All 28 year-by-speed artifacts are unique and hash-valid (836,736 rows; 2,190,553 reported presence-hours).
The 1,461-day panel has no missing outcome values. Near-port `<2`-knot cargo presence averaged 383.2 hours/day
in the fitting period and 776.5 during the disruption interval. The registered log-one-plus disruption
coefficient is 0.655 (95% CI 0.248–1.062), or 92.5% after transformation. It exceeds the movement control, and
the registered disruption-minus-recovery contrast is positive.

The component nevertheless fails two mandatory conditions:

- approach specificity fails: the west-minus-north/south disruption coefficient is −0.499
  (95% CI −0.803 to −0.195);
- the disruption coefficient (0.655) is not larger than the first fixed same-duration placebo (0.683).

The result therefore supports only a descriptive disruption-period increase in physical low-speed cargo
presence. It does not establish place-specific mechanism replication, individual waiting, relocation, labour
causality, emissions, exposure, health, or NS-G7 passage. The outcome-access disclosure in the correction
freeze also means this is a transparent registered pipeline correction, not a pristine first look.
