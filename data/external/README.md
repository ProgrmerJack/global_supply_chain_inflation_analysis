# `data/external/` — immutable third-party evidence

1.4 GB of retrieved source documents and datasets. **Nothing here is derived and nothing here may be
regenerated locally.** Each subdirectory carries retrieval provenance: source URL, retrieval timestamp,
byte count and SHA-256, usually in a `*_manifest.csv` or per-file sidecar. Acquisition scripts in
`src/acquire/` verify those hashes and resume without re-downloading.

Per-source descriptions — CARB/POLA/POLB inventories, EPA AQS, NOAA wind and HMS smoke, ACS/LODES,
CalEnviroScreen, AB617 monitoring, GFW, policy documents, product-port metadata — are in the
`data/external/` section of **`data/README.md`**, which is itself hashed evidence for a Paper B claim.

## Rules

- Never edit a retrieved file. If a source reissues data, retrieve it alongside and record both.
- Several of these directories are named in `prereg/` receipts and amendments; moving one invalidates a
  registration. `python scripts/check_pinned_paths.py` enforces this.
- Manifest sidecars (`*.manifest.json`, `*_manifest.csv`) look unreferenced by code but are the
  provenance record for the file beside them. Do not delete them.
