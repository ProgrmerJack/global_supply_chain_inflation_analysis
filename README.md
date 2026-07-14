# The coupled environmental and economic costs of US port congestion (2009–2025)

A 17-year, vessel-level account of **idling emissions** and **goods prices** at five US port complexes,
built from terrestrial AIS. One physical measure — vessel **dwell time** — is used to quantify two
externalities of port congestion at once: anchorage air emissions and sectoral inflation.

## Headline results

- **Concentration.** Only Los Angeles/Long Beach dwell co-moves with the NY Fed GSCPI (r = 0.47,
  autocorrelation-robust p = 0.014; both series stationary, so not spurious); robust to port-call
  segmentation (r = 0.46 at a 24-h call gap) and to an anchor-ship-day measure (r = 0.40); other ports ≈ 0.
- **Coupled prices (state-dependent, non-causal).** A full-sample interaction local projection shows a
  goods-CPI response significant only in the high-congestion regime (+1.20%, p = 0.01), ~3× services.
  Survives import-price/freight controls (+1.28%) and an anchor-ship-day shock (+1.11%), is
  Bonferroni-robust across horizons, and is not reproduced by placebo ports.
- **Anchorage idling emissions (CARB-calibrated).** 2021 reached ~3.3× the 2016–2019 (pre-pandemic
  non-crisis) baseline; per-ship-day CO₂ intensity 54 t (method-dependent band [24, 69]); 2021
  environmental social cost order US$340M (band $150–630M).
- **Nov-2021 queuing reform (measurement caveat).** ~19% near-port anchorage decline, but not a causal
  estimate (n = 5, p = 0.20); ships relocate >150 nm offshore, so it is a lower bound on avoided emissions.

## Repository layout

```
manuscript/         LaTeX manuscripts (pdflatex + bibtex; Paper B has inline refs, pdflatex only)
  paper_A_CEE.tex        Communications Earth & Environment (Article)
  paper_B_scidata.tex    Scientific Data (Data Descriptor)
  paper_A_SI.tex         Supplementary Information (sections S1–S12)
  cover_letter_CEE.tex   cover letter for Paper A
  cover_letter_scidata.tex   cover letter for Paper B
  references.bib         verified citations
src/
  process_ais/      AIS download, extraction, dwell, mode classification, zone building
  emissions/        CARB-calibrated emissions, per-TEU, era-seam QC, factors
  models/           congestion index, local projections, inference, unit-root
config/             mode-zone polygons, NOAA anchorages, IMO emission factors
data/               processed census + curated pings (see data availability)
outputs/            canonical results + manuscript figures (see outputs/README.md)
_archive/           historical drafts, planning, verification, zone diagnostics (see its README)
_REMOVE/            superseded artifacts staged for deletion (see its README)
DEPOSIT_PACKAGE.md  Zenodo deposit manifest, metadata, and DOI-first steps
PROJECT_FULL_OVERVIEW.md   self-contained project overview
```

## Reproducibility — ten standing guard scripts

Every headline regenerates from the deposited data via assert-guarded checks that fail loudly on
regression (six validate the dataset, four the analysis):

| Script | Checks |
|---|---|
| `src/emissions/calibrated_emissions.py` | emissions intensity, band, 17-yr totals, social-cost band |
| `src/emissions/era_seam_qc.py` | FGDB→CSV era-boundary continuity |
| `src/emissions/per_teu.py` | per-TEU 3.4× |
| `src/process_ais/ais_qc.py` | AIS anomaly audit (MMSI, position spikes; dwell–GSCPI r invariant) |
| `src/process_ais/port_call_segmentation.py` | GSCPI concentration survives port-call segmentation |
| `src/process_ais/mode_validation.py` | mode SOG-threshold + anchorage-buffer sensitivity |
| `src/models/state_lp.py` | state-dependent price interaction LP |
| `src/models/price_robustness.py` | price result: controls, anchor-shock, placebos, Bonferroni |
| `src/models/inference.py` | concentration r, detrending, anchor-time cross-check, reform DiD |
| `src/models/unit_root.py` | ADF/KPSS stationarity (not-spurious) |

## Data availability

Dataset deposited at Zenodo under CC-BY-4.0: **DOI 10.5281/zenodo.21203605**
(209.5M curated AIS pings, dwell/mode census, CARB-calibrated emissions, macro panel, TEU series, FRED
macro controls, zones).
Underlying sources: NOAA Marine Cadastre AIS (public domain), NY Fed GSCPI, US BLS CPI, Federal Reserve
IndPro/oil, Port of Los Angeles TEU, CARB congestion inventory. Companion Scientific Data descriptor
(Paper B) documents the records.

## Author

Abduxoliq Ashuraliyev (sole author, ORCID 0009-0003-5482-5526).
