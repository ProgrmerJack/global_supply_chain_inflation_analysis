# `data/processed/` — derived products (not access-gated)

Deliberately **not** in `PROTECTED_ROOTS`: `src/governance/access.py` carries the comment that
`data/processed` "is deliberately NOT protected: after consolidation it holds both pilot (exploratory)
and national artifacts". Protected corpora live in `data/interim/`.

Full catalogue, including the four census directories, the two-stage Paper A macro chain, and what must
never be deleted: **`data/README.md`**.

## The census directories at a glance

| Directory | Holds | Read by |
|---|---|---|
| `ais_dwell_census/` | four small dwell CSVs (pre-mode) | `src/index/build_dwell_index.py` |
| `ais_dwell_census_mode/` | dwell + mode CSVs, `port_pings/` (134.5M) | emissions, segmentation, mode guards |
| `ais_dwell_census_mode_2009_2014/` | 2009–2014 dwell + mode CSVs | emissions, segmentation guards |
| `ais_dwell_census_mode_2009_2014_v2/` | 2009–2014 `port_pings_fgdb/` (75.0M) | 5 guards + the publication verifier |

`ais_dwell_census/` is small and looks disposable. It is the **most-referenced item in the data tree**
and the only dwell input to the analysis panel. It was once staged into `_REMOVE/` for deletion while
live code still wrote and read it, which severed the Paper A macro chain.

`_v2` in a directory name means a rebuilt product; `_v2` in a *file* name meant a scratch copy and those
were removed on 2026-08-05 after being shown byte-identical to their canonical siblings.

## Before deleting anything here

Run `python scripts/check_pinned_paths.py`. Several files are hashed evidence in a claim ledger or a
`prereg/` freeze receipt, and a reference count of zero is not permission to delete.
