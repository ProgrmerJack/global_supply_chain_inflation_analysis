# Offshore emissions — EXPLORATORY ONLY; the earlier "mass-balance closure" is WITHDRAWN

**STATUS (revised 2026-07-17 after review): WITHDRAWN as a validation claim.** The earlier version of this file
claimed the CO₂ mass balance "closes (~72% offshore)". **That claim was invalid on two counts and is retracted:**

1. **Circular calibration.** The 20% offshore cargo fraction was **back-solved to match** the published total,
   then the resulting total was compared to that same target and called a match. That is fitting-to-target,
   **not** held-out validation. The "72% offshore" share is therefore not robust — it moves with the assumed
   fraction.
2. **System-boundary mismatch.** The benchmark (~2,001 t CO₂/day, Zhang et al. PMC11457959) is the peak excess
   of the **whole connected freight system** (ocean-going vessels **+ trucks + rail + cargo-handling
   equipment**), not an OGV-only offshore figure. Comparing an OGV near-port+offshore estimate to an all-source
   freight excess compares unlike quantities.

Additional invalid simplifications now flagged:
3. **GFW *does* support vessel-type + speed filtering** (per the API docs / review) — so the cargo fraction
   should be **measured with the cargo filter**, not assumed. My earlier "presence is all-vessel only"
   conclusion was wrong (group-by GEARTYPE is unsupported for the presence dataset, but the `filters` parameter
   is not — to be verified and used).
4. **Offshore loitering ≠ at-anchor hoteling.** A vessel 150–300 nm out may be drifting, slow-steaming,
   manoeuvring or transiting — its propulsion/aux/boiler profile is not the anchorage-intensity × presence-hours
   used here.

## What survives (only this)
> An exploratory calculation suggests omitted offshore vessel activity **could be substantial**, but the estimate
> is not independently validated and depends on unmeasured vessel-type and operating-mode assumptions.

The retracted claims ("mass balance closes", "held-out failure becomes confirmation", "72% of congestion CO₂
was offshore", "waiting and emissions relocated together") are **removed from all downstream use** (abstract,
figures, conclusions).

## Rebuild requirements (before any offshore-emissions claim)
- **cargo-filtered** GFW presence (measured fraction, no back-solve);
- **speed-bin-specific** operating modes (drift/slow-steam/manoeuvre/anchor), each with its own ME/aux/boiler load;
- **independently specified** emission factors;
- **like-for-like** boundary: OGV-only estimate vs an **OGV-only** published component/inventory;
- **identical dates**, absolute-vs-excess defined consistently;
- **uncertainty propagation**, and **no parameter fitted to the validation target**.

Only after that can an emissions-relocation hypothesis be *tested* (not assumed). Code retained
(`src/analysis/offshore_emissions.py`) but its output is exploratory scratch, not a result.
