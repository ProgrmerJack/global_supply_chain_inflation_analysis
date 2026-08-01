"""Frozen, outcome-blind measurement helpers for the Baltimore shock study."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config/protocol/baltimore_infrastructure_shock.json"
PROJECTED_CRS = "EPSG:26918"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# The frozen design JSON records input paths as they stood when it was registered. On 2026-08-06 the
# config data was grouped into config/{geometry,registries,protocol}/ (amendment
# prereg/amendments/2026-08-06_config_prereg_subfoldering.md). The registered JSON is NOT rewritten --
# that would change its own hash and destroy the record of what was registered -- so the loader
# resolves a recorded path to its current location instead. The content hash recorded alongside each
# path is still verified, so a moved file whose bytes changed still fails.
_CONFIG_RELOCATIONS = {
    "config/national_state_zones.geojson": "config/geometry/national_state_zones.geojson",
    "config/carb_atberth_spb_tanker_terminals.csv":
        "config/registries/carb_atberth_spb_tanker_terminals.csv",
    "config/national_state_zone_coverage.csv":
        "config/registries/national_state_zone_coverage.csv",
}


def resolve_recorded_path(recorded: str) -> Path:
    """Map a path as the frozen design recorded it onto where the file lives now."""
    candidate = ROOT / _CONFIG_RELOCATIONS.get(recorded, recorded)
    if candidate.is_file():
        return candidate
    return ROOT / recorded  # let the caller raise with the recorded path in the message


def load_design(path: Path = CONFIG_PATH) -> dict:
    design = json.loads(Path(path).read_text(encoding="utf-8"))
    phases = design["phases"]
    bounds = [(pd.Timestamp(row["start"]), pd.Timestamp(row["end"])) for row in phases]
    if any(end < start for start, end in bounds):
        raise ValueError("phase end precedes phase start")
    if any(bounds[i][1] + pd.Timedelta(days=1) != bounds[i + 1][0] for i in range(len(bounds) - 1)):
        raise ValueError("phases must be contiguous and non-overlapping")
    if set(design["receiver_candidates"]) & set(design["nonreceiver_placebos"]):
        raise ValueError("receiver and placebo sets overlap")
    if not set(design["receiver_candidates"] + design["nonreceiver_placebos"]).issubset(design["retained_census_complexes"]):
        raise ValueError("an analysis port is absent from the retained census")
    geometry = resolve_recorded_path(design["bridge_geometry"])
    if sha256(geometry) != design["bridge_geometry_sha256"]:
        raise ValueError("official bridge geometry hash mismatch")
    berth_geometry = resolve_recorded_path(design["measurement"]["berth_geometry"])
    if sha256(berth_geometry) != design["measurement"]["berth_geometry_sha256"]:
        raise ValueError("frozen berth geometry hash mismatch")
    return design


def load_bridge(design: dict | None = None) -> LineString:
    design = design or load_design()
    frame = gpd.read_file(ROOT / design["bridge_geometry"])
    if len(frame) != 1 or frame.geometry.iloc[0].geom_type != "LineString":
        raise ValueError("bridge geometry must contain exactly one LineString")
    return gpd.GeoSeries(frame.geometry, crs=frame.crs).to_crs(PROJECTED_CRS).iloc[0]


def _chord_side(x: float, y: float, bridge: LineString) -> int:
    (x1, y1), (x2, y2) = bridge.coords[0], bridge.coords[-1]
    signed = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
    return int(np.sign(signed))


def inland_side_from_berths(bridge: LineString, berth_geometry) -> int:
    """Choose the bridge-chord side containing most berth-geometry components."""
    parts = list(getattr(berth_geometry, "geoms", [berth_geometry]))
    sides = [_chord_side(point.x, point.y, bridge) for point in (part.representative_point() for part in parts)]
    positive, negative = sides.count(1), sides.count(-1)
    if positive == negative or not (positive or negative):
        raise ValueError("berth geometry does not identify a strict inland-side majority")
    return 1 if positive > negative else -1


def track_crossings(
    pings: pd.DataFrame,
    bridge: LineString,
    inland_side: int,
    *,
    buffer_m: float = 250.0,
    max_minutes: float = 30.0,
) -> pd.DataFrame:
    """Return robust crossings between stable sides of the finite bridge line."""
    required = {"mmsi", "timestamp", "lon", "lat"}
    if missing := required - set(pings.columns):
        raise ValueError(f"crossing pings missing columns: {sorted(missing)}")
    if inland_side not in {-1, 1} or buffer_m < 0 or max_minutes <= 0:
        raise ValueError("invalid crossing parameters")

    rows = pings.copy()
    rows["timestamp"] = pd.to_datetime(rows["timestamp"], errors="coerce", utc=True)
    rows = rows.dropna(subset=list(required)).sort_values(["mmsi", "timestamp"], kind="stable")
    points = gpd.GeoSeries(gpd.points_from_xy(rows.lon, rows.lat), crs="EPSG:4326").to_crs(PROJECTED_CRS)
    rows = rows.assign(
        projected_geometry=points.array,
        bridge_distance_m=[point.distance(bridge) for point in points],
        bridge_side=[_chord_side(point.x, point.y, bridge) for point in points],
    )
    rows = rows.loc[rows.bridge_distance_m.ge(buffer_m) & rows.bridge_side.ne(0)]

    found: list[dict] = []
    for mmsi, group in rows.groupby("mmsi", sort=False):
        previous = None
        for row in group.itertuples():
            if previous is not None:
                minutes = (row.timestamp - previous.timestamp).total_seconds() / 60
                segment = LineString([previous.projected_geometry, row.projected_geometry])
                if 0 < minutes <= max_minutes and row.bridge_side != previous.bridge_side and segment.intersects(bridge):
                    found.append(
                        {
                            "mmsi": mmsi,
                            "timestamp": previous.timestamp + (row.timestamp - previous.timestamp) / 2,
                            "direction": "inbound" if row.bridge_side == inland_side else "outbound",
                            "segment_minutes": minutes,
                        }
                    )
            previous = row
    return pd.DataFrame(found, columns=["mmsi", "timestamp", "direction", "segment_minutes"])


def presence_intervals(pings: pd.DataFrame, *, cap_minutes: float = 30.0) -> pd.DataFrame:
    """Convert observed pings to capped port-presence intervals; never impute gaps."""
    required = {"mmsi", "timestamp", "port_complex_id"}
    if missing := required - set(pings.columns):
        raise ValueError(f"presence pings missing columns: {sorted(missing)}")
    if cap_minutes <= 0:
        raise ValueError("cap_minutes must be positive")
    rows = pings.copy()
    rows["timestamp"] = pd.to_datetime(rows["timestamp"], errors="coerce", utc=True)
    rows = rows.dropna(subset=list(required)).sort_values(
        ["mmsi", "port_complex_id", "timestamp"], kind="stable"
    )
    next_time = rows.groupby(["mmsi", "port_complex_id"], sort=False)["timestamp"].shift(-1)
    minutes = (next_time - rows.timestamp).dt.total_seconds() / 60
    valid = minutes.gt(0)
    rows = rows.loc[valid, ["mmsi", "port_complex_id", "timestamp"]].copy()
    rows["presence_hours"] = minutes.loc[valid].clip(upper=cap_minutes) / 60
    rows["midpoint_utc"] = rows.timestamp + pd.to_timedelta(rows.presence_hours / 2, unit="h")
    return rows


def receiver_weights(
    episodes: pd.DataFrame,
    receivers: list[str],
    *,
    baltimore: str = "baltimore_md",
    max_days: int = 60,
    minimum: int = 10,
) -> pd.DataFrame:
    """Freeze receiver weights from consecutive bidirectional pre-event contacts."""
    required = {"mmsi", "port_complex_id", "start"}
    if missing := required - set(episodes.columns):
        raise ValueError(f"episodes missing columns: {sorted(missing)}")
    rows = episodes.copy()
    rows["start"] = pd.to_datetime(rows.start, errors="coerce", utc=True)
    rows = rows.dropna(subset=list(required)).sort_values(["mmsi", "start"], kind="stable")
    rows["previous_port"] = rows.groupby("mmsi", sort=False).port_complex_id.shift()
    rows["previous_start"] = rows.groupby("mmsi", sort=False).start.shift()
    rows["gap_days"] = (rows.start - rows.previous_start).dt.total_seconds() / 86400
    receiver_set = set(receivers)
    transitions = rows.loc[
        rows.gap_days.between(0, max_days)
        & (
            (rows.previous_port.eq(baltimore) & rows.port_complex_id.isin(receiver_set))
            | (rows.port_complex_id.eq(baltimore) & rows.previous_port.isin(receiver_set))
        )
    ].copy()
    transitions["receiver"] = np.where(
        transitions.port_complex_id.eq(baltimore), transitions.previous_port, transitions.port_complex_id
    )
    counts = transitions.groupby("receiver").size().reindex(receivers, fill_value=0).rename("transitions")
    eligible = counts.loc[counts.ge(minimum)]
    if eligible.empty:
        raise ValueError("no receiver meets the frozen transition minimum")
    return eligible.rename_axis("port_complex_id").reset_index().assign(weight=lambda x: x.transitions / x.transitions.sum())


def triple_difference(panel: pd.DataFrame, weights: pd.DataFrame, *, event_year: int, design_years: list[int]) -> float:
    """Compute the registered receiver-weighted fleet×period×year contrast."""
    required = {"year", "port_complex_id", "linked", "post", "value", "fleet_size"}
    if missing := required - set(panel.columns):
        raise ValueError(f"DDD panel missing columns: {sorted(missing)}")
    rows = panel.copy()
    if (rows.fleet_size <= 0).any():
        raise ValueError("fleet_size must be positive")
    rows["rate"] = 100 * rows.value / rows.fleet_size
    means = rows.groupby(["year", "port_complex_id", "linked", "post"], as_index=False).rate.mean()
    wide = means.pivot(index=["year", "port_complex_id"], columns=["linked", "post"], values="rate")
    needed = {(False, False), (False, True), (True, False), (True, True)}
    if not needed.issubset(wide.columns):
        raise ValueError("DDD panel lacks a fleet-period cell")
    wide["fleet_did"] = (wide[True, True] - wide[True, False]) - (wide[False, True] - wide[False, False])
    contrasts = wide.fleet_did.unstack("year")
    contrasts["ddd"] = contrasts[event_year] - contrasts[design_years].mean(axis=1)
    merged = weights.set_index("port_complex_id").join(contrasts[["ddd"]], how="inner")
    if len(merged) != len(weights) or merged.ddd.isna().any():
        raise ValueError("DDD panel does not cover every weighted receiver")
    return float((merged.weight * merged.ddd).sum())


def randomization_p(observed: float, permuted: np.ndarray) -> float:
    values = np.asarray(permuted, dtype=float)
    if values.size == 0 or not np.isfinite(values).all() or not np.isfinite(observed):
        raise ValueError("randomization statistics must be finite and non-empty")
    return float((1 + np.count_nonzero(values >= observed)) / (1 + values.size))


if __name__ == "__main__":
    # This module is a LIBRARY of estimator primitives, not a runnable analysis. Before 2026-08-05 it
    # had no __main__ at all, so `python src/analysis/baltimore_infrastructure_shock.py` exited 0
    # having done nothing -- the worst possible failure mode, because a scripted verifier records the
    # zero exit code as success. It now exits non-zero and names the actual driver.
    import sys

    sys.exit(
        "baltimore_infrastructure_shock.py is a library of estimator primitives and computes nothing "
        "on its own.\n"
        "  Driver          : python src/analysis/run_baltimore_operational.py\n"
        "  Stored outputs  : results/confirmatory/baltimore_shock/{b_g1,b_g2,b_g2_audit}.json\n"
        "  Registration    : OSF uzxcv (2026-07-28); placebo correction OSF rpj42\n"
        "Note that tests/test_baltimore_infrastructure_shock.py exercises these primitives on "
        "synthetic fixtures only; it does not reproduce the registered DDD."
    )
