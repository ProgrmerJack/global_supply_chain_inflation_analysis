# G1-v2 run-once readiness (status of plan.md steps 1–3)

**Date:** 2026-07-15. This tracks the three steps in `docs/plan.md §20` (freeze → acquire records → run once)
and the frozen `prereg/G1v2_operational_validation_protocol.md`. **No G1-v2 pass/fail has been computed** —
the one-shot comparison is deliberately held until the primary comparators are in hand (see Step 2).

## Step 1 — FREEZE ✅ done
- Protocol `prereg/G1v2_operational_validation_protocol.md` → **FROZEN 2026-07-15**.
- Frozen A5 (activity) thresholds = `plan.md §5.3`: annual call coverage ±20%; deseasonalized monthly anomaly
  **r ≥ 0.70** vs the primary comparator (official container-vessel calls); event timing ±1 month; population
  pass = anomaly positive in ≥90% AND ≥6/11 gateways call-validated. TEU is secondary/confirmatory only.
  0.70 is **above** the observed development median (0.65) — not tailored to sit above the failure.
- Frozen holdout: temporal 2024–2025; gateway `charleston_sc` + `jacksonville_fl` reserved.
- Frozen Pillar-B (§5.3): episode macro-F1 ≥0.85 & CI-low ≥0.80; berth/anchor F1 ≥0.85 & resolved ≥90%;
  anchorage & berth duration signed bias within ±10%.
- Tamper-evident freeze receipt: `prereg/G1v2_freeze_receipt.json` (SHA-256 of protocol + registry + design
  input). Recommended git tag on commit: `g1v2-frozen`.

## Step 2 — RUN-ONCE INGEST: official monthly TEU (6 gateways) + annual calls (11/11) ingested via federal APIs ⚙️ (one-shot still NOT fired)
`teu_throughput.py --coverage` → **6/14 monthly-TEU** series present (was 0); **`g1v2_official_annual/` →
11/11 gateways** annual container-vessel calls (the primary comparator). Run: `python
src/process_ais/ingest_bts_official.py`.

**The API (answer to "is there an API?"):** the **BTS Port Performance Freight Statistics Program** on
`data.bts.gov` — a **Socrata SODA API** (official US DOT, machine-readable JSON/CSV, no anti-bot, unlike the
port-authority sites which Cloudflare/reCAPTCHA-block). Dataset **`rd72-aq8r` "Monthly TEU Data"** gives
official monthly TEU by US container gateway (`https://data.bts.gov/resource/rd72-aq8r.json`). `data.lacity.org`
(also Socrata) carries POLA's own monthly series (`tsuv-4rgh`, the source of the repo's `pola_teu.csv`).

**Ingested** (`src/process_ais/ingest_bts_official.py`, provenance-hashed in
`data/external/g1v2_official/ingestion_manifest.csv`): monthly TEU **2019-01 … 2022-10 (46 months, covers the
Nov-2021 queue reform)** for the 6 BTS-covered registry gateways — `san_pedro_bay` (= LA + Long Beach summed),
`new_york_new_jersey`, `norfolk_newport_news_va`, `houston_tx`, `charleston_sc`, `savannah_ga`. For
**savannah/houston/charleston TEU is the registry PRIMARY**, so those are fully populated; for SPB/NY-NJ/Norfolk
this fills the **secondary** (TEU) row.

**PRIMARY container-vessel CALLS — now acquired for ALL 11 gateways (annual).** BTS `5rpz-kgm9` "Port Data"
(`cargo_type=VESSEL CALLS`, `trade_type=Container`; source USACE Waterborne Commerce) gives official **annual
container-vessel calls, 2020–2023, for all 11 registry gateways** (SPB = Los Angeles + Long Beach summed).
Ingested to `data/external/g1v2_official_annual/` (+ `annual_ingestion_manifest.csv`, provenance-hashed) by
`ingest_bts_official.ingest_annual_calls()`. This is the resolution the frozen **A4 "annual call-count coverage
ratio"** metric uses, so the primary comparator is available for every gateway — including SPB/NY-NJ/Norfolk.
*Monthly* calls are published **nowhere** (BTS "Calls by Vessel Type" is a chart asset; port authorities give
annual/press-release figures), so the frozen **A5 monthly-anomaly-vs-calls cannot be met for the calls-primary
gateways** — those rest on annual call coverage + monthly-TEU (secondary) anomaly. Data-availability limit, not
a code gap.

