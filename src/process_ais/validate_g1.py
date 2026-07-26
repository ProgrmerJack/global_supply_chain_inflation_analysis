"""Task 6 — G1 national AIS-validity gate driver (docs/implementation_plan.md §5; gates.yml G1).

Turns a national port-state-month panel (built by `mode_time.aggregate_state_month`) plus official
port activity into the registered G1 decision. It reuses the already-tested gate arithmetic in
`mode_validation.evaluate_g1`; this module only supplies the driver responsibilities that did not yet
exist: per-port activity correlation over paired months, blind vessel-state macro-F1, the validated-complex
count, and a confirmatory-guarded `gate_decision.json` writer.

G1 (verbatim, gates.yml): monthly AIS activity correlates r>=0.80 with official calls/throughput in >=80%
of validation ports; blind vessel-state macro-F1 >=0.85; >=12 validated complexes for a national claim.

This driver is data-ready but does not fabricate inputs. Producing a real G1 decision requires (a) the
national vessel-state panel from ingested NOAA AIS across >=12 complexes and (b) an official monthly
port-activity series (e.g. Census vessel imports by port, USACE/BTS calls). Both are operational
data-acquisition steps; the arithmetic and gate logic here are exercised on synthetic fixtures.

Run from repo root (once the panel and official activity exist):
    python src/process_ais/validate_g1.py --panel <panel.parquet> --official <official.csv>

EXACT COMMAND THAT REPRODUCES THE PUBLISHED G1 DECISION (verified 2026-08-06):

    python src/process_ais/validate_g1.py \
        --panel data/processed/national_activity_month.csv \
        --official data/processed/official_port_activity_ves_wgt_mo.csv \
        --measure freight_port_calls \
        --comparator cargo_tonnage \
        --blind-labels data/processed/blind_state_labels.csv \
        --evidence-status development \
        --out <scratch>/g1_recheck.json

    reproduces, to full precision, the three registered components:
        activity     median r = 0.3200241092239818   (FAIL vs the 0.80 criterion)  -> Paper C M02
        motion state macro-F1 = 0.7288887505928576   (FAIL vs 0.80)                -> Paper C M03
        berth/anchor F1       = 0.9895978427549311   (diagnostic; 60.854% unresolved)

    Writing to a scratch path leaves the registered decision untouched; this driver cannot reopen or
    overwrite `results/development/G1_ais_fullcensus/gate_decision_ves_wgt_mo.json`.

REGISTERED CONFIGURATION THAT PRODUCED THE PUBLISHED NUMBERS (documented 2026-08-06).
An external reviewer previously could not run this module at all: the two required arguments are
described generically above, and no invocation appeared anywhere in the repository, so the values
behind Paper C's claims M02 and M03 could not be regenerated. The registered pairing, recovered from
`results/development/G1_ais_fullcensus/audit_g1_v1_2026-07-15.md`, is:

    measure     AIS `freight_port_calls` -- 24-h gap-defined call starts for NMEA vessel types 70-89
    comparator  Census `VES_WGT_MO` -- imports-only vessel shipping weight, monthly, by port
                (staged under data/interim/official_port_activity/cnt_wgt_mo/)
    panel       the national complex-month activity panel (data/processed/national_activity_month.csv)
    scope       15 complexes x 120 paired months

    Decision evidence : results/development/G1_ais_fullcensus/gate_decision_ves_wgt_mo.json
    Registered values : median r = 0.320024, 0/15 ports at r >= 0.80 (M02)
                        motion macro-F1 = 0.728889 on 480,768 pings, 60.854% of stationary
                        observations unresolved (M03)
    Registration      : OSF vs9bu (2026-07-15), parent htdqp (2026-07-13)

The gate is CLOSED and its decision is immutable: the audit above documents rather than edits the
decision file, and re-running this driver cannot reopen or overwrite it. The comparator is a partial
construct match by the project's own account (calls are an event count, VES_WGT_MO is a cargo mass),
which is the substance of Paper C's argument -- see the threshold discussion in that manuscript.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .mode_validation import G1_CORRELATION_MIN, G1_PORT_FRACTION_MIN, G1_VALIDATED_COMPLEXES_MIN
    from ..governance.access import assert_confirmatory_unlocked
except ImportError:  # flat context (script run, or package imported as a top-level namespace)
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[1]))   # src/ -> governance package
    sys.path.insert(0, str(_here.parents[0]))   # src/process_ais/ -> sibling flat modules
    from mode_validation import G1_CORRELATION_MIN, G1_PORT_FRACTION_MIN, G1_VALIDATED_COMPLEXES_MIN  # type: ignore
    from governance.access import assert_confirmatory_unlocked  # type: ignore


MIN_OVERLAP_MONTHS = 12  # a complex enters the validation set only with >=12 paired AIS/official months
G1_RULE = (
    "Monthly AIS activity correlates r>=0.80 with official calls/throughput in >=80% of validation ports; "
    "blind vessel-state macro-F1>=0.85; >=12 validated complexes for a national claim."
)


def ais_monthly_activity(panel: pd.DataFrame, measure: str = "unique_vessels") -> pd.DataFrame:
    """Derive a monthly AIS activity series per complex from the port-state-month panel.

    ``*_port_calls`` are the registered 24-hour-gap call measures and should be preferred where their
    physical vessel class matches the official comparator.  ``unique_vessels`` is retained only as a
    descriptive monthly presence measure; ``ship_days`` sums berthing/anchoring state hours over 24.
    None uses a price, pollution or policy outcome (G1 must stay outcome-blind).
    """
    keys = ["port_complex_id", "year_month"]
    if missing := set(keys) - set(panel.columns):
        raise ValueError(f"panel missing columns: {sorted(missing)}")
    out = panel[keys].copy()
    if measure == "unique_vessels":
        if "unique_vessels" not in panel:
            raise ValueError("panel has no unique_vessels column")
        out["ais_activity"] = pd.to_numeric(panel["unique_vessels"], errors="coerce")
    elif measure == "cargo_vessels":
        if "unique_cargo_vessels" not in panel:
            raise ValueError("panel has no unique_cargo_vessels column")
        out["ais_activity"] = pd.to_numeric(panel["unique_cargo_vessels"], errors="coerce")
    elif measure in {"cargo_port_calls", "freight_port_calls"}:
        if measure not in panel:
            raise ValueError(f"panel has no {measure} column")
        out["ais_activity"] = pd.to_numeric(panel[measure], errors="coerce")
    elif measure == "ship_days":
        hour_cols = [f"{state}_hours" for state in ("official_anchorage", "berth", "uncharted_near_port_wait")]
        present = [c for c in hour_cols if c in panel.columns]
        if not present:
            raise ValueError("panel has no port-side state-hour columns for ship_days")
        out["ais_activity"] = panel[present].apply(pd.to_numeric, errors="coerce").sum(axis=1) / 24.0
    else:
        raise ValueError(f"unsupported AIS activity measure: {measure!r}")
    return out


def port_activity_correlations(
    ais_activity: pd.DataFrame,
    official_activity: pd.DataFrame,
    *,
    min_months: int = MIN_OVERLAP_MONTHS,
) -> tuple[dict[str, float], pd.DataFrame]:
    """Per-complex Pearson correlation of monthly AIS vs official activity over paired months.

    Returns (correlations for complexes with >=min_months paired months, a per-complex validation report).
    Complexes with too few paired months or zero variance are excluded from the validation set, not silently
    assigned a value.
    """
    for name, frame, col in (("ais", ais_activity, "ais_activity"), ("official", official_activity, "official_activity")):
        if missing := {"port_complex_id", "year_month", col} - set(frame.columns):
            raise ValueError(f"{name} activity missing columns: {sorted(missing)}")

    merged = ais_activity.merge(official_activity, on=["port_complex_id", "year_month"], how="inner")
    correlations: dict[str, float] = {}
    rows = []
    for port, group in merged.groupby("port_complex_id", sort=True):
        paired = group.dropna(subset=["ais_activity", "official_activity"])
        n = len(paired)
        if n < min_months:
            rows.append({"port_complex_id": port, "paired_months": n, "correlation": np.nan, "status": "insufficient_overlap"})
            continue
        if paired["ais_activity"].std(ddof=0) == 0 or paired["official_activity"].std(ddof=0) == 0:
            rows.append({"port_complex_id": port, "paired_months": n, "correlation": np.nan, "status": "zero_variance"})
            continue
        r = float(np.corrcoef(paired["ais_activity"], paired["official_activity"])[0, 1])
        correlations[port] = r
        rows.append({"port_complex_id": port, "paired_months": n, "correlation": r, "status": "validated"})
    report = pd.DataFrame(rows, columns=["port_complex_id", "paired_months", "correlation", "status"])
    return correlations, report


MOTION_F1_MIN = 0.80  # 2-class moving/stationary is the validatable state metric (critique §4-C)
# import value is an ECONOMIC quantity, not a vessel-activity comparator -> activity correlation is DIAGNOSTIC
OPERATIONALLY_MATCHED_COMPARATORS = {"container_vessel_calls", "teu_throughput", "vessel_class_calls", "cargo_tonnage"}
G1_RULE_STRUCTURED = (
    "G1 (revised, component-separated): (A) ingestion integrity; (B) activity vs an OPERATIONALLY MATCHED "
    "official series (vessel calls/TEU, NOT import value); (C) motion moving-vs-stationary macro-F1>=0.80; "
    "(D) berth-vs-anchor is a diagnostic, not a pass/fail gate; scope>=12 complexes. Import-value activity "
    "correlation and navigation-status berth/anchor F1 are DIAGNOSTIC only."
)


def state_metrics_from_labels(labels: pd.DataFrame) -> dict:
    """Motion (primary) + berth/anchor (diagnostic) metrics from a blind_state_validation label table."""
    from sklearn.metrics import f1_score
    need = {"motion_truth", "motion_pred", "berth_truth", "berth_pred"}
    if need - set(labels.columns):
        if {"truth", "predicted"}.issubset(labels.columns):
            raise ValueError(
                "legacy blind-label schema detected (truth,predicted); regenerate decomposed "
                "motion_truth/motion_pred/berth_truth/berth_pred labels from the retained static sample"
            )
        raise ValueError(f"blind labels missing columns: {sorted(need - set(labels.columns))}")
    m = labels.dropna(subset=["motion_truth", "motion_pred"])
    motion_f1 = float(f1_score(m["motion_truth"], m["motion_pred"], labels=["moving", "stationary"],
                               average="macro", zero_division=0))
    b = labels.dropna(subset=["berth_truth", "berth_pred"])
    conf = b[b["berth_pred"].isin(["anchored", "moored"])]
    berth_f1 = (float(f1_score(conf["berth_truth"], conf["berth_pred"], labels=["anchored", "moored"],
                               average="macro", zero_division=0)) if len(conf) else None)
    unresolved = float((b["berth_pred"] == "unknown_stationary").mean()) if len(b) else None
    return {"motion_macro_f1": motion_f1, "n_motion_scored": int(len(m)),
            "berth_anchor_macro_f1_confident": berth_f1, "berth_unresolved_stationary_share": unresolved,
            "n_berth_confident": int(len(conf))}


def reproducibility_manifest(inputs: dict, *, measure: str, comparator: str, notes: str = "") -> dict:
    """Freeze input hashes + config so a development result stays reproducible (critique §6)."""
    import hashlib
    import platform

    def _sha(path):
        path = Path(path)
        if not path.exists():
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()

    return {"inputs": {role: {"path": str(p), "sha256": _sha(p)} for role, p in inputs.items()},
            "measure": measure, "comparator": comparator, "notes": notes,
            "python": platform.python_version(),
            "frozen_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


def decide_g1(
    ais_activity: pd.DataFrame,
    official_activity: pd.DataFrame,
    state_metrics: dict | None = None,
    *,
    evidence_status: str = "development",
    comparator: str = "import_value",
    measure: str = "cargo_vessels",
    min_months: int = MIN_OVERLAP_MONTHS,
    reproducibility: dict | None = None,
    integrity: dict | None = None,
) -> dict:
    """Assemble the revised, component-separated G1 decision (critique §4).

    On DEVELOPMENT evidence (inspected sampled data) no confirmatory pass/fail is emitted. Import-value
    activity correlation and navigation-status berth/anchor F1 are reported as DIAGNOSTICS, not gates.
    Only ingestion integrity, national scope, a matched-comparator activity gate and the 2-class motion
    gate are confirmatory-eligible.
    """
    correlations, report = port_activity_correlations(ais_activity, official_activity, min_months=min_months)
    validated = len(correlations)
    rs = np.array(list(correlations.values())) if correlations else np.array([])
    matched = comparator in OPERATIONALLY_MATCHED_COMPARATORS
    frac = float((rs >= G1_CORRELATION_MIN).mean()) if len(rs) else 0.0
    activity_status = ("pass" if frac >= G1_PORT_FRACTION_MIN else "fail") if matched else "diagnostic"
    activity = {
        "comparator": comparator,
        "operationally_matched": matched,
        "status": activity_status,
        "port_fraction_ge_min": frac,
        "median_r": float(np.median(rs)) if len(rs) else None,
        "n_ports": validated,
        "per_port_correlations": {p: correlations[p] for p in sorted(correlations)},
        "note": ("" if matched else "import value is price/mix/inflation-laden, not a vessel-activity "
                 "comparator; use container-vessel calls or TEU throughput for a confirmatory activity "
                 "gate — this correlation is DIAGNOSTIC only"),
    }
    scope = {"validated_complexes": validated, "min": G1_VALIDATED_COMPLEXES_MIN,
             "status": "pass" if validated >= G1_VALIDATED_COMPLEXES_MIN else "fail"}
    motion = {"status": "not_provided"}
    berth = {"status": "not_provided"}
    if state_metrics is not None:
        mf1 = state_metrics.get("motion_macro_f1")
        motion = {"macro_f1": mf1, "threshold": MOTION_F1_MIN,
                  "status": ("pass" if (mf1 is not None and mf1 >= MOTION_F1_MIN) else "fail"),
                  "reference": "AIS navigation status (noisy auxiliary)",
                  "n_scored": state_metrics.get("n_motion_scored")}
        berth = {"status": "diagnostic",
                 "macro_f1_confident": state_metrics.get("berth_anchor_macro_f1_confident"),
                 "unresolved_stationary_share": state_metrics.get("berth_unresolved_stationary_share"),
                 "note": "berth polygons incomplete + navigation status noisy; not a pass/fail gate"}
    components = {
        "ingestion_integrity": integrity or {"status": "not_provided"},
        "activity_correlation": activity,
        "motion_state": motion,
        "berth_anchor_state": berth,
        "national_scope": scope,
    }
    if evidence_status != "confirmatory":
        overall = "development"
    else:
        gates = [scope["status"] == "pass"]
        if motion.get("status") in ("pass", "fail"):
            gates.append(motion["status"] == "pass")
        if integrity and integrity.get("status") in ("pass", "fail"):
            gates.append(integrity["status"] == "pass")
        if matched:
            gates.append(activity_status == "pass")
        overall = "pass" if all(gates) else "fail"
    return {
        "gate": "G1",
        "name": "national AIS validity (revised architecture)",
        "evidence_status": evidence_status,
        "status": overall,
        "rule": G1_RULE_STRUCTURED,
        "components": components,
        "reproducibility": reproducibility or {},
        "validation_report": report.to_dict(orient="records"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def write_g1_decision(decision: dict, out_path: Path | str) -> Path:
    """Write the decision, refusing protected confirmatory paths without a verified unlock (fail closed)."""
    out_path = Path(out_path)
    assert_confirmatory_unlocked(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(decision, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return out_path


def _load_official(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "official_activity" not in df.columns:
        raise ValueError("official activity CSV must contain an 'official_activity' column")
    return df


def _read_panel(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)


DEFAULT_PINGS_MANIFEST = (Path(__file__).resolve().parents[2]
                          / "data/interim/national_pings/ingestion_manifest.csv")


def ingestion_integrity(manifest_path: Path | str) -> dict:
    """G1-A ingestion integrity from the append-only ingestion ledger.

    A failed download is retained as an audit record and a later successful retry is appended for the
    same date.  The gate therefore evaluates the final coverage *by date*, while exposing both retry
    and superseded-error counts rather than treating a recovered day as an unresolved failure.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return {"status": "not_provided", "note": f"manifest absent: {manifest_path}"}
    m = pd.read_csv(manifest_path)
    required = {"date", "status"}
    if missing := required - set(m.columns):
        return {"status": "not_provided", "note": f"manifest missing columns: {sorted(missing)}"}

    entries = m.loc[m["date"].notna(), ["date", "status"]].copy()
    entries["date"] = entries["date"].astype(str)
    entries["status"] = entries["status"].fillna("").astype(str).str.strip().str.lower()
    if entries.empty:
        return {"status": "not_provided", "note": "manifest has no dated ingestion records"}

    statuses_by_day = entries.groupby("date", sort=True)["status"].agg(set)
    succeeded = statuses_by_day.map(lambda statuses: "ok" in statuses)
    unresolved = statuses_by_day.loc[~succeeded]
    error_days = int(unresolved.map(lambda statuses: "error" in statuses).sum())
    missing_days = int(unresolved.map(lambda statuses: "missing" in statuses and "error" not in statuses).sum())
    unknown_days = int(len(unresolved) - error_days - missing_days)
    retry_counts = entries.groupby("date", sort=True).size()
    error_attempts = int((entries["status"] == "error").sum())
    superseded_error_attempts = int(
        entries.loc[entries["status"].eq("error"), "date"].isin(succeeded.index[succeeded]).sum()
    )
    unresolved_days = int(len(unresolved))
    note = "all dated ingestion records have a successful retained result"
    if unresolved_days:
        note = f"{unresolved_days} date(s) lack a successful ingestion result"

    return {
        "status": "pass" if unresolved_days == 0 else "fail",
        "days_ok": int(succeeded.sum()),
        "days_error": error_days,
        "days_missing": missing_days,
        "days_unknown": unknown_days,
        "days_total": int(len(statuses_by_day)),
        "attempt_rows": int(len(entries)),
        "retried_days": int((retry_counts > 1).sum()),
        "error_attempts": error_attempts,
        "superseded_error_attempts": superseded_error_attempts,
        "note": note,
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Evaluate the revised, component-separated G1 gate.")
    parser.add_argument("--panel", type=Path, required=True, help="port-state-month or activity panel (parquet/csv)")
    parser.add_argument("--official", type=Path, required=True, help="official monthly port-activity CSV")
    parser.add_argument("--blind-labels", type=Path, default=None,
                        help="blind_state_validation label CSV (motion_/berth_ columns); omit until produced")
    parser.add_argument("--measure", default="cargo_vessels",
                        choices=["cargo_vessels", "unique_vessels", "cargo_port_calls", "freight_port_calls", "ship_days"])
    parser.add_argument("--comparator", default="import_value",
                        help="official comparator; 'import_value' is DIAGNOSTIC (not operationally matched)")
    parser.add_argument("--evidence-status", default="development", choices=["development", "confirmatory"])
    parser.add_argument("--ingestion-manifest", type=Path, default=DEFAULT_PINGS_MANIFEST,
                        help="ingestion manifest for the G1-A integrity component")
    parser.add_argument("--out", type=Path,
                        default=Path("results/development/G1_ais_8day/gate_decision.json"),
                        help="gate decision path (development by default; results/confirmatory only when frozen)")
    args = parser.parse_args()

    ais = ais_monthly_activity(_read_panel(args.panel), measure=args.measure)
    official = _load_official(args.official)
    state_metrics = None
    inputs = {"panel": args.panel, "official_activity": args.official}
    if args.blind_labels is not None:
        state_metrics = state_metrics_from_labels(pd.read_csv(args.blind_labels))
        inputs["blind_labels"] = args.blind_labels
    integrity = ingestion_integrity(args.ingestion_manifest) if args.ingestion_manifest else None
    repro = reproducibility_manifest(inputs, measure=args.measure, comparator=args.comparator,
                                     notes=f"evidence={args.evidence_status}")
    decision = decide_g1(ais, official, state_metrics, evidence_status=args.evidence_status,
                         comparator=args.comparator, measure=args.measure, reproducibility=repro, integrity=integrity)
    out = write_g1_decision(decision, args.out)
    c = decision["components"]
    mo = c["motion_state"].get("macro_f1")
    print(f"G1 [{decision['evidence_status']}] status={decision['status']}")
    print(f"  scope        : {c['national_scope']['status']} ({c['national_scope']['validated_complexes']} complexes)")
    print(f"  activity     : {c['activity_correlation']['status']} (comparator={args.comparator}, "
          f"median r={c['activity_correlation']['median_r']}, matched={c['activity_correlation']['operationally_matched']})")
    print(f"  motion state : {c['motion_state']['status']} (macro-F1={mo})")
    print(f"  berth/anchor : {c['berth_anchor_state']['status']} "
          f"(F1={c['berth_anchor_state'].get('macro_f1_confident')}, diagnostic)")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
