# InMAP ISRM exposure surface (§11/§12) — modelled screen, validation pending

> **MODELLED SCREEN ONLY — not observed validation and not closed.** The conclusion/status text below is
> superseded wherever it says “validated” or “closed”; use `H5_incremental_exposure_result.md` and the result
> index for the current conditional interpretation.

**Confirmatory** under `prereg/deep_case_SPB_preregistration.md`. Code `src/analysis/inmap_exposure.py`; tables
`inmap_receptor_pm25.csv`, `inmap_equity.csv`, and `inmap_resident_worker_exposure.csv`.

## How the blocker was closed (no binary, no download, no login)
The stated blocker — "needs the InMAP Go binary + a multi-GB source-receptor matrix installed" — is resolved by
reading the **public InMAP ISRM v1.2.1 directly from anonymous S3** (`s3://inmap-model/isrm_v1.2.1.zarr`) via
`zarr`, pulling only the **one source-cell row** for the port (~MB, not the full matrix). No Go, no full
download, anonymous access. `PM2.5(receptor) = Σ_precursor SR[layer0, port_source, :] × emission`, with the
2021 LA/LB hoteling emissions (NOx 2,766 t, SOx 234 t, primary PM 115 t).

## Result
- **Port-attributable PM2.5 peak = 2.20 µg/m³** near the port (physically plausible for SPB near-port OGV),
  decaying across 3,188 LA-basin receptors.
- **Income gradient (population-weighted, InMAP):**
  | income quintile | PM2.5 µg/m³ |
  |---|---|
  | Q1 (lowest) | **0.055** |
  | Q3 | 0.051 |
  | Q5 (highest) | **0.034** |
  → **1.61× regressive by income** (lowest-income tracts get 1.61× the port PM2.5 of highest-income).

## Why this matters
1. The InMAP income-regressivity screen (1.61×) is directionally consistent with the independent 1/d²×wind
   screen (1.78×). This is cross-model agreement on a **conditional spatial pattern**, not validation of the
   emissions input, exposure magnitude, or policy effect.
2. The observed wind-oriented design failed its falsification test. InMAP therefore supplies a mechanistic
   **modelled screen only**; it cannot replace observed validation or establish a reform-attributable change.

## Caveats
- Emissions input is a **modelled near-port hoteling estimate with incomplete offshore coverage**. The official
  2024 stationary-mode comparison passes the frozen numerical tolerances, but formal NS-G3 remains blocked by
  the official/model population and CO2e/CO2 mismatch and by Pillar B. The 1.61× gradient is less sensitive to
  a common emissions-scale factor, but remains conditional on the point-source geometry and receptor model.
- Modelled, not observed; the InMAP steady-state annual surface, not the reform-specific *change* (that needs
  the reform emission delta × ISRM — a straightforward extension now that access is closed).

## Units audit (review Priority 5) — passes, with one caveat
- **Source cell** centroid (33.734, −118.219) sits **at the port** (33.72, −118.20); 4 km cell. ✓
- **Emissions are annual** (t/yr → µg/s average rate: PM 3.64e6, NOx 8.76e7, SOx 7.42e6 µg/s) — **not** daily
  mistaken for annual. ✓
- Peak 2.20 µg/m³ decomposes: **primary PM 1.59 + nitrate(from NOx) 0.56 + sulfate(from SOx) 0.04**. Primary-PM
  dominated near-source, as expected. NH₃/VOC set to 0 (ships emit little; minor SOA omission).
- **CAVEAT — point-source placement OVERESTIMATES the peak.** All port emissions are in one 4 km cell; the real
  port footprint is ~10 km, so spreading the source would **lower** the 2.2 µg/m³ peak (toward ~1–1.5). Layer-0
  (surface) emission also slightly raises ground concentration vs a ~40 m stack. **Treat 2.2 µg/m³ as an upper
  estimate**, and keep it out of the abstract until the source geometry is refined.

## Status (revised)
**InMAP exposure MODELLING implemented (public ISRM, no login); formal emissions validation and observational
spatial validation PENDING** — not "closed/validated". The income-regressivity spatial pattern (1.61×) is a
conditional model output and agrees directionally with the 1/d² screen (1.78×); it does not validate the
emissions inventory or a policy effect. Next: distribute the source over the port footprint; reform-delta × ISRM for the
policy-attributable change; and (Priority 7) spatial validation against AB 617 / South Coast AQMD community
monitors (Wilmington–Carson–W. Long Beach), which are better sited than the AQS north-side monitors.

## Resident versus workplace weighting (conditional modelled surface)

Using the same LA County receptor/tract universe, ACS population gives a modelled mean of **0.04603 µg/m³**
(1,498 tracts; 6,142,728 residents) and LODES WAC workplace employment gives **0.04567 µg/m³** (1,497 tracts;
3,452,905 jobs). The 0.8% difference is negligible at this resolution: the current point-source ISRM surface
does **not** show a material resident-versus-workplace mean contrast. WAC identifies job locations, not worker
residences or worker demographics, and this remains a total-port modelled screen—not a policy-attributable
exposure estimate.
