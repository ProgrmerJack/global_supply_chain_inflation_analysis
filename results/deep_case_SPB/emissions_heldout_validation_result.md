# 2024 official emissions check (NS-G3) — numerical tolerance pass, formal gate blocked

The original comparison in this file used Zhang et al.'s **all-source freight-system excess** as if it were an
OGV hoteling inventory. That was a system-boundary error and remains withdrawn. The current check uses the
official 2024 Port of Los Angeles and Port of Long Beach OGV mode tables, downloaded once with byte hashes in
`data/external/spb_emissions_inventories/`. Code:
`src/emissions/validate_spb_2024_inventory.py`; machine-readable output:
`emissions_2024_official_mode_validation.csv`.

## Like-mode numerical comparison

Official stationary OGV CO₂e is taken from POLA Table 3.17 and POLB Table 2.7:

| source | berth CO₂e (t) | anchorage CO₂e (t) |
|---|---:|---:|
| POLA | 82,475 | 12,710 |
| POLB | 178,263 | 56,337 |
| **combined** | **260,738** | **69,047** |

The AIS model's 2024 stationary CO₂ is 188,363 t berth + 77,034 t anchor + 731 t unresolved hoteling =
**266,127 t**, versus **329,785 t** official CO₂e: **−19.3%**, inside the frozen ±20% numerical tolerance.
Among resolved stationary modes, the model's berth share is **70.97%** versus **79.06%** official, a
**−8.09 percentage-point** difference, inside the frozen ±10-point tolerance.

The previously reported 274,224 t is the model's aux+boiler total including transit and manoeuvring. It is not
used for this stationary-mode comparison.

## Decision

**Numerical tolerances pass; NS-G3 is not fired.** Two preregistered validity conditions remain unresolved:

1. the official tables cover all OGVs, including cruise vessels, whereas the AIS retained population is
   cargo/tanker (and 18.9% of 2024 vessel-month rows lack a matched type and are conservatively imputed); and
2. the official quantity is CO₂e while the model reports CO₂, and anchor-versus-berth attribution remains
   conditional on Pillar B.

Therefore this is encouraging external calibration evidence, not a formal held-out pass. Absolute emissions
remain modelled and stay out of the abstract. The earlier −72% “failure” cannot be cited: it tested the wrong
system boundary and does not diagnose offshore relocation.
