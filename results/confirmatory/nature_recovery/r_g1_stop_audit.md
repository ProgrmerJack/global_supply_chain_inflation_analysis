# Nature-recovery R-G1 stop audit

## Decision

The corrected, registered R-G1 measurement gate **failed scientifically**. The Nature-recovery At-Berth
intervention route is closed at R-G1; R-G2 and all protected 2025 contrasts, AQ/TEMPO/CARB outcomes,
emissions, equity and manuscript edits remain unopened.

The binding condition is port-specific 2024 arrival agreement. AIS reconstructed 185 complete Port of Los
Angeles visits versus 143 official arrivals, an absolute fractional error of 29.37% against the frozen 25%
limit. All other conditions passed, including combined San Pedro Bay agreement.

| Frozen condition | Result | Decision |
|---|---:|---:|
| 2017–2025 source dates | 3,287/3,287; minimum monthly coverage 100% | pass |
| recovered-source regulatory-length observability | 6,739/6,966 = 96.74% | pass |
| complete 2024 candidate share | 623/630 = 98.89% | pass |
| combined 2024 arrivals | 623 AIS vs 634 official; 1.74% error | pass |
| Port of Long Beach | 438 vs 491; 10.79% error | pass |
| Port of Los Angeles | 185 vs 143; 29.37% error | **fail** |
| SPB complete visits in 2025 | 574 | pass |
| eligible donors | 13 | pass |

The immutable corrected receipt is `r_g1_call_measurement.json` (SHA-256
`acf73e2c9a0227d5d7cbb24562e3197008128bff3e38b48a2129eced26723058`).

## Technical corrections before the final decision

Three technical defects were separated from the scientific decision without changing any registered
threshold, population definition, source geometry or comparator:

1. An interrupted append left a valid immutable 2022-08-17 parquet without its successful manifest row. The
   artifact's date, source, schema and 255,859 rows were verified and the append-only ledger was reconciled;
   no source data were replaced or redownloaded.
2. Reprojecting sparse WGS84 polygon boundaries to EPSG:5070 falsely placed three of 8,557,725 Baltimore
   pings outside their frozen outer domain. All were inside the native geometry used at ingestion. Domain
   tests now remain in that native CRS; the geometry itself is unchanged.
3. The first written gate receipt incorrectly measured length from the older 133-day sparse vessel table,
   producing 57.21% observability, rather than from the recovered coastal source required by the protocol.
   The comparator-independent full-source audit measured 96.74%. The invalid receipt is preserved byte for
   byte as `r_g1_call_measurement.invalidated_length_source_2026-07-28.json` (SHA-256
   `68dc7a23cda4c1cb25b43a47ec419b18d2440f291a06cab99d40a7c3599431f2`).

The separately hashed correction receipts are
`prereg/nature_recovery_r_g1_technical_correction_2026-07-28.json` and
`prereg/nature_recovery_r_g1_length_source_correction_2026-07-28.json`.

## Deep failure verification

The final POLA miss is not a retrieval, coordinate, CRS, length-lineage or software-test failure:

* the POLA and POLB terminal coordinates and labels match the three hash-frozen source plans;
* the nearest cross-port terminal centers are 1.41 km apart, so the two 750 m buffers do not overlap;
* the exact registered first-contact and visit-completeness rules are used;
* an auxiliary read-only radius audit failed the POLA tolerance at every predeclared radius: 197 visits at
  250 m, 196 at 500 m and 185 at the primary 750 m, versus 143 official arrivals;
* in the auxiliary sequence diagnostic, 31 of 146 traceable LA-first groups later contacted a Long Beach
  terminal, and all 31 first touched the PBF buffer. This is consistent with pass-by/cross-port attribution
  inside a shared harbour; it is diagnostic only and cannot reassign the frozen primary calls;
* the full repository suite passes: **207 passed**, with only ten existing pyproj deprecation warnings.

The combined system count is accurate while the frozen within-complex port attribution is not. That is a
measurement-construct failure under the preregistered gate, not permission to pool ports, enlarge tolerance,
drop PBF, switch radius, use last contact, or continue to downstream outcomes.