**Genuinely residual (require manual port-authority retrieval — not on any clean API):**
- **Monthly TEU for `baltimore_md`, `philadelphia_pa`, `jacksonville_fl`, `miami_fl`, `port_everglades_fl`.** Not
  in the BTS monthly table. 5rpz *annual* container TEU exists for them but **undercounts port-authority TEU
  ~34% (USACE definition — verified against POLA) so it is NOT ingested.** Sources: `miamidade.gov/portmiami/
  statistics.asp`, Broward/Port Everglades, PhilaPort, JAXPORT, Maryland MPA monthly reports (HTML/PDF).
- **2024–2025 window** (frozen temporal holdout + 2023-onward At-Berth). Both BTS monthly TEU (`rd72`→2022-10,
  `iahn`→2023-08) and 5rpz annual (→2023) stop before it. Needs current port-authority series.
- **Decision:** run-once comparison **still not fired** — it runs once when coverage is adequate. Ingesting
  inputs post-freeze is allowed; firing the single decision on partial coverage is not (`plan.md §20`).

**Bonus for Pillar B:** BTS `nfsh-p62e` "Monthly Average Container Vessel Dwell Times" (2019+) and `iiy2-kmkn`
weekly ships-at-anchor counts (LA/LB + Savannah, 2021+) are tabular — candidate independent duration/queue
references for Pillar B and the offshore mass-balance.

## Step 3 — PILLAR B HARNESS: BUILT ✅ + runs on real data; BLOCKED on berth geometry + human labels ⛔
`src/process_ais/pillar_b_state_validation.py` (+ `tests/test_pillar_b_state_validation.py`, 4 tests green;
`--self-check` passes). Episode-level (not raw-ping), blinded, duration-aware; reuses `assign_port_call_ids`
and the single-sourced SOG thresholds. Pieces: `reconstruct_episodes`, `stratified_episode_sample`,
`write_blinded_annotation_bundle` (blinded template + sequestered `prediction_key.csv`), `cohen_kappa`,
`adjudicate`, `score_state` (macro-F1 + bootstrap CI, berth/anchor F1 + resolved coverage, duration signed
bias), `decide_pillar_b` (frozen §5.3 gate; the registered 0.729 result fails it; a missing duration reference
**blocks**, never silently passes).

**Real-data run — San Pedro Bay, Oct-2021 (congestion peak):** 619,588 pings / 350 vessels → **3,167 episodes**
(1,712 moving, 1,455 stationary). Blinded sample of 32 written to
`results/development/pillar_b_spb_2021_10/` (template + sequestered key).

**Finding that blocks a Pillar-B pass today:** resolved (berth/anchor) coverage of stationary episodes is only
**30.4%** because `config/noaa_anchorages.geojson` supplies **anchor polygons only — no berth/terminal
polygons** (0 berth episodes resolvable). This is < the 90% frozen gate and reproduces the registered "39%
coverage" problem (`plan.md §18`). **To unblock:** add container-terminal/berth polygons per gateway (the
`plan.md §20` Month-2 "official terminal records" acquisition; a POLA container-terminal map already sits in
`data/external/g1_v2_geometry_sources/`), then draw the stratified sample, collect two blinded annotators'
labels + adjudication, and run `score_state`/`decide_pillar_b` once on the untouched holdout.

## Bottom line
Freeze is done and the machinery for both pillars is built, tested, and demonstrated on real census pings. The
remaining gate on *both* pillars is the same: **institutional data acquisition** — official container-vessel
call series (Step 2) and container-terminal berth geometry + blinded human labels (Step 3). Neither one-shot
gate is fired until those inputs exist, exactly as the frozen protocol requires.
