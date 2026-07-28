"""Blind vessel-state validation for G1 (docs/implementation_plan.md §5; gates.yml G1 macro-F1).

The state classifier (`mode_time.assign_state_labels`) assigns berth/anchorage/approach/moving states from
position, speed and frozen zone geometry. An INDEPENDENT ground truth is the AIS **navigation-status** field
(vessel-reported: 0 under-way, 1 at-anchor, 5 moored), which the classifier never sees. Blind macro-F1 is the
agreement between the classifier and navigation status on a common coarse taxonomy {moving, anchored, moored}.

This module (a) freezes clean per-complex state zones from the immutable source snapshot, skipping any complex
whose zones fail the non-overlap check, (b) reads navigation status from the already-retained sparse NOAA
static sample, (c) classifies that sample with the REAL classifier, and (d) writes a decomposed blind-label
table + macro-F1. The label table is consumed by `validate_g1` to close the third G1 sub-gate. No study outcome
is fabricated and no second status download is needed.

Run from repo root:
  python src/process_ais/blind_state_validation.py
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

try:
    from .stream_sample_ais import download, url_for
    from .mode_time import assign_state_labels, STATE_NAMES
    from .national_state_zones import build_state_zones_from_snapshot, load_assignable_port_areas, DEFAULT_ZONE_SOURCES, _PORT_COLUMN
    from ..governance.access import assert_confirmatory_unlocked
except ImportError:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[1]))
    sys.path.insert(0, str(_here.parents[0]))
    from stream_sample_ais import download, url_for  # type: ignore
    from mode_time import assign_state_labels, STATE_NAMES  # type: ignore
    from national_state_zones import build_state_zones_from_snapshot, load_assignable_port_areas, DEFAULT_ZONE_SOURCES, _PORT_COLUMN  # type: ignore
    from governance.access import assert_confirmatory_unlocked  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
PHASE0 = ROOT
DEFAULT_PORT_AREAS = PHASE0 / "config/geometry/port_areas_usace.geojson"
DEFAULT_ASSIGNMENT = PHASE0 / "config/registries/port_area_assignment_coverage.csv"
DEFAULT_STATIC_SAMPLE = PHASE0 / "data/interim/vessel_static_sample"
DEFAULT_LABELS_OUT = PHASE0 / "data/processed/blind_state_labels.csv"

# AIS navigation status is a NOISY AUXILIARY reference (manually maintained onboard; often stale/miscoded),
# NOT a gold-standard label. We therefore validate the reliable speed-based MOTION distinction as primary,
# and report the berth-vs-anchor split only as a caveated auxiliary diagnostic with an explicit
# "unknown_stationary" class (a stationary vessel outside charted berth/anchorage is NOT forced into either).

# --- primary: 2-class motion (moving vs stationary) ---
STATUS_TO_MOTION = {0: "moving", 8: "moving", 3: "moving", 4: "moving", 1: "stationary", 5: "stationary"}
STATE_TO_MOTION = {
    "transit": "moving", "manoeuvre": "moving", "approach_channel": "moving", "departure": "moving",
    "official_anchorage": "stationary", "uncharted_near_port_wait": "stationary",
    "offshore_wait": "stationary", "berth": "stationary",
}
# --- auxiliary: berth-vs-anchor among stationary vessels (classifier's CONFIDENT zone states only) ---
STATUS_TO_BERTH = {1: "anchored", 5: "moored"}
STATE_TO_BERTH = {"berth": "moored", "official_anchorage": "anchored", "offshore_wait": "anchored",
                  "uncharted_near_port_wait": "unknown_stationary"}
ZONE_PRIORITY = ("berth", "official_anchorage", "approach_channel")
RAW_USECOLS = ["mmsi", "base_date_time", "longitude", "latitude", "sog", "vessel_type", "status", "cargo"]
RETAINED_STATUS_COLUMNS = ["mmsi", "timestamp", "port_complex_id", "lat", "lon", "sog", "vessel_type", "status"]


def build_clean_state_zones(port_areas_path=DEFAULT_PORT_AREAS, assignment_path=DEFAULT_ASSIGNMENT,
                            snapshot_path=DEFAULT_ZONE_SOURCES):
    """Freeze zones per complex, skipping any whose geometry fails the non-overlap check. Returns
    (zones GeoDataFrame with port_complex_id/state/geometry, built_ports, skipped_ports)."""
    port_areas, eligible = load_assignable_port_areas(port_areas_path, assignment_path)
    snapshot = gpd.read_file(snapshot_path)
    built, skipped, frames = [], [], []
    for port_id in eligible:
        try:
            zones = build_state_zones_from_snapshot(port_areas, snapshot, eligible_port_ids=[port_id])
        except ValueError:
            skipped.append(port_id)
            continue
        if len(zones):
            frames.append(zones)
            built.append(port_id)
    if not frames:
        raise RuntimeError("no complex produced clean state zones")
    zones = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    return zones.rename(columns={_PORT_COLUMN: "port_complex_id"}), built, skipped


def _read_status_pings(raw_path: str) -> pd.DataFrame:
    import io, zipfile
    def _frame(handle):
        return pd.read_csv(handle, usecols=lambda c: str(c).strip().lower() in RAW_USECOLS,
                           low_memory=False)
    if raw_path.endswith(".zst"):
        import zstandard as zstd
        with open(raw_path, "rb") as f:
            reader = zstd.ZstdDecompressor().stream_reader(f)
            return _frame(io.TextIOWrapper(reader, encoding="utf-8", errors="replace"))
    if raw_path.endswith(".zip"):
        with zipfile.ZipFile(raw_path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as fh:
                return _frame(fh)
    return _frame(raw_path)


def status_sample_for_day(target: date, port_areas: gpd.GeoDataFrame) -> pd.DataFrame:
    """Download one day, keep cargo in-box pings with navigation status, assign port_complex_id."""
    url = url_for(target.year, target.month, target.day)
    suffix = ".zip" if url.endswith(".zip") else ".csv.zst"
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        download(url, tmp)
        raw = _read_status_pings(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    raw.columns = [c.strip().lower() for c in raw.columns]
    vt = pd.to_numeric(raw["vessel_type"], errors="coerce")
    raw = raw.loc[vt.between(70, 79.999)].copy()          # cargo only (matches container gateways; 2018+ codes clean)
    raw["lat"] = pd.to_numeric(raw["latitude"], errors="coerce")
    raw["lon"] = pd.to_numeric(raw["longitude"], errors="coerce")
    raw["sog"] = pd.to_numeric(raw["sog"], errors="coerce")
    raw["nav_status"] = pd.to_numeric(raw["status"], errors="coerce")
    raw = raw.dropna(subset=["lat", "lon"])
    pts = gpd.GeoDataFrame(raw, geometry=gpd.points_from_xy(raw["lon"], raw["lat"]), crs="EPSG:4326")
    joined = gpd.sjoin(pts, port_areas[[_PORT_COLUMN, "geometry"]], how="inner", predicate="within")
    joined = joined.rename(columns={_PORT_COLUMN: "port_complex_id"})
    joined["mmsi"] = joined["mmsi"]
    return joined[["mmsi", "port_complex_id", "lat", "lon", "sog", "nav_status"]].reset_index(drop=True)


def status_sample_from_retained(
    sample_dir: Path | str = DEFAULT_STATIC_SAMPLE,
    *,
    max_pings_per_port_day: int = 250,
) -> pd.DataFrame:
    """Read a deterministic, bounded G1 sample from the retained status-bearing NOAA pings.

    The sparse re-sample already has canonical coordinates, the corrected vessel type and AIS navigation
    status.  Capping by port and retained day keeps spatial classification disk- and memory-safe while
    preserving coverage across the entire 2015--2025 temporal range.  Selection is a stable hash of retained
    fields, never of an outcome or classifier result.
    """
    if max_pings_per_port_day < 1:
        raise ValueError("max_pings_per_port_day must be positive")

    files = sorted(Path(sample_dir).glob("year=*/month=*/pings_*.parquet"))
    if not files:
        raise ValueError(f"no retained static-sample pings found under {sample_dir}")

    frames = []
    for path in files:
        pings = pd.read_parquet(path)
        if missing := set(RETAINED_STATUS_COLUMNS) - set(pings.columns):
            raise ValueError(f"retained static sample missing columns in {path.name}: {sorted(missing)}")
        pings = pings.loc[:, RETAINED_STATUS_COLUMNS].copy()
        pings["vessel_type"] = pd.to_numeric(pings["vessel_type"], errors="coerce")
        pings["nav_status"] = pd.to_numeric(pings.pop("status"), errors="coerce")
        pings = pings.loc[
            pings["vessel_type"].between(70, 79.999)
            & pings["nav_status"].isin(STATUS_TO_MOTION)
        ].dropna(subset=["mmsi", "timestamp", "port_complex_id", "lat", "lon", "sog"])
        if pings.empty:
            continue
        pings["_sample_key"] = pd.util.hash_pandas_object(
            pings[["mmsi", "timestamp", "port_complex_id", "lat", "lon", "sog", "nav_status"]],
            index=False,
        )
        frames.extend(
            group.nsmallest(max_pings_per_port_day, "_sample_key")
            for _, group in pings.groupby("port_complex_id", sort=True)
        )

    if not frames:
        raise ValueError("retained static sample has no cargo pings with a supported navigation status")
    sample = pd.concat(frames, ignore_index=True)
    return (
        sample.sort_values(["port_complex_id", "timestamp", "mmsi", "_sample_key"], kind="stable")
        .loc[:, ["mmsi", "port_complex_id", "lat", "lon", "sog", "nav_status"]]
        .reset_index(drop=True)
    )


def macro_f1_from_sample(sample: pd.DataFrame, zones: gpd.GeoDataFrame) -> tuple[dict, pd.DataFrame]:
    """Classify the sample with the REAL classifier and score it against navigation status, decomposed.

    Returns a metrics dict and the per-ping label table. The PRIMARY, defensible metric is the 2-class
    motion macro-F1 (moving vs stationary). The berth-vs-anchor 3-class F1 is AUXILIARY: it is scored only on
    the classifier's confident zone states (stationary pings the classifier calls 'unknown_stationary' are
    reported as an unresolved share, not penalised), and against a noisy reference, so it is a diagnostic —
    not a pass/fail gate.
    """
    from sklearn.metrics import f1_score, precision_recall_fscore_support

    labelled = assign_state_labels(sample.assign(port_complex_id=sample["port_complex_id"]),
                                   zones, zone_priority=ZONE_PRIORITY)
    df = sample.copy()
    df["predicted_state"] = labelled["state"].values
    df["motion_pred"] = df["predicted_state"].map(STATE_TO_MOTION)
    df["motion_truth"] = df["nav_status"].map(STATUS_TO_MOTION)
    df["berth_pred"] = df["predicted_state"].map(STATE_TO_BERTH)
    df["berth_truth"] = df["nav_status"].map(STATUS_TO_BERTH)

    motion = df.dropna(subset=["motion_truth", "motion_pred"])
    motion_f1 = float(f1_score(motion["motion_truth"], motion["motion_pred"],
                               labels=["moving", "stationary"], average="macro", zero_division=0))
    # per-port motion F1 (reveals whether failure is concentrated in a few ports vs universal)
    per_port = {}
    for port, g in motion.groupby("port_complex_id"):
        if len(g) >= 50:
            per_port[port] = round(float(f1_score(g["motion_truth"], g["motion_pred"],
                                                  labels=["moving", "stationary"], average="macro", zero_division=0)), 3)
    # per-class precision/recall for motion
    p, r, f, _ = precision_recall_fscore_support(motion["motion_truth"], motion["motion_pred"],
                                                 labels=["moving", "stationary"], zero_division=0)
    per_class = {c: {"precision": round(float(pp), 3), "recall": round(float(rr), 3), "f1": round(float(ff), 3)}
                 for c, pp, rr, ff in zip(["moving", "stationary"], p, r, f)}

    # auxiliary berth/anchor among stationary truth, classifier-confident only (unknown_stationary excluded)
    berth = df.dropna(subset=["berth_truth", "berth_pred"])
    confident = berth[berth["berth_pred"].isin(["anchored", "moored"])]
    berth_f1 = (float(f1_score(confident["berth_truth"], confident["berth_pred"],
                               labels=["anchored", "moored"], average="macro", zero_division=0))
                if len(confident) else float("nan"))
    unresolved_share = float((berth["berth_pred"] == "unknown_stationary").mean()) if len(berth) else float("nan")

    metrics = {
        "motion_macro_f1": motion_f1,                     # PRIMARY (2-class, defensible)
        "motion_per_port_f1": per_port,
        "motion_per_class": per_class,
        "n_motion_scored": int(len(motion)),
        "berth_anchor_macro_f1_confident": berth_f1,       # AUXILIARY diagnostic
        "berth_unresolved_stationary_share": unresolved_share,
        "n_berth_confident": int(len(confident)),
        "reference": "AIS navigation status (noisy auxiliary, not gold-standard)",
    }
    labels = df[["port_complex_id", "motion_truth", "motion_pred", "berth_truth", "berth_pred", "predicted_state"]]
    return metrics, labels.reset_index(drop=True)


def run(
    *,
    sample_dir: Path | str = DEFAULT_STATIC_SAMPLE,
    max_pings_per_port_day: int = 250,
    labels_out: Path = DEFAULT_LABELS_OUT,
) -> dict:
    port_areas, _ = load_assignable_port_areas(DEFAULT_PORT_AREAS, DEFAULT_ASSIGNMENT)
    zones, built, skipped = build_clean_state_zones()
    port_areas = port_areas.loc[port_areas[_PORT_COLUMN].isin(built)]   # only complexes with clean zones
    sample = status_sample_from_retained(sample_dir, max_pings_per_port_day=max_pings_per_port_day)
    sample = sample.loc[sample["port_complex_id"].isin(built)].reset_index(drop=True)
    metrics, labels = macro_f1_from_sample(sample, zones)
    labels_out = Path(labels_out)
    assert_confirmatory_unlocked(labels_out)
    labels_out.parent.mkdir(parents=True, exist_ok=True)
    labels.to_csv(labels_out, index=False, lineterminator="\n")
    print(f"complexes with clean zones: {len(built)} (skipped {len(skipped)}: {skipped})")
    print(f"blind sample: {len(sample):,} cargo in-box pings; motion-scored {metrics['n_motion_scored']:,}")
    print(f"reference: {metrics['reference']}")
    print(f"PRIMARY  motion macro-F1 (moving vs stationary) = {metrics['motion_macro_f1']:.3f}")
    print(f"  per-class: {metrics['motion_per_class']}")
    print(f"  per-port : {metrics['motion_per_port_f1']}")
    bf = metrics["berth_anchor_macro_f1_confident"]
    print(f"AUXILIARY berth-vs-anchor macro-F1 (confident zone states only) = "
          f"{bf:.3f} on {metrics['n_berth_confident']:,} pings; "
          f"unresolved stationary share = {metrics['berth_unresolved_stationary_share']:.2f}  "
          f"(diagnostic only; nav status is noisy + berth polygons incomplete)")
    print(f"wrote {labels_out}")
    return {**metrics, "built": built, "skipped": skipped}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Blind vessel-state macro-F1 from retained AIS navigation-status pings.")
    ap.add_argument("--sample-dir", type=Path, default=DEFAULT_STATIC_SAMPLE)
    ap.add_argument("--max-pings-per-port-day", type=int, default=250)
    ap.add_argument("--out", type=Path, default=DEFAULT_LABELS_OUT)
    args = ap.parse_args()
    run(sample_dir=args.sample_dir, max_pings_per_port_day=args.max_pings_per_port_day, labels_out=args.out)


if __name__ == "__main__":
    main()
