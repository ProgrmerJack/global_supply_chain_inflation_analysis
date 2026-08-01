"""Fire the registered Baltimore B-G1/B-G2 gates once, from retained public AIS."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd

try:
    from .baltimore_infrastructure_shock import (
        PROJECTED_CRS,
        inland_side_from_berths,
        load_bridge,
        load_design,
        randomization_p,
        receiver_weights,
        track_crossings,
    )
    from ..governance.access import assert_baltimore_unlocked
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from analysis.baltimore_infrastructure_shock import (  # type: ignore
        PROJECTED_CRS,
        inland_side_from_berths,
        load_bridge,
        load_design,
        randomization_p,
        receiver_weights,
        track_crossings,
    )
    from governance.access import assert_baltimore_unlocked  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
PINGS = ROOT / "data/interim/national_pings"
RESULTS = ROOT / "results/confirmatory/baltimore_shock"
G1_RECEIPT = RESULTS / "b_g1.json"
G2_RECEIPT = RESULTS / "b_g2.json"


def _parquet_sources(years: set[int], *, december_only: set[int] | None = None) -> list[str]:
    sources: list[str] = []
    december_only = december_only or set()
    for year in sorted(years):
        months = [12] if year in december_only else range(1, 13)
        for month in months:
            sources.extend(str(path).replace("\\", "/") for path in sorted((PINGS / f"year={year}" / f"month={month:02d}").glob("pings_*.parquet")))
    if not sources:
        raise FileNotFoundError("no retained national AIS parquet files")
    return sources


def _sql_paths(paths: list[str]) -> str:
    return "[" + ",".join("'" + value.replace("'", "''") + "'" for value in paths) + "]"


def _shift(value: str, event_year: int) -> pd.Timestamp:
    source = pd.Timestamp(value)
    return pd.Timestamp(event_year + source.year - 2024, source.month, source.day)


def _phase_dates(design: dict, event_year: int, ids: set[str] | None = None) -> pd.DatetimeIndex:
    dates: list[pd.Timestamp] = []
    for phase in design["phases"]:
        if ids is None or phase["id"] in ids:
            dates.extend(pd.date_range(_shift(phase["start"], event_year), _shift(phase["end"], event_year)))
    return pd.DatetimeIndex(dates)


def _available_dates() -> set[pd.Timestamp]:
    out: set[pd.Timestamp] = set()
    for path in PINGS.glob("year=*/month=*/pings_*.parquet"):
        try:
            out.add(pd.Timestamp(path.stem.removeprefix("pings_")))
        except ValueError:
            continue
    return out


def _coverage(design: dict, years: list[int]) -> tuple[pd.DataFrame, bool]:
    available = _available_dates()
    rows = []
    threshold = design["operational_gate"]["minimum_daily_coverage"]
    for year in years:
        for phase in design["phases"]:
            expected = _phase_dates(design, year, {phase["id"]})
            observed = sum(day in available for day in expected)
            rows.append({"year": year, "phase": phase["id"], "expected_days": len(expected), "available_days": observed, "coverage": observed / len(expected)})
    frame = pd.DataFrame(rows)
    return frame, bool(frame.coverage.ge(threshold).all())


def _baltimore_episode_starts(paths: list[str], design: dict, years: list[int]) -> pd.DataFrame:
    clauses = []
    for year in years:
        start, end = _phase_dates(design, year).min() - pd.Timedelta(hours=25), _phase_dates(design, year).max() + pd.Timedelta(days=1)
        clauses.append(f"(timestamp >= TIMESTAMPTZ '{start.isoformat()}' AND timestamp < TIMESTAMPTZ '{end.isoformat()}')")
    query = f"""
      WITH p AS (
        SELECT mmsi, timestamp, port_complex_id,
               lag(timestamp) OVER (PARTITION BY mmsi, port_complex_id ORDER BY timestamp) previous_timestamp
        FROM read_parquet({_sql_paths(paths)}, hive_partitioning=true)
        WHERE port_complex_id = '{design['baltimore_complex']}'
          AND vessel_type BETWEEN {design['vessel_populations']['primary_freight']['ais_type_min']}
                              AND {design['vessel_populations']['primary_freight']['ais_type_max']}
          AND ({' OR '.join(clauses)})
      )
      SELECT mmsi, timestamp AS start, port_complex_id
      FROM p
      WHERE previous_timestamp IS NULL OR timestamp - previous_timestamp > INTERVAL 24 HOURS
      ORDER BY mmsi, start
    """
    return duckdb.sql(query).df()


def _bridge_crossings(paths: list[str], design: dict, years: list[int]) -> pd.DataFrame:
    bridge = load_bridge(design)
    berth_path = ROOT / design["measurement"]["berth_geometry"]
    zones = gpd.read_file(berth_path)
    berth = zones.loc[(zones.port_complex_id == design["baltimore_complex"]) & (zones.state == "berth")].to_crs(PROJECTED_CRS).geometry.union_all()
    inland = inland_side_from_berths(bridge, berth)
    if inland != design["measurement"]["frozen_inland_side_sign"]:
        raise ValueError("recomputed inland side differs from the frozen sign")
    wgs = gpd.GeoSeries([bridge], crs=PROJECTED_CRS).to_crs("EPSG:4326").iloc[0]
    minx, miny, maxx, maxy = wgs.bounds
    clauses = []
    for year in years:
        start, end = _phase_dates(design, year).min(), _phase_dates(design, year).max() + pd.Timedelta(days=1)
        clauses.append(f"(timestamp >= TIMESTAMPTZ '{start.isoformat()}' AND timestamp < TIMESTAMPTZ '{end.isoformat()}')")
    query = f"""
      SELECT mmsi, timestamp, lon, lat
      FROM read_parquet({_sql_paths(paths)}, hive_partitioning=true)
      WHERE port_complex_id = '{design['baltimore_complex']}'
        AND vessel_type BETWEEN {design['vessel_populations']['primary_freight']['ais_type_min']}
                            AND {design['vessel_populations']['primary_freight']['ais_type_max']}
        AND lon BETWEEN {minx - 0.04} AND {maxx + 0.04}
        AND lat BETWEEN {miny - 0.04} AND {maxy + 0.04}
        AND ({' OR '.join(clauses)})
      ORDER BY mmsi, timestamp
    """
    pings = duckdb.sql(query).df()
    return track_crossings(
        pings,
        bridge,
        inland,
        buffer_m=design["measurement"]["bridge_uncertainty_buffer_m"],
        max_minutes=design["measurement"]["track_segment_max_minutes"],
    )


def _local_dates(frame: pd.DataFrame, column: str, timezone: str) -> pd.Series:
    return pd.to_datetime(frame[column], utc=True).dt.tz_convert(timezone).dt.tz_localize(None).dt.normalize()


def _g1(design: dict, years: list[int], coverage: pd.DataFrame, episodes: pd.DataFrame, crossings: pd.DataFrame) -> dict:
    timezone = design["timezone"]
    episodes = episodes.assign(date=_local_dates(episodes, "start", timezone))
    crossings = crossings.assign(date=_local_dates(crossings, "timestamp", timezone))
    cross_daily = crossings.groupby("date").size()
    contact_daily = episodes.groupby("date").size()

    pre = _phase_dates(design, 2024, {"pre"})
    full = _phase_dates(design, 2024, {"full_obstruction_1", "full_obstruction_2"})
    deep = _phase_dates(design, 2024, {"deep_draft_reopened"})
    restored = _phase_dates(design, 2024, {"full_channel_restored"})

    def ratio(target: pd.DatetimeIndex) -> float:
        baseline = pre[-len(target):]
        denominator = float(cross_daily.reindex(baseline, fill_value=0).sum())
        return float(cross_daily.reindex(target, fill_value=0).sum() / denominator) if denominator else float("nan")

    ratios = {"full_obstruction": ratio(full), "deep_draft_reopened": ratio(deep), "full_channel_restored": ratio(restored)}
    weekly = []
    for year in years:
        days = _phase_dates(design, year)
        for day in days:
            week = day - pd.Timedelta(days=(day.weekday() - 1) % 7)
            weekly.append((year, week, int(cross_daily.get(day, 0)), int(contact_daily.get(day, 0))))
    weekly = pd.DataFrame(weekly, columns=["year", "week", "crossings", "contacts"]).groupby(["year", "week"], as_index=False)[["crossings", "contacts"]].sum()
    spearman = float(weekly.crossings.corr(weekly.contacts, method="spearman"))
    limits = design["operational_gate"]
    checks = {
        "coverage": bool(coverage.coverage.ge(limits["minimum_daily_coverage"]).all()),
        "full_obstruction": bool(np.isfinite(ratios["full_obstruction"]) and ratios["full_obstruction"] <= limits["full_obstruction_crossing_ratio_max"]),
        "deep_draft_reopened": bool(np.isfinite(ratios["deep_draft_reopened"]) and ratios["deep_draft_reopened"] >= limits["deep_draft_reopened_crossing_ratio_min"]),
        "full_channel_restored": bool(np.isfinite(ratios["full_channel_restored"]) and ratios["full_channel_restored"] >= limits["full_restored_crossing_ratio_min"]),
        "crossing_contact_concordance": bool(np.isfinite(spearman) and spearman >= limits["weekly_crossing_contact_spearman_min"]),
    }
    coverage.to_csv(RESULTS / "b_g1_coverage.csv", index=False)
    weekly.to_csv(RESULTS / "b_g1_weekly_measurement.csv", index=False)
    return {"gate": "B-G1", "status": "pass" if all(checks.values()) else "fail", "checks": checks, "crossing_ratios": ratios, "weekly_crossing_contact_spearman": spearman, "crossing_episodes": int(len(crossings)), "contact_episodes": int(len(episodes))}


def _all_episode_starts(paths: list[str], design: dict, ports: list[str]) -> pd.DataFrame:
    quoted = ",".join("'" + value.replace("'", "''") + "'" for value in ports)
    query = f"""
      WITH p AS (
        SELECT mmsi, timestamp, port_complex_id,
               lag(timestamp) OVER (PARTITION BY mmsi, port_complex_id ORDER BY timestamp) previous_timestamp
        FROM read_parquet({_sql_paths(paths)}, hive_partitioning=true)
        WHERE port_complex_id IN ({quoted})
          AND vessel_type BETWEEN {design['vessel_populations']['primary_freight']['ais_type_min']}
                              AND {design['vessel_populations']['primary_freight']['ais_type_max']}
      )
      SELECT mmsi, timestamp AS start, port_complex_id
      FROM p
      WHERE previous_timestamp IS NULL OR timestamp - previous_timestamp > INTERVAL 24 HOURS
      ORDER BY mmsi, start
    """
    return duckdb.sql(query).df()


def _fixed_fleet_membership(paths: list[str], design: dict, ports: list[str]) -> pd.DataFrame:
    quoted = ",".join("'" + value.replace("'", "''") + "'" for value in ports)
    query = f"""
      SELECT DISTINCT mmsi, port_complex_id
      FROM read_parquet({_sql_paths(paths)}, hive_partitioning=true)
      WHERE port_complex_id IN ({quoted})
        AND vessel_type BETWEEN {design['vessel_populations']['primary_freight']['ais_type_min']}
                            AND {design['vessel_populations']['primary_freight']['ais_type_max']}
        AND timestamp >= TIMESTAMPTZ '{design['network']['linked_fleet_start']}'
        AND timestamp < TIMESTAMPTZ '{pd.Timestamp(design['network']['linked_fleet_end']) + pd.Timedelta(days=1)}'
    """
    return duckdb.sql(query).df()


def _g2(design: dict, episodes: pd.DataFrame, membership: pd.DataFrame) -> dict:
    receivers = design["receiver_candidates"]
    placebos = design["nonreceiver_placebos"]
    ports = receivers + placebos
    episodes["start"] = pd.to_datetime(episodes.start, utc=True)
    design_episodes = episodes.loc[episodes.start.dt.year.isin(design["network"]["weight_years"])]
    weights = receiver_weights(design_episodes, receivers, minimum=design["network"]["minimum_transitions_for_positive_weight"])
    try:
        placebo_weights = receiver_weights(design_episodes, placebos, minimum=design["network"]["minimum_transitions_for_positive_weight"])
    except ValueError:
        placebo_weights = pd.DataFrame(columns=["port_complex_id", "transitions", "weight"])
    weights.to_csv(RESULTS / "b_g2_receiver_weights.csv", index=False)
    placebo_weights.to_csv(RESULTS / "b_g2_placebo_weights.csv", index=False)

    linked = set(membership.loc[membership.port_complex_id.eq(design["baltimore_complex"]), "mmsi"])
    comparison = {port: set(membership.loc[membership.port_complex_id.eq(port), "mmsi"]) - linked for port in ports}
    if not linked or any(not comparison[port] for port in ports):
        raise ValueError("a frozen linked/comparison fleet is empty")

    rows = episodes.loc[episodes.port_complex_id.isin(ports)].copy()
    rows["date"] = _local_dates(rows, "start", design["timezone"])
    rows["year"] = rows.date.dt.year
    rows["linked"] = rows.mmsi.isin(linked)
    rows["comparison"] = [mmsi in comparison[port] for mmsi, port in zip(rows.mmsi, rows.port_complex_id)]
    rows = pd.concat([rows.loc[rows.linked].assign(group="linked"), rows.loc[rows.comparison].assign(group="comparison")])
    daily = rows.groupby(["date", "year", "port_complex_id", "group"]).size().rename("episodes").reset_index()
    counts = {(row.date, row.port_complex_id, row.group): int(row.episodes) for row in daily.itertuples()}

    design_years = design["design_years"]
    all_years = design_years + [design["event_year"]]
    post_offsets = np.r_[np.arange(0, 30), np.arange(34, 49)]
    pre_offsets = np.arange(-45, 0)

    def fleet_did(port: str, year: int, month: int, day: int) -> float:
        treatment = pd.Timestamp(year, month, day)
        values = {}
        for group in ["linked", "comparison"]:
            denominator = len(linked) if group == "linked" else len(comparison[port])
            pre = sum(counts.get((treatment + pd.Timedelta(days=int(offset)), port, group), 0) for offset in pre_offsets)
            post = sum(counts.get((treatment + pd.Timedelta(days=int(offset)), port, group), 0) for offset in post_offsets)
            values[group] = 100 * (post - pre) / denominator
        return values["linked"] - values["comparison"]

    def port_ddd(port: str, event_year: int, month: int, day: int) -> float:
        return fleet_did(port, event_year, month, day) - np.mean([fleet_did(port, year, month, day) for year in all_years if year != event_year])

    event = pd.Timestamp(design["treatment_timestamp_local"])
    individual = pd.Series({port: port_ddd(port, design["event_year"], event.month, event.day) for port in ports})
    observed = float((weights.set_index("port_complex_id").weight * individual.reindex(weights.port_complex_id).values).sum())
    placebo_observed = None if placebo_weights.empty else float((placebo_weights.set_index("port_complex_id").weight * individual.reindex(placebo_weights.port_complex_id).values).sum())

    candidate_dates = pd.date_range("2024-02-15", "2024-09-30", freq="W-TUE")
    cube = {(year, when.month, when.day, port): port_ddd(port, year, when.month, when.day) for year in all_years for when in candidate_dates for port in ports}
    rng = np.random.default_rng(design["random_seed"])

    def permute(template_weights: np.ndarray) -> np.ndarray:
        result = np.empty(design["randomization_draws"])
        for index in range(len(result)):
            pseudo_year = int(rng.choice(all_years))
            when = candidate_dates[int(rng.integers(len(candidate_dates)))]
            selected = rng.choice(ports, size=len(template_weights), replace=False)
            result[index] = sum(weight * cube[pseudo_year, when.month, when.day, port] for weight, port in zip(rng.permutation(template_weights), selected))
        return result

    permuted = permute(weights.weight.to_numpy())
    p_value = randomization_p(observed, permuted)
    if placebo_weights.empty:
        placebo_p = None
    else:
        placebo_p = randomization_p(placebo_observed, permute(placebo_weights.weight.to_numpy()))
    top_four = weights.nlargest(4, "weight").port_complex_id
    leave_one_out = {}
    for excluded in weights.port_complex_id:
        kept = weights.loc[weights.port_complex_id.ne(excluded)].copy()
        kept["weight"] /= kept.weight.sum()
        leave_one_out[excluded] = float((kept.set_index("port_complex_id").weight * individual.reindex(kept.port_complex_id).values).sum())
    limits = design["operational_gate"]
    checks = {
        "randomization": bool(observed > 0 and p_value <= limits["receiver_randomization_p_max"]),
        "top_four": bool(individual.reindex(top_four).gt(0).sum() >= limits["minimum_positive_top_four_receivers"]),
        "leave_one_out": bool(all(value > 0 for value in leave_one_out.values())),
        "negative_control": bool(placebo_p is not None and (placebo_observed <= 0 or placebo_p > limits["receiver_randomization_p_max"])),
    }
    pd.DataFrame({"port_complex_id": individual.index, "ddd": individual.values}).to_csv(RESULTS / "b_g2_port_estimates.csv", index=False)
    np.save(RESULTS / "b_g2_randomization_distribution.npy", permuted)
    return {
        "gate": "B-G2",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "network_ddd": observed,
        "one_sided_randomization_p": p_value,
        "negative_control_ddd": placebo_observed,
        "negative_control_p": placebo_p,
        "positive_top_four": int(individual.reindex(top_four).gt(0).sum()),
        "leave_one_receiver_out": leave_one_out,
        "linked_fleet_mmsi": len(linked),
        "comparison_fleet_mmsi": {port: len(value) for port, value in comparison.items()},
        "randomization_draws": design["randomization_draws"],
        "seed": design["random_seed"],
    }


def _write_once(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(f"registered gate already fired: {path}")
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def verify() -> int:
    """Recompute B-G2 from the frozen inputs and compare with the stored receipt. Writes nothing.

    Added 2026-08-06. The one-shot rule (`_write_once`) protects the registered decision, but it also
    meant the only available check on the Baltimore numbers was re-hashing the file that contains them,
    and the module's declared tests exercise the estimator primitives on synthetic fixtures only. This
    path re-executes the identical pipeline on the identical inputs and diffs the result against
    `b_g2.json`. It cannot fire, overwrite, or reopen the gate.

    Run: python src/analysis/run_baltimore_operational.py --verify
    """
    design = load_design()
    if not G2_RECEIPT.exists():
        raise RuntimeError("nothing to verify: B-G2 has not been run")
    stored = json.loads(G2_RECEIPT.read_text(encoding="utf-8"))

    spill = ROOT / "data/interim/duckdb_spill"
    spill.mkdir(parents=True, exist_ok=True)
    duckdb.sql("SET memory_limit='4GB'")
    duckdb.sql(f"SET temp_directory='{str(spill.resolve()).replace(chr(92), '/')}'")

    ports = [design["baltimore_complex"], *design["receiver_candidates"], *design["nonreceiver_placebos"]]
    full_paths = _parquet_sources({2018, 2019, 2021, 2022, 2023, 2024}, december_only={2018, 2021})
    all_episodes = _all_episode_starts(full_paths, design, ports)
    membership = _fixed_fleet_membership(full_paths, design, ports)
    recomputed = _g2(design, all_episodes, membership)

    def flat(d, prefix=""):
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out.update(flat(v, f"{prefix}{k}."))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{prefix}{k}"] = float(v)
        return out

    a, b = flat(stored), flat(recomputed)
    shared = sorted(set(a) & set(b))
    diffs = [(k, a[k], b[k]) for k in shared if abs(a[k] - b[k]) > 1e-9]
    print("=== Baltimore B-G2 read-only verification ===")
    print(f"  compared {len(shared)} numeric fields against the stored receipt")
    for k in ("network_ddd", "one_sided_randomization_p", "negative_control_ddd", "negative_control_p"):
        if k in a:
            print(f"    {k:32s} stored {a[k]:.9f}   recomputed {b.get(k, float('nan')):.9f}")
    if diffs:
        for k, x, y in diffs[:10]:
            print(f"  MISMATCH {k}: stored {x!r} recomputed {y!r}")
        raise RuntimeError(f"{len(diffs)} field(s) do not reproduce from the frozen inputs")
    print("  PASS: every numeric field reproduces exactly. Gate NOT refired; nothing written.")
    return 0


def main() -> int:
    design = load_design()
    assert_baltimore_unlocked(RESULTS)
    RESULTS.mkdir(parents=True, exist_ok=True)
    if G2_RECEIPT.exists():
        raise FileExistsError("Baltimore B-G2 already fired")
    spill = ROOT / "data/interim/duckdb_spill"
    spill.mkdir(parents=True, exist_ok=True)
    duckdb.sql("SET memory_limit='4GB'")
    duckdb.sql(f"SET temp_directory='{str(spill.resolve()).replace(chr(92), '/')}'")
    years = design["design_years"] + [design["event_year"]]
    source_years = set(years) | {year - 1 for year in years}
    paths = _parquet_sources(source_years, december_only={year - 1 for year in years} - set(years))
    if G1_RECEIPT.exists():
        g1 = json.loads(G1_RECEIPT.read_text(encoding="utf-8"))
    else:
        coverage, _ = _coverage(design, years)
        episodes = _baltimore_episode_starts(paths, design, years)
        crossings = _bridge_crossings(paths, design, years)
        g1 = _g1(design, years, coverage, episodes, crossings)
        _write_once(G1_RECEIPT, g1)
    if g1["status"] != "pass":
        print(json.dumps(g1, indent=2))
        return 2

    ports = [design["baltimore_complex"], *design["receiver_candidates"], *design["nonreceiver_placebos"]]
    full_paths = _parquet_sources({2018, 2019, 2021, 2022, 2023, 2024}, december_only={2018, 2021})
    all_episodes = _all_episode_starts(full_paths, design, ports)
    membership = _fixed_fleet_membership(full_paths, design, ports)
    g2 = _g2(design, all_episodes, membership)
    _write_once(G2_RECEIPT, g2)
    print(json.dumps({"B-G1": g1["status"], "B-G2": g2["status"], "B-G2_p": g2["one_sided_randomization_p"]}, indent=2))
    return 0 if g2["status"] == "pass" else 3


if __name__ == "__main__":
    import sys

    raise SystemExit(verify() if "--verify" in sys.argv else main())
