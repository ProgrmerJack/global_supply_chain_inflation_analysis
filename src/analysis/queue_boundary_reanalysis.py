"""Transparent post-outcome-known SPB queue-boundary spatial reanalysis."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "prereg/amendments/2026-07-28_spb_queue_boundary_reanalysis.md"
FREEZE = ROOT / "prereg/studies/spb_queue_boundary/spb_queue_boundary_reanalysis_freeze_receipt.json"
CORRECTION = ROOT / "prereg/amendments/2026-07-28_spb_queue_boundary_implementation_correction.md"
FAIL_CLOSED_CORRECTION = ROOT / "prereg/amendments/2026-07-28_spb_queue_boundary_fail_closed_reporting.md"
CACHE = ROOT / "data/external/gfw/spb_speed_bins"
OLD_GATE = ROOT / "results/deep_case_SPB/NS_G1_direct_measurement_gate.json"
PLAN = ROOT / "docs/nature_sustainability_recovery_plan_2026-07-23.md"
OUT = ROOT / "results/development/spb_queue_boundary_reanalysis"
CENTER = (33.72, -118.20)
SPEED_BINS = ("<2", "2-4", "4-6", "6-10", "10-15", "15-25", ">25")
MOVEMENT = ("10-15", "15-25", ">25")
SECTORS = ("west", "north", "south", "east")
RINGS = ("0-50nm", "50-150nm", "150-300nm")
SMOKE_EXCLUSION = pd.Timestamp("2021-12-01")
EVENT = pd.Timestamp("2021-11-16")
ANNOUNCEMENT = pd.Timestamp("2021-11-11")
MATURE_START = pd.Timestamp("2022-02-01")
FIXED_PLACEBOS = tuple(pd.Timestamp(f"{year}-11-16") for year in (2019, 2020, 2022))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_local_freeze() -> dict:
    """Fail closed on any artifact that can change the result.

    Amendment 2026-08-05 (prereg/amendments/2026-08-05_queue_boundary_governing_plan_repin.md):
    `governing_plan` is a NARRATIVE planning document. It is not read by this analysis and cannot
    alter any output, yet as a fail-closed pin an editorial touch to it permanently blocked
    regeneration of claims M04 and S02 while the code and data were provably unchanged. It is now
    RECORDED (hashed into the receipt, reported below) but not ENFORCED. The six artifacts that can
    determine the estimate remain enforced and unchanged. Freeze inputs are artifacts that can change
    a number; planning prose is provenance, not a gate.
    """
    receipt = json.loads(FREEZE.read_text(encoding="utf-8"))
    enforced = {
        "protocol": PROTOCOL,
        "analysis_executable": Path(__file__),
        "implementation_correction": CORRECTION,
        "fail_closed_reporting_correction": FAIL_CLOSED_CORRECTION,
        "gfw_manifest": CACHE / "manifest.csv",
        "immutable_ns_g1_decision": OLD_GATE,
    }
    for name, path in enforced.items():
        if receipt.get("sha256", {}).get(name) != sha256(path):
            raise RuntimeError(f"queue-boundary local freeze mismatch: {name}")
    recorded = sha256(PLAN)
    if receipt.get("sha256", {}).get("governing_plan") != recorded:
        print(f"  note: governing_plan hash differs from the receipt ({recorded[:16]}...); "
              "recorded, not enforced — see the 2026-08-05 amendment")
    if receipt.get("status") != "LOCALLY_FROZEN_POST_OUTCOME_KNOWN_REANALYSIS":
        raise RuntimeError("queue-boundary reanalysis is not locally frozen")
    return receipt


def _nm(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    radius_km = 6371.0088
    p1, p2 = np.radians(lat), np.radians(CENTER[0])
    dphi, dlon = np.radians(CENTER[0] - lat), np.radians(CENTER[1] - lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return radius_km * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1))) / 1.852


def _bearing(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    p1, p2 = np.radians(CENTER[0]), np.radians(lat)
    dlon = np.radians(lon - CENTER[1])
    y = np.sin(dlon) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dlon)
    return (np.degrees(np.arctan2(y, x)) + 360) % 360


def add_geometry(cells: pd.DataFrame) -> pd.DataFrame:
    out = cells.copy()
    distance = _nm(out["lat"].to_numpy(float), out["lon"].to_numpy(float))
    bearing = _bearing(out["lat"].to_numpy(float), out["lon"].to_numpy(float))
    out["distance_nm"] = distance
    out["ring"] = np.select(
        [distance <= 50, distance <= 150, distance <= 300], RINGS, default="beyond"
    )
    out["band"] = np.select(
        [(distance > 125) & (distance <= 150), (distance > 150) & (distance <= 175)],
        ["inner", "outer"],
        default="outside",
    )
    out["sector"] = np.select(
        [
            (bearing >= 225) & (bearing < 315),
            (bearing >= 315) | (bearing < 45),
            (bearing >= 135) & (bearing < 225),
        ],
        SECTORS[:3],
        default="east",
    )
    out["speed_group"] = np.select(
        [out["speed_bin"].eq("<2"), out["speed_bin"].isin(MOVEMENT)],
        ["low", "movement"],
        default="other",
    )
    return out


def supported_dates(manifest: pd.DataFrame) -> pd.DatetimeIndex:
    dates: set[pd.Timestamp] = set()
    for date_range in manifest["date_range"].drop_duplicates():
        start_text, end_text = str(date_range).split(",")
        dates.update(pd.date_range(start_text, pd.Timestamp(end_text) - pd.Timedelta(days=1), freq="D"))
    dates.discard(SMOKE_EXCLUSION)
    return pd.DatetimeIndex(sorted(dates))


def load_verified_cells() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    manifest = pd.read_csv(CACHE / "manifest.csv", dtype={"speed_bin": str})
    expected = {(year, speed) for year in range(2019, 2024) for speed in SPEED_BINS}
    observed = set(zip(manifest["year"].astype(int), manifest["speed_bin"].astype(str)))
    if observed != expected or manifest.duplicated(["year", "speed_bin"]).any():
        raise RuntimeError("GFW speed-bin manifest is incomplete or duplicated")
    if set(manifest["dataset_version"]) != {"public-global-presence:v4.0"}:
        raise RuntimeError("GFW speed-bin dataset version changed")
    frames = []
    for row in manifest.to_dict("records"):
        path = CACHE / row["artifact"]
        if not path.is_file() or sha256(path) != row["sha256"]:
            raise RuntimeError(f"GFW speed-bin artifact failed hash validation: {path.name}")
        frame = pd.read_parquet(path)
        if frame.isna().any().any() or frame.duplicated(["date", "lat", "lon"]).any():
            raise RuntimeError(f"GFW speed-bin artifact has missing or duplicate cells: {path.name}")
        frames.append(frame)
    cells = pd.concat(frames, ignore_index=True)
    cells["date"] = pd.to_datetime(cells["date"], errors="raise")
    support = supported_dates(manifest)
    if not cells["date"].isin(support).all() or any(date.day == 31 and date.month == 12 for date in support):
        raise RuntimeError("GFW cell dates do not obey the corrected half-open request support")
    old = json.loads(OLD_GATE.read_text(encoding="utf-8"))
    if old["gfw_bts_aggregate_operational_relevance"]["conditions"] != {
        "positive_association": True,
        "stronger_than_movement_control": True,
        "timing_within_one_observation": False,
    }:
        raise RuntimeError("immutable NS-G1 decision no longer has the audited component pattern")
    coverage = {
        "artifact_count": len(manifest),
        "row_count": len(cells),
        "presence_hours": float(cells["hours"].sum()),
        "support_days": len(support),
        "unsupported_year_end_dates_excluded": [f"{year}-12-31" for year in range(2019, 2024)],
        "smoke_test_date_excluded": str(SMOKE_EXCLUSION.date()),
        "all_hashes_valid": True,
        "manifest_sha256": sha256(CACHE / "manifest.csv"),
    }
    return cells, manifest, coverage


def _sector_area_km2(inner_nm: float, outer_nm: float) -> float:
    return (np.pi / 4) * (outer_nm ** 2 - inner_nm ** 2) * (1.852 ** 2)


def build_daily_panel(cells: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    cells = add_geometry(cells)
    dates = supported_dates(manifest)
    primary = cells[cells["speed_group"].isin(["low", "movement"])].copy()
    low4 = cells[cells["speed_bin"].isin(["<2", "2-4"])].copy()
    low4["speed_group"] = "low4"
    analysis_cells = pd.concat([primary, low4], ignore_index=True)
    groups = ("low", "low4", "movement")
    narrow = (analysis_cells[analysis_cells["band"].ne("outside") & analysis_cells["sector"].isin(SECTORS[:3])]
              .groupby(["date", "speed_group", "band", "sector"])["hours"].sum())
    narrow_index = pd.MultiIndex.from_product(
        [dates, groups, ("inner", "outer"), SECTORS[:3]],
        names=["date", "speed_group", "band", "sector"],
    )
    narrow = narrow.reindex(narrow_index, fill_value=0).rename("hours").reset_index()
    narrow_pivot = narrow.pivot_table(
        index="date", columns=["speed_group", "band", "sector"], values="hours", fill_value=0
    )
    daily = pd.DataFrame(index=dates)
    areas = {"inner": _sector_area_km2(125, 150), "outer": _sector_area_km2(150, 175)}
    for sector in SECTORS[:3]:
        for speed in groups:
            for band in ("inner", "outer"):
                hours = narrow_pivot[(speed, band, sector)].to_numpy(float)
                daily[f"{speed}_{band}_{sector}_hours"] = hours
                daily[f"{speed}_{band}_{sector}_density"] = hours / areas[band] * 10_000
        low_inner = daily[f"low_inner_{sector}_hours"]
        low_outer = daily[f"low_outer_{sector}_hours"]
        daily[f"low_outer_share_{sector}"] = low_outer / (low_inner + low_outer).replace(0, np.nan)
        daily[f"ddd_{sector}"] = (
            np.log1p(daily[f"low_outer_{sector}_density"])
            - np.log1p(daily[f"low_inner_{sector}_density"])
            - np.log1p(daily[f"movement_outer_{sector}_density"])
            + np.log1p(daily[f"movement_inner_{sector}_density"])
        )
        daily[f"ddd4_{sector}"] = (
            np.log1p(daily[f"low4_outer_{sector}_density"])
            - np.log1p(daily[f"low4_inner_{sector}_density"])
            - np.log1p(daily[f"movement_outer_{sector}_density"])
            + np.log1p(daily[f"movement_inner_{sector}_density"])
        )

    broad = (analysis_cells[analysis_cells["ring"].isin(RINGS)]
             .groupby(["date", "speed_group", "ring"])["hours"].sum())
    broad_index = pd.MultiIndex.from_product(
        [dates, groups, RINGS], names=["date", "speed_group", "ring"]
    )
    broad = broad.reindex(broad_index, fill_value=0).rename("hours").reset_index()
    broad_pivot = broad.pivot_table(
        index="date", columns=["speed_group", "ring"], values="hours", fill_value=0
    )
    for speed in groups:
        for ring in RINGS:
            daily[f"{speed}_{ring}"] = broad_pivot[(speed, ring)].to_numpy(float)
        daily[f"{speed}_total_0_300"] = daily[[f"{speed}_{ring}" for ring in RINGS]].sum(axis=1)
    daily["low_offshore_share"] = (
        daily["low_50-150nm"] + daily["low_150-300nm"]
    ) / daily["low_total_0_300"].replace(0, np.nan)
    values = daily.to_numpy(float)
    if np.isinf(values).any() or daily.filter(like="hours").lt(0).any().any():
        raise RuntimeError("daily queue-boundary panel has invalid values")
    return daily.reset_index(names="date")


def build_weekly_speed_composition(cells: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    cells = add_geometry(cells)
    dates = supported_dates(manifest)
    grouped = (cells[cells["ring"].isin(RINGS)]
               .groupby(["date", "speed_bin", "ring"])["hours"].sum())
    index = pd.MultiIndex.from_product(
        [dates, SPEED_BINS, RINGS], names=["date", "speed_bin", "ring"]
    )
    daily = grouped.reindex(index, fill_value=0).rename("hours").reset_index()
    daily["week_start"] = daily["date"] - pd.to_timedelta(daily["date"].dt.weekday, unit="D")
    weekly = (daily.groupby(["week_start", "speed_bin", "ring"], as_index=False)
              .agg(mean_daily_hours=("hours", "mean"), days_included=("date", "size")))
    return weekly


def build_weekly_panel(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    frame["week_start"] = frame["date"] - pd.to_timedelta(frame["date"].dt.weekday, unit="D")
    nonlinear = {
        "low_offshore_share",
        *(f"low_outer_share_{sector}" for sector in SECTORS[:3]),
        *(f"ddd_{sector}" for sector in SECTORS[:3]),
        *(f"ddd4_{sector}" for sector in SECTORS[:3]),
    }
    value_columns = [
        column for column in frame if column not in {"date", "week_start"} | nonlinear
    ]
    weekly = frame.groupby("week_start", as_index=False).agg(
        **{column: (column, "mean") for column in value_columns}, days_included=("date", "size")
    )
    for sector in SECTORS[:3]:
        low_inner = weekly[f"low_inner_{sector}_hours"]
        low_outer = weekly[f"low_outer_{sector}_hours"]
        weekly[f"low_outer_share_{sector}"] = low_outer / (low_inner + low_outer).replace(0, np.nan)
        weekly[f"ddd_{sector}"] = (
            np.log1p(weekly[f"low_outer_{sector}_density"])
            - np.log1p(weekly[f"low_inner_{sector}_density"])
            - np.log1p(weekly[f"movement_outer_{sector}_density"])
            + np.log1p(weekly[f"movement_inner_{sector}_density"])
        )
        weekly[f"ddd4_{sector}"] = (
            np.log1p(weekly[f"low4_outer_{sector}_density"])
            - np.log1p(weekly[f"low4_inner_{sector}_density"])
            - np.log1p(weekly[f"movement_outer_{sector}_density"])
            + np.log1p(weekly[f"movement_inner_{sector}_density"])
        )
    weekly["low_offshore_share"] = (
        weekly["low_50-150nm"] + weekly["low_150-300nm"]
    ) / weekly["low_total_0_300"].replace(0, np.nan)
    return weekly


def _phase_rows(weekly: pd.DataFrame, event: pd.Timestamp, *, window_weeks: int = 52) -> pd.DataFrame:
    mature_start = event + (MATURE_START - EVENT)
    anticipation_start = event - (EVENT - ANNOUNCEMENT)
    anticipation_week = anticipation_start - pd.Timedelta(days=anticipation_start.weekday())
    pre_end = anticipation_week - pd.Timedelta(weeks=1)
    pre_start = pre_end - pd.Timedelta(weeks=window_weeks - 1)
    mature_week = mature_start + pd.Timedelta(days=(-mature_start.weekday()) % 7)
    post_end = event + pd.Timedelta(weeks=window_weeks)
    pre = weekly[weekly["week_start"].between(pre_start, pre_end)].copy()
    post = weekly[weekly["week_start"].between(mature_week, post_end)].copy()
    pre["post"], post["post"] = 0.0, 1.0
    return pd.concat([pre, post], ignore_index=True)


def fit_level_shift(
    weekly: pd.DataFrame,
    outcome: str,
    event: pd.Timestamp = EVENT,
    *,
    window_weeks: int = 52,
    min_weeks: int = 39,
) -> dict:
    data = _phase_rows(
        weekly[weekly["days_included"].eq(7)], event, window_weeks=window_weeks
    ).dropna(subset=[outcome]).copy()
    n_pre, n_post = int((data["post"] == 0).sum()), int((data["post"] == 1).sum())
    if min(n_pre, n_post) < min_weeks:
        raise ValueError(f"level-shift model requires at least {min_weeks} complete weeks in each phase")
    week = (data["week_start"] - event).dt.days.to_numpy(float) / 7
    post_time = np.where(data["post"].to_numpy() == 1, week - week[data["post"].to_numpy() == 1].min(), 0)
    design = pd.DataFrame({
        "const": 1.0,
        "trend": week / 52,
        "post": data["post"].to_numpy(float),
        "post_trend": post_time / 52,
    })
    day = data["week_start"].dt.dayofyear.to_numpy(float)
    for harmonic in (1, 2):
        angle = 2 * np.pi * harmonic * day / 365.25
        design[f"sin{harmonic}"] = np.sin(angle)
        design[f"cos{harmonic}"] = np.cos(angle)
    result = sm.OLS(data[outcome].to_numpy(float), design).fit(
        cov_type="HAC", cov_kwds={"maxlags": 8}
    )
    beta, se = float(result.params["post"]), float(result.bse["post"])
    return {
        "outcome": outcome,
        "event": str(event.date()),
        "estimate": beta,
        "standard_error": se,
        "ci_low": beta - 1.959963984540054 * se,
        "ci_high": beta + 1.959963984540054 * se,
        "p_value": float(result.pvalues["post"]),
        "n_pre_weeks": n_pre,
        "n_mature_weeks": n_post,
        "window_weeks": window_weeks,
    }


def fit_or_unestimable(weekly: pd.DataFrame, outcome: str, event: pd.Timestamp = EVENT) -> dict:
    try:
        return {**fit_level_shift(weekly, outcome, event), "estimable": True}
    except ValueError as error:
        data = _phase_rows(weekly[weekly["days_included"].eq(7)], event).dropna(subset=[outcome])
        return {
            "outcome": outcome,
            "event": str(event.date()),
            "estimate": None,
            "standard_error": None,
            "ci_low": None,
            "ci_high": None,
            "p_value": None,
            "n_pre_weeks": int((data["post"] == 0).sum()),
            "n_mature_weeks": int((data["post"] == 1).sum()),
            "window_weeks": 52,
            "estimable": False,
            "reason": str(error),
        }


def moving_block_mean_difference(
    pre: np.ndarray, post: np.ndarray, *, draws: int = 10_000, block: int = 8, seed: int = 20260728
) -> dict:
    pre, post = np.asarray(pre, float), np.asarray(post, float)
    if min(len(pre), len(post)) < block:
        raise ValueError("moving-block mean difference has insufficient observations")
    rng = np.random.default_rng(seed)

    def sample(values: np.ndarray) -> float:
        starts = np.arange(len(values) - block + 1)
        chosen = rng.choice(starts, size=int(np.ceil(len(values) / block)), replace=True)
        index = np.concatenate([np.arange(start, start + block) for start in chosen])[:len(values)]
        return float(values[index].mean())

    observed = float(post.mean() - pre.mean())
    samples = np.fromiter((sample(post) - sample(pre) for _ in range(draws)), float, count=draws)
    low, high = np.quantile(samples, [0.025, 0.975])
    return {"estimate": observed, "ci_low": float(low), "ci_high": float(high),
            "draws": draws, "block_weeks": block}


def _raw_period_change(weekly: pd.DataFrame, outcome: str) -> dict:
    data = _phase_rows(weekly[weekly["days_included"].eq(7)], EVENT)
    return moving_block_mean_difference(
        data.loc[data["post"].eq(0), outcome].dropna().to_numpy(float),
        data.loc[data["post"].eq(1), outcome].dropna().to_numpy(float),
    )


def _raw_period_change_with_block(weekly: pd.DataFrame, outcome: str, block: int) -> dict:
    data = _phase_rows(weekly[weekly["days_included"].eq(7)], EVENT)
    return moving_block_mean_difference(
        data.loc[data["post"].eq(0), outcome].dropna().to_numpy(float),
        data.loc[data["post"].eq(1), outcome].dropna().to_numpy(float),
        block=block,
    )


def _holm(rows: list[dict]) -> list[dict]:
    order = sorted(range(len(rows)), key=lambda index: rows[index]["p_value"])
    adjusted = [1.0] * len(rows)
    running = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, (len(rows) - rank) * rows[index]["p_value"])
        running = max(running, value)
        adjusted[index] = running
    return [{**row, "holm_p_value": adjusted[index]} for index, row in enumerate(rows)]


def date_randomization(weekly: pd.DataFrame, actual: dict) -> tuple[dict, pd.DataFrame]:
    candidates = pd.date_range("2019-11-19", "2022-11-15", freq="4W-TUE")
    rows = []
    for event in candidates:
        if abs((event - EVENT).days) <= 182:
            continue
        try:
            rows.append(fit_level_shift(weekly, "ddd_west", event))
        except ValueError:
            continue
    table = pd.DataFrame(rows)
    p_value = float((1 + (table["estimate"].abs() >= abs(actual["estimate"])).sum()) / (1 + len(table)))
    return {"candidate_count": len(table), "two_sided_rank_p_value": p_value}, table


def evaluate_gate(weekly: pd.DataFrame, coverage: dict) -> tuple[dict, dict[str, pd.DataFrame]]:
    actual_ddd = fit_level_shift(weekly, "ddd_west")
    actual_share = fit_or_unestimable(weekly, "low_outer_share_west")
    near = _raw_period_change(weekly, "low_0-50nm")
    far = _raw_period_change(weekly, "low_150-300nm")
    total = _raw_period_change(weekly, "low_total_0_300")
    rotated = pd.DataFrame([fit_level_shift(weekly, f"ddd_{sector}") for sector in ("north", "south")])
    fixed = _holm([fit_level_shift(weekly, "ddd_west", event) for event in FIXED_PLACEBOS])
    fixed_table = pd.DataFrame(fixed)
    randomization, random_table = date_randomization(weekly, actual_ddd)
    sensitivity_rows = [
        {**fit_level_shift(weekly, "ddd_west", window_weeks=26, min_weeks=12), "sensitivity": "ddd_26_week"},
        {**fit_level_shift(weekly, "ddd_west", window_weeks=78, min_weeks=39), "sensitivity": "ddd_78_week"},
        {**fit_level_shift(weekly, "ddd4_west"), "sensitivity": "low_under_4_knots"},
    ]
    for block in (4, 12):
        for outcome in ("low_0-50nm", "low_150-300nm"):
            sensitivity_rows.append({
                **_raw_period_change_with_block(weekly, outcome, block),
                "outcome": outcome,
                "sensitivity": f"block_{block}_weeks",
            })
    sensitivity_table = pd.DataFrame(sensitivity_rows)
    false_fixed = fixed_table[
        (fixed_table["estimate"] > 0)
        & (fixed_table["holm_p_value"] < 0.05)
        & (fixed_table["estimate"].abs() >= abs(actual_ddd["estimate"]))
    ]
    conditions = {
        "source_and_support_valid": bool(coverage["artifact_count"] == 35 and coverage["all_hashes_valid"]),
        "positive_speed_specific_boundary_effect": bool(actual_ddd["ci_low"] > 0),
        "positive_low_speed_outer_share_effect": bool(
            actual_share["estimable"] and actual_share["ci_low"] > 0
        ),
        "near_decline_and_far_increase": bool(near["ci_high"] < 0 and far["ci_low"] > 0),
        "date_randomization_rank": bool(randomization["two_sided_rank_p_value"] <= 0.10),
        "no_equally_large_same_signed_fixed_placebo": bool(false_fixed.empty),
    }
    decision = {
        "study": "San Pedro Bay queue-boundary spatial reanalysis",
        "evidence_status": "post_outcome_known_public_data_reanalysis",
        "run_once_at_utc": datetime.now(UTC).isoformat(),
        "coverage": coverage,
        "primary_ddd": actual_ddd,
        "primary_low_speed_outer_share": actual_share,
        "broad_absolute_changes": {"near_0_50nm": near, "far_150_300nm": far, "total_0_300nm": total},
        "date_randomization": randomization,
        "sensitivity_summary": sensitivity_table.to_dict("records"),
        "conditions": conditions,
        "component_status": "pass" if all(conditions.values()) else "fail",
        "queue_reform_causal_claim_authorized": bool(all(conditions.values())),
        "individual_waiting_claim_authorized": False,
        "emissions_or_exposure_claim_authorized": False,
        "claim_boundary": (
            "At most low-speed cargo-presence redistribution around a radial policy-boundary proxy; "
            "not individual waiting, container-only activity, legal compliance, emissions, exposure, or mass balance."
        ),
    }
    return decision, {
        "fixed_placebos": fixed_table,
        "date_placebos": random_table,
        "rotated_sectors": rotated,
        "sensitivities": sensitivity_table,
    }


def verify() -> dict:
    """Recompute the registered estimate from the frozen inputs and compare, WITHOUT firing the gate.

    Added 2026-08-05. The one-shot rule protects the registered decision from being re-rolled, but it
    also meant the only available check on the stored numbers was re-hashing the file that contains
    them — which proves the file has not been edited and nothing about whether the number is right.
    This path re-executes the identical pipeline on the identical frozen inputs and compares the
    recomputed decision with the stored one. It writes nothing and cannot alter any outcome.

    Run: python src/analysis/queue_boundary_reanalysis.py --verify
    """
    require_local_freeze()
    decision_path = OUT / "decision.json"
    if not decision_path.exists():
        raise RuntimeError("nothing to verify: the reanalysis has not been run")
    stored = json.loads(decision_path.read_text(encoding="utf-8"))

    cells, manifest, coverage = load_verified_cells()
    daily = build_daily_panel(cells, manifest)
    weekly = build_weekly_panel(daily)
    recomputed, _ = evaluate_gate(weekly, coverage)

    def _flat(d, prefix=""):
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out.update(_flat(v, f"{prefix}{k}."))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{prefix}{k}"] = float(v)
        return out

    a, b = _flat(stored), _flat(recomputed)
    shared = sorted(set(a) & set(b))
    diffs = [(k, a[k], b[k]) for k in shared if abs(a[k] - b[k]) > 1e-9]
    print(f"=== queue-boundary read-only verification ===")
    print(f"  compared {len(shared)} numeric fields against the stored decision")
    for k in ("primary.estimate", "primary.p_value", "date_rank_p"):
        if k in a:
            print(f"    {k:24s} stored {a[k]:.6f}   recomputed {b.get(k, float('nan')):.6f}")
    if diffs:
        for k, x, y in diffs[:10]:
            print(f"  MISMATCH {k}: stored {x!r} recomputed {y!r}")
        raise RuntimeError(f"{len(diffs)} field(s) do not reproduce from the frozen inputs")
    print(f"  PASS: every numeric field reproduces exactly. The stored decision is recomputable,")
    print(f"        not merely hash-intact. Gate NOT refired; nothing written.")
    return recomputed


def run() -> dict:
    require_local_freeze()
    decision_path = OUT / "decision.json"
    if decision_path.exists():
        raise RuntimeError("queue-boundary reanalysis has already fired")
    cells, manifest, coverage = load_verified_cells()
    daily = build_daily_panel(cells, manifest)
    weekly = build_weekly_panel(daily)
    speed_composition = build_weekly_speed_composition(cells, manifest)
    decision, tables = evaluate_gate(weekly, coverage)
    OUT.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(OUT / "daily_physical_panel.parquet", index=False)
    weekly.to_csv(OUT / "weekly_physical_panel.csv", index=False, lineterminator="\n")
    speed_composition.to_csv(OUT / "weekly_speed_composition.csv", index=False, lineterminator="\n")
    (OUT / "data_quality.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name, table in tables.items():
        table.to_csv(OUT / f"{name}.csv", index=False, lineterminator="\n")
    decision_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    share = decision["primary_low_speed_outer_share"]
    share_text = (
        f"{100 * share['estimate']:.2f} percentage points "
        f"(95% CI {100 * share['ci_low']:.2f} to {100 * share['ci_high']:.2f})"
        if share["estimable"]
        else f"UNESTIMABLE ({share['n_pre_weeks']} pre and {share['n_mature_weeks']} mature weeks; {share['reason']})"
    )
    report = f"""# San Pedro Bay queue-boundary spatial reanalysis

