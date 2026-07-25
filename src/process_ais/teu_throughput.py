"""Official container-throughput / vessel-call adapter for G1-v2 (matched-comparator ingestion).

Registry-driven, provenance-preserving ingestion of the per-gateway OFFICIAL operational series named in
`config/registries/g1v2_comparator_registry.csv` (container-vessel calls = primary; container TEU = secondary). US port
authorities publish these heterogeneously (HTML/Excel/PDF, no uniform API), so this adapter does NOT
auto-scrape: each series is ingested from a standardized two-column monthly CSV [year_month, value] that the
run-once step produces from the registered source, and every ingest records the source, access date and a
SHA-256 so the comparison is reproducible and auditable.

CONFIRMATORY INTEGRITY: this only ingests/assembles the official INPUTS. It must not be used to compute a
G1-v2 pass/fail until `prereg/studies/g1_v2/G1v2_operational_validation_protocol.md` is frozen (freeze before opening
values). The AIS side of the match is already built (`capacity_weighted_activity.csv` = capacity arrivals;
reconstructed container-vessel calls per complex-month).

Canonical inputs: data/external/g1v2_official/<complex_id>__<metric>.csv  + ingestion_manifest.csv
Run (only after the protocol is frozen):
  python src/process_ais/teu_throughput.py --coverage    # which registered series are present
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "config/registries/g1v2_comparator_registry.csv"
OFFICIAL_DIR = ROOT / "data/external/g1v2_official"
REGISTRY_COLUMNS = {"complex_id", "official_metric", "unit", "primary_or_secondary",
                    "official_source", "ais_metric_matched"}
OFFICIAL_SCHEMA = ["complex_id", "official_metric", "year_month", "value", "unit",
                   "primary_or_secondary", "official_source", "source_hash"]


def load_comparator_registry(path: Path | str = DEFAULT_REGISTRY) -> pd.DataFrame:
    reg = pd.read_csv(path)
    if missing := REGISTRY_COLUMNS - set(reg.columns):
        raise ValueError(f"comparator registry missing columns: {sorted(missing)}")
    return reg


def _canonical_name(complex_id: str, metric: str) -> str:
    return f"{complex_id}__{metric.lower()}.csv"


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ingest_official_series(complex_id: str, metric: str, raw_csv: Path | str, *, source: str,
                           access_date: str | None = None, official_dir: Path = OFFICIAL_DIR) -> Path:
    """Validate one downloaded monthly [year_month, value] series into the canonical, hashed store."""
    raw = pd.read_csv(raw_csv)
    cols = {c.strip().lower(): c for c in raw.columns}
    if "year_month" not in cols or "value" not in cols:
        raise ValueError("official series CSV must have columns 'year_month' and 'value'")
    out = pd.DataFrame({
        "year_month": raw[cols["year_month"]].astype(str).str.slice(0, 7),
        "value": pd.to_numeric(raw[cols["value"]], errors="coerce"),
    }).dropna(subset=["value"]).sort_values("year_month").reset_index(drop=True)
    if not out["year_month"].str.match(r"^\d{4}-\d{2}$").all():
        raise ValueError("year_month values must be YYYY-MM")

    official_dir = Path(official_dir)
    official_dir.mkdir(parents=True, exist_ok=True)
    dest = official_dir / _canonical_name(complex_id, metric)
    out.to_csv(dest, index=False, lineterminator="\n")

    manifest_row = pd.DataFrame([{
        "complex_id": complex_id, "official_metric": metric.upper(), "canonical_file": dest.name,
        "source": source, "access_date": access_date or date.today().isoformat(),
        "sha256": _sha256(dest), "n_months": len(out),
        "coverage": f"{out.year_month.min()}..{out.year_month.max()}",
    }])
    man = official_dir / "ingestion_manifest.csv"
    header = not man.exists()
    manifest_row.to_csv(man, mode="a", header=header, index=False, lineterminator="\n")
    return dest


def assemble_official(registry: pd.DataFrame, official_dir: Path = OFFICIAL_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assemble every present registered official series into one long frame + a coverage report."""
    official_dir = Path(official_dir)
    frames, cov = [], []
    for row in registry.itertuples(index=False):
        f = official_dir / _canonical_name(row.complex_id, row.official_metric)
        present = f.exists()
        cov.append({"complex_id": row.complex_id, "official_metric": row.official_metric,
                    "primary_or_secondary": row.primary_or_secondary, "present": present,
                    "canonical_file": f.name})
        if present:
            s = pd.read_csv(f)
            s.insert(0, "complex_id", row.complex_id)
            s.insert(1, "official_metric", row.official_metric)
            s["unit"] = row.unit
            s["primary_or_secondary"] = row.primary_or_secondary
            s["official_source"] = row.official_source
            s["source_hash"] = _sha256(f)
            frames.append(s.reindex(columns=OFFICIAL_SCHEMA))
    long = (pd.concat(frames, ignore_index=True) if frames
            else pd.DataFrame(columns=OFFICIAL_SCHEMA))
    return long, pd.DataFrame(cov)


def main() -> None:
    ap = argparse.ArgumentParser(description="G1-v2 official comparator adapter (ingest/assemble; freeze protocol first).")
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument("--coverage", action="store_true", help="report which registered official series are present")
    args = ap.parse_args()
    registry = load_comparator_registry(args.registry)
    _, cov = assemble_official(registry)
    if args.coverage or True:
        n = int(cov["present"].sum())
        print(f"registered official series: {len(cov)} ({n} present, {len(cov)-n} awaiting the run-once fetch)")
        print(cov.to_string(index=False))


if __name__ == "__main__":
    main()
