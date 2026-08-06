# Air-quality wind-oriented result (§11) — naive design FAILS its own sanity check (honest negative)

**Confirmatory** under `prereg/deep_case_SPB_preregistration.md`. Run once. Table: `aq_wind_oriented.csv`;
code `src/analysis/aq_wind_oriented.py`.

## Finding
Downwind-minus-upwind NO₂ across the 4 LA-county monitors ≤25 km of SPB is **−9.5 ppb** (downwind *lower* than
upwind) — the **opposite sign** of a port source. Per monitor: 4009 (8.6 km) −7.6, 4006 (9.4 km) −7.5,
4008 (15.5 km) −15.9, 1302 (20.2 km) −7.2.

## Why (a real confounder, not noise)
All 4 monitors sit **north of the port**, between it and the Los Angeles urban/freeway basin. When they are
"downwind of the port" the wind is from the **south = clean marine air**; when "upwind" it is from the
**north = polluted urban/freeway air**. So the naive downwind−upwind contrast measures the **land–sea / urban
air-mass gradient**, which swamps any port plume. The pre-registered distance-decay falsification is
uninformative here (the excess is negative throughout).

## Interpretation vs the frozen falsification battery
The design **fails its own sanity check** (a genuine source must show downwind ≥ upwind). This does not prove
the port has no NO₂ effect; it proves the **naive monitor-contrast cannot isolate it** at these north-side
monitors, because the port's marine-side plume is confounded with clean ocean air. This is exactly the failure
mode `plan.md §11` warned about (monitor selection + air-mass control are critical).

## What is needed (pre-registered refinements; not yet run)
1. **Activity interaction** — the frozen model's `β(PortActivity × Downwind)`: does downwind NO₂ rise *with port
   congestion* net of the air-mass level (absorbed by the downwind main effect + time FE)? This is the correct
   port-attributable estimand and remains to be estimated.
2. **Air-mass control** — restrict to marine-sector hours only, or match on wind sector, so downwind/upwind are
   compared within the same air mass.
3. **Ocean-side receptors** — monitors/receptors seaward of the port (few AQS sites there; may need modelled
   concentration, e.g. InMAP).
4. **PM2.5** and secondary nitrate as a slower-decaying tracer.

## Status (NS-G4 implication)
**Observed NO₂ port signal is NOT established by the naive wind contrast** — it is confounded by the urban
background, which is large relative to the port at these receptors. Per `plan.md` NS-G4, until a wind-oriented
response survives (via the activity interaction / air-mass control), **observed-health claims stay demoted**.
This is an honest negative that constrains the paper: the emissions→concentration link at SPB is not yet
demonstrated with observations.
