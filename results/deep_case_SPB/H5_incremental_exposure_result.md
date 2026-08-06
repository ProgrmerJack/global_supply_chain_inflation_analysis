# H5 incremental exposure (§12) — MODELLED screening; regressive by income

**Confirmatory** under `prereg/deep_case_SPB_preregistration.md`. Table `H5_incremental_exposure.csv`. First-order
**screening dispersion** (NOT InMAP/CTM, NOT observed): incremental exposure ∝ (1/(d²+d₀²)) × downwind-fraction,
where downwind-fraction is the share of hours the real SPB wind (`noaa_wind`) blows from the port toward each
tract; tract centroids from the CES 5.0 shapefile; population weights + income/race from ACS.

## Finding
Modelled port NO₂/PM exposure, population-weighted, relative to the mean:

| income quintile | rel. exposure | | minority quintile | rel. exposure |
|---|---|---|---|---|
| Q1 (lowest) | **1.24** | | Q1 (least minority) | 0.87 |
| Q2 | 1.18 | | Q2 | 1.23 |
| Q3 | 1.02 | | Q3 | 0.97 |
| Q4 | 0.87 | | Q4 | 0.96 |
| Q5 (highest) | **0.69** | | Q5 (most minority) | 0.97 |

**Monotonic income gradient: lowest-income tracts get 1.78× the modelled port exposure of highest-income
tracts** — the plume is **regressive by income.** The minority gradient is **weak** (Q5/Q1 = 1.12×, non-monotonic)
in this modelled screening — income is the sharper axis here.

## Heavy caveats (this is a screen, not a result)
1. **Modelled, not observed.** The observed AQ link did NOT validate (naive null + interaction fails
   falsification), so this dispersion surface's **absolute magnitude is unvalidated**; only the **distributional
   shape** (regressive by income) is informative, and even that is model-dependent.
2. **Screening dispersion, not InMAP.** A proper reduced-complexity CTM (InMAP) would give a validated
   concentration field with secondary chemistry; this 1/d²×downwind proxy is a first-order stand-in.
3. **Port plume distribution, not the policy-attributable change.** This is who the port exposes, not how the
   2021 reform *redistributed* it — the incremental-policy estimand needs the reform's emission change × a
   validated surface.

## Status
**H5 income-regressivity = indicated (modelled screen), pending InMAP + a validated concentration surface.**
Combined with the H5 **baseline** result (port communities already more burdened + more Black), the
environmental-justice concern is supported at the baseline + modelled-screen level; a defensible *incremental*
exposure claim still needs the concentration model.
