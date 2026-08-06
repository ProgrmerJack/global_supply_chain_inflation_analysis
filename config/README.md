# `config/` — frozen geometry, registries and method constants

**Layout (reorganised 2026-08-06,
`prereg/amendments/2026-08-06_config_prereg_subfoldering.md`):**

```
config/
  __init__.py, README.md, emission_factors.py   package/code — kept at root; emission_factors is
                                                imported as `config.emission_factors`
  geometry/    7 files   frozen spatial definitions (port areas, mode zones, anchorages, state zones)
  registries/ 12 files   comparator, crosswalk, coverage and terminal registries
  protocol/    7 files   gates, schemas, source declarations, provenance, method note
```

26 data files moved; all are byte-identical. The 18 that a registration names are declared in the
`RELOCATIONS` table of `scripts/check_pinned_paths.py`, which re-verifies each recorded SHA-256 at the
new path on every run — the receipts themselves were not rewritten. Nothing was unfrozen: an
undeclared move, or a declared move whose bytes drift, still fails the guard and the test suite.


**Do not reorganise this directory.** 19 of its 29 files are named inside `prereg/` receipts and
amendments; moving one invalidates a registration. `python scripts/check_pinned_paths.py` enforces this.

Despite the name, most of this is not settings — it is **frozen scientific input**: the spatial
definitions and comparator registries that were fixed before outcomes were opened. That is why it is
pinned and why it sits beside the data rather than inside `src/`.

## Spatial geometry

| File | Size | What | Used by |
|---|---|---|---|
| `national_state_zone_sources.geojson` | 38.6 MB | source geometry for the national state zones | `national_state_zones.py` |
| `national_state_zones.geojson` | 4.2 MB | derived national berth/anchor state zones | national state pipeline |
| `port_areas_usace.geojson` | 3.0 MB | USACE port areas — the **narrow** 15-complex boundary | national census, Paper B |
| `port_mode_zones_v2.geojson` | 0.7 MB | current five-port mode zones | `reclassify_modes.py`, mode guards |
| `port_mode_zones.geojson` | 0.7 MB | superseded v1 mode zones — kept for the era comparison | `mode_time_methodology.md` |
| `carb_atberth_recovery_coastal_domains.geojson` | 0.4 MB | frozen 20/40 km sea-to-port domains | at-berth recovery |
| `noaa_anchorages.geojson` | 0.2 MB | NOAA charted anchorage areas | mode classification, Paper A Fig 3 |

The USACE port areas and the five-port mode zones describe **different areas** — that is the origin of
the Paper A / Paper C unresolved-state disagreement. See the top of `data/README.md`.

## Registries and coverage records

`port_complex_crosswalk.csv`, `port_area_assignment_coverage.csv`, `port_area_sources.csv`,
`national_state_zone_{coverage.csv,provenance.json}`, `g1_operational_comparator_registry.csv`,
`g1v2_comparator_registry.csv`, the three `g1_v2_*_draft.csv` registries,
`carb_atberth_{recovery_assignment_coverage,spb_tanker_terminals}.csv`,
`data_acquisition_registry.csv` — each freezes a mapping or a coverage decision before outcomes were
seen. Several are hashed by a freeze receipt.

## Method and settings

| File | What |
|---|---|
| `emission_factors.py` | IMO Table 17 emission factors — code, but frozen method, cited by the deep-case preregistration |
| `emissions_method.md` | the emissions calculation method note |
| `gates.yml` | gate thresholds |
| `ports.schema.yml`, `data_sources.yml` | schema and source declarations |
| `config.yaml` | run settings (the only genuinely mutable file here) |
| `baltimore_infrastructure_shock.json` | frozen Baltimore study configuration |

## Rule

Treat everything except `config.yaml` as append-only. Changing a frozen geometry or registry after an
outcome has been seen is a protocol deviation and needs an amendment in `prereg/amendments/`.