**Evidence status:** post-outcome-known public-data reanalysis  
**Component decision:** {decision['component_status'].upper()}

This result does not alter the failed registered NS-G1 decision. It evaluates direct low-speed cargo presence,
not individual waiting or container-only activity.

## Primary estimates

- Speed-specific west-boundary triple difference: {decision['primary_ddd']['estimate']:.3f}
  (95% CI {decision['primary_ddd']['ci_low']:.3f} to {decision['primary_ddd']['ci_high']:.3f}).
- West low-speed outer-share change: {share_text}.
- Date-randomization rank p: {decision['date_randomization']['two_sided_rank_p_value']:.3f}
  across {decision['date_randomization']['candidate_count']} admissible dates.

## Absolute accounting

- 0–50 nmi: {decision['broad_absolute_changes']['near_0_50nm']['estimate']:+.2f} mean daily vessel-hours
  (block-bootstrap 95% CI {decision['broad_absolute_changes']['near_0_50nm']['ci_low']:+.2f} to
  {decision['broad_absolute_changes']['near_0_50nm']['ci_high']:+.2f}).
- 150–300 nmi: {decision['broad_absolute_changes']['far_150_300nm']['estimate']:+.2f}
  (95% CI {decision['broad_absolute_changes']['far_150_300nm']['ci_low']:+.2f} to
  {decision['broad_absolute_changes']['far_150_300nm']['ci_high']:+.2f}).
- Total 0–300 nmi: {decision['broad_absolute_changes']['total_0_300nm']['estimate']:+.2f}
  (95% CI {decision['broad_absolute_changes']['total_0_300nm']['ci_low']:+.2f} to
  {decision['broad_absolute_changes']['total_0_300nm']['ci_high']:+.2f}).

## Gate

""" + "\n".join(
        f"- {name.replace('_', ' ')}: **{'PASS' if value else 'FAIL'}**"
        for name, value in decision["conditions"].items()
    ) + f"""

**Permitted claim:** {decision['claim_boundary']}
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    return decision


if __name__ == "__main__":
    import sys

    if "--verify" in sys.argv:
        verify()
    else:
        result = run()
        print(json.dumps({"component_status": result["component_status"],
                          "conditions": result["conditions"]}, indent=2))
