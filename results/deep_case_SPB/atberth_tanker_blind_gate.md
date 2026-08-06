# CARB At-Berth tanker blind-gate decision

**Registration:** [OSF w6zsg](https://osf.io/w6zsg/)  
**Gate:** FAIL  
**H4 effect estimation:** STOPPED

This report contains counts, missingness, source coverage and the frozen 2024
tanker-to-tanker comparator only. It contains no policy-effect estimate and does
not establish Pillar-B, compliance or emissions validity.

## Conditions

- all source dates ok: **PASS**
- every month at least 95pct: **PASS**
- spb at least 50 resolved calls each year: **PASS**
- at least five donors with 20 calls each year: **PASS**
- official 2024 tanker call error at most 20pct: **FAIL**
- berth geometry coverage at least 80pct: **FAIL**
- unresolved sog time at most 10pct: **PASS**

## Fixed inputs and denominators

- Source dates complete: 3,287/3,287; minimum monthly coverage 1.000.
- Eligible tanker MMSIs: 6,859; status disagreements excluded: 17.
- SPB resolved calls: 2024 = 1,315; 2025 = 1,121.
- Donors with at least 20 resolved calls in both years: 14 (baltimore_md, boston_ma, charleston_sc, houston_tx, jacksonville_fl, miami_fl, mobile_al, new_orleans_la, new_york_new_jersey, norfolk_newport_news_va, philadelphia_pa, port_everglades_fl, savannah_ga, wilmington_nc).
- Official 2024 SPB tanker arrivals: 634; AIS 24-hour-gap tanker calls: 1,322; absolute error 108.5%.
- Resolved SPB calls with a stationary berth-geometry interval: 735/2,436 (30.2%).
- Unresolved-SOG interval time: 39.5/98650.3 hours (0.0%).

The append-only ingestion ledger contains 11
earlier non-OK attempts; a later successful retry plus its retained parquet is
the final status used for source-day completeness. All attempts remain auditable.
