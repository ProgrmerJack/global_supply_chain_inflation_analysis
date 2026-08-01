"""Prospective 2014-2015 SPB physical congestion replication."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from acquire import gfw  # noqa: E402
from analysis import h1_offshore_cargo as h1  # noqa: E402

TITLE = "San Pedro Bay 2014-2015 disruption spatial-mechanism replication"
REGISTRATION_TITLE = f"Correction: {TITLE}"
PROTOCOL = ROOT / "prereg/amendments/2026-07-23_spb_labour_spatial_replication_correction.md"
FREEZE = ROOT / "prereg/studies/spb_labour/spb_labour_spatial_replication_correction_freeze_receipt.json"
EXTERNAL = ROOT / "prereg/studies/spb_labour/spb_labour_spatial_replication_correction_external_timestamp.json"
CACHE = ROOT / "data/external/gfw/spb_labour_speed_bins"
OUT = ROOT / "results/confirmatory/spb_labour_spatial_replication_corrected"
EVENT = (pd.Timestamp("2014-07-01"), pd.Timestamp("2015-02-20"))
RECOVERY = (pd.Timestamp("2015-02-21"), pd.Timestamp("2015-12-31"))
ANTICIPATION = (pd.Timestamp("2014-05-01"), pd.Timestamp("2014-06-30"))
PLACEBOS = ((pd.Timestamp("2012-07-01"), pd.Timestamp("2013-02-20")),
            (pd.Timestamp("2013-07-01"), pd.Timestamp("2014-02-20")))
RINGS = ("0-50nm", "50-150nm", "150-300nm")
SECTORS = ("west", "north", "south", "east")
MOVEMENT = ("10-15", "15-25", ">25")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_registration(*, get_attributes=None) -> dict:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    receipt = json.loads(EXTERNAL.read_text(encoding="utf-8"))
    if freeze["sha256"]["protocol"] != sha256(PROTOCOL):
        raise RuntimeError("labour-replication protocol changed after freeze")
    if freeze["sha256"]["analysis_executable"] != sha256(Path(__file__)):
        raise RuntimeError("labour-replication executable changed after freeze")
    if receipt.get("status") != "EXTERNALLY_TIMESTAMPED":
        raise RuntimeError("labour-replication design is not externally timestamped")
    if receipt.get("local_freeze_receipt_sha256") != sha256(FREEZE):
        raise RuntimeError("external timestamp does not bind the labour-replication freeze")
    registration_id = receipt["registration_id"]
    if get_attributes is None:
        def get_attributes(value: str) -> dict:
            with urllib.request.urlopen(
                f"https://api.osf.io/v2/registrations/{value}/", timeout=30
            ) as response:
                return json.load(response)["data"]["attributes"]
    attributes = get_attributes(registration_id)
    if (attributes.get("title") != REGISTRATION_TITLE or not attributes.get("public")
            or attributes.get("revision_state") != "approved" or attributes.get("withdrawn")):
        raise RuntimeError("OSF does not report the approved public labour-replication registration")
    return receipt


def acquire() -> pd.DataFrame:
    return gfw.acquire_spb_speed_bins(
        CACHE, years=range(2012, 2016), verify=require_registration
    )


def build_daily_panel(cells: pd.DataFrame) -> pd.DataFrame:
    """Aggregate verified cells without losing hours through index-label coercion."""
    distance = h1._nm(cells["lat"].to_numpy(), cells["lon"].to_numpy())
    cells["ring"] = np.select(
        [distance <= 50, distance <= 150, distance <= 300], RINGS, default="beyond"
    )
    bearing = h1._bearing(cells["lat"].to_numpy(), cells["lon"].to_numpy())
    cells["sector"] = np.select(
        [(bearing >= 225) & (bearing < 315), (bearing >= 315) | (bearing < 45),
         (bearing >= 135) & (bearing < 225)], SECTORS[:3], default="east"
    )
    grouped = (cells.loc[cells["ring"].ne("beyond")]
               .groupby(["date", "speed_bin", "ring", "sector"])["hours"].sum())
    dates = pd.date_range("2012-01-01", "2015-12-31", freq="D").strftime("%Y-%m-%d")
    index = pd.MultiIndex.from_product(
        [dates, gfw.SPEED_BINS, RINGS, SECTORS],
        names=["date", "speed_bin", "ring", "sector"],
    )
    complete = grouped.reindex(index, fill_value=0).rename("hours").reset_index()
    pivot = complete.pivot_table(
        index="date", columns=["speed_bin", "ring", "sector"], values="hours", fill_value=0
    )
    pivot.index = pd.to_datetime(pivot.index, errors="raise")
    daily = pd.DataFrame(index=pivot.index)
    for ring in RINGS:
        daily[f"low_{ring}"] = sum(pivot[("<2", ring, sector)] for sector in SECTORS)
        daily[f"movement_{ring}"] = sum(
            pivot[(speed, ring, sector)] for speed in MOVEMENT for sector in SECTORS
        )
    daily["low_total_0_300"] = daily[[f"low_{ring}" for ring in RINGS]].sum(axis=1)
    daily["movement_total_0_300"] = daily[[f"movement_{ring}" for ring in RINGS]].sum(axis=1)
    for sector in SECTORS:
        daily[f"low_{sector}_0_300"] = sum(pivot[("<2", ring, sector)] for ring in RINGS)
    daily["low_north_south_mean_0_300"] = (
        daily["low_north_0_300"] + daily["low_south_0_300"]
    ) / 2
    daily = daily.reset_index(names="date")
    outcome_columns = [column for column in daily if column != "date"]
    values = daily[outcome_columns].to_numpy(float)
    in_ring_source_hours = float(cells.loc[cells["ring"].ne("beyond"), "hours"].sum())
    if not np.isfinite(values).all():
        raise RuntimeError("daily physical panel contains missing or non-finite outcomes")
    if in_ring_source_hours > 0 and float(daily["low_total_0_300"].sum()) <= 0:
        raise RuntimeError("positive in-ring source hours collapsed to zero during daily aggregation")
    return daily


def load_daily_panel() -> tuple[pd.DataFrame, dict]:
    require_registration()
    manifest = pd.read_csv(CACHE / "manifest.csv")
    expected = {(year, speed) for year in range(2012, 2016) for speed in gfw.SPEED_BINS}
    observed = set(zip(manifest["year"].astype(int), manifest["speed_bin"].astype(str)))
    hashes_valid = observed == expected and not manifest.duplicated(["year", "speed_bin"]).any()
    frames = []
    for row in manifest.to_dict("records"):
        path = CACHE / row["artifact"]
        hashes_valid &= path.is_file() and sha256(path) == row["sha256"]
        if path.is_file():
            frames.append(pd.read_parquet(path))
    if not hashes_valid:
        raise RuntimeError("labour-replication cache is incomplete, duplicated or hash-invalid")
    cells = pd.concat(frames, ignore_index=True)
    return build_daily_panel(cells), {
        "artifact_count": len(manifest),
        "rows": int(sum(manifest["rows"])),
        "presence_hours": float(sum(manifest["presence_hours"])),
        "manifest_sha256": sha256(CACHE / "manifest.csv"),
        "hashes_valid": bool(hashes_valid),
    }


def _design(dates: pd.Series) -> pd.DataFrame:
    day = (dates - pd.Timestamp("2012-01-01")).dt.days.to_numpy()
    design = pd.DataFrame({"const": 1.0, "trend": day / 365.25}, index=dates.index)
    for harmonic in (1, 2):
        angle = 2 * np.pi * harmonic * day / 365.25
        design[f"sin{harmonic}"] = np.sin(angle)
        design[f"cos{harmonic}"] = np.cos(angle)
    for index, (start, end) in enumerate(PLACEBOS, 1):
        design[f"placebo_{index}"] = dates.between(start, end).astype(float)
    design["disruption"] = dates.between(*EVENT).astype(float)
    design["recovery"] = dates.between(*RECOVERY).astype(float)
    return design


def fit_effect(daily: pd.DataFrame, outcome: pd.Series) -> tuple[object, pd.DataFrame]:
    keep = ~daily["date"].between(*ANTICIPATION)
    dates = daily.loc[keep, "date"].reset_index(drop=True)
    y = pd.Series(outcome.loc[keep].to_numpy(float), index=dates.index)
    result = sm.OLS(y, _design(dates)).fit(cov_type="HAC", cov_kwds={"maxlags": 28})
    rows = []
    for term in ("placebo_1", "placebo_2", "disruption", "recovery"):
        beta, se = float(result.params[term]), float(result.bse[term])
        rows.append({"term": term, "beta": beta, "standard_error": se,
                     "ci_low": beta - 1.959963984540054 * se,
                     "ci_high": beta + 1.959963984540054 * se,
                     "p_value": float(result.pvalues[term])})
    return result, pd.DataFrame(rows)


def _contrast(result, left: str, right: str) -> dict:
    vector = np.zeros(len(result.params))
    vector[result.model.exog_names.index(left)] = 1
    vector[result.model.exog_names.index(right)] = -1
    estimate = float(vector @ result.params)
    se = float(np.sqrt(vector @ result.cov_params() @ vector))
    return {"estimate": estimate, "standard_error": se,
            "ci_low": estimate - 1.959963984540054 * se,
            "ci_high": estimate + 1.959963984540054 * se}


def _baseline_z(daily: pd.DataFrame, column: str) -> pd.Series:
    transformed = np.log1p(daily[column].astype(float))
    baseline = transformed[daily["date"].lt(ANTICIPATION[0])]
    return (transformed - baseline.mean()) / baseline.std(ddof=1)


def run() -> dict:
    decision_path = OUT / "decision.json"
    if decision_path.exists():
        raise RuntimeError("labour-replication gate already fired")
    daily, coverage = load_daily_panel()
    primary_result, primary_terms = fit_effect(daily, np.log1p(daily["low_0-50nm"]))
    low_minus_movement = _baseline_z(daily, "low_0-50nm") - _baseline_z(daily, "movement_0-50nm")
    speed_result, speed_terms = fit_effect(daily, low_minus_movement)
    approach_minus_control = (
        _baseline_z(daily, "low_west_0_300")
        - _baseline_z(daily, "low_north_south_mean_0_300")
    )
    approach_result, approach_terms = fit_effect(daily, approach_minus_control)
    primary = primary_terms.set_index("term")
    conditions = {
        "positive_near_low_speed": bool(primary.loc["disruption", "ci_low"] > 0),
        "stronger_than_movement_control": bool(
            speed_terms.set_index("term").loc["disruption", "ci_low"] > 0
        ),
        "approach_specificity": bool(
            approach_terms.set_index("term").loc["disruption", "ci_low"] > 0
        ),
        "larger_than_fixed_placebos": bool(
            primary.loc["disruption", "beta"]
            > primary.loc[["placebo_1", "placebo_2"], "beta"].max()
        ),
        "recovery_below_disruption": bool(
            _contrast(primary_result, "disruption", "recovery")["ci_low"] > 0
        ),
        "complete_hash_valid_cache": bool(coverage["artifact_count"] == 28 and coverage["hashes_valid"]),
    }
    period_masks = {
        "fitting": daily["date"].between(pd.Timestamp("2012-01-01"), pd.Timestamp("2014-04-30")),
        "disruption": daily["date"].between(*EVENT),
        "recovery": daily["date"].between(*RECOVERY),
    }
    summary_rows = []
    outcome_columns = [
        *(f"low_{ring}" for ring in RINGS), "low_total_0_300",
        *(f"movement_{ring}" for ring in RINGS), "movement_total_0_300",
        *(f"low_{sector}_0_300" for sector in SECTORS),
    ]
    for period, mask in period_masks.items():
        for column in outcome_columns:
            summary_rows.append({"period": period, "outcome": column,
                                 "days": int(mask.sum()), "mean_daily_hours": float(daily.loc[mask, column].mean()),
                                 "total_hours": float(daily.loc[mask, column].sum())})
    decision = {
        "study": TITLE,
        "registration": json.loads(EXTERNAL.read_text(encoding="utf-8"))["registration_url"],
        "correction_status": "registered_pipeline_correction_after_invalid_first_execution",
        "invalid_first_execution": "../spb_labour_spatial_replication/invalidation_receipt.json",
        "run_once_at_utc": datetime.now(UTC).isoformat(),
        "coverage": coverage,
        "primary_log1p_effects": primary_terms.to_dict("records"),
        "primary_percent_effect": float(100 * np.expm1(primary.loc["disruption", "beta"])),
        "speed_specificity_effects": speed_terms.to_dict("records"),
        "approach_specificity_effects": approach_terms.to_dict("records"),
        "disruption_minus_recovery": _contrast(primary_result, "disruption", "recovery"),
        "conditions": conditions,
        "component_status": "pass" if all(conditions.values()) else "fail",
        "ns_g7_passed": False,
        "claim_boundary": (
            "At most disruption-associated physical cargo-presence accumulation; not individual waiting, "
            "relocation, a policy effect, emissions, exposure, health, or standalone NS-G7 passage."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(OUT / "daily_physical_panel.csv", index=False, lineterminator="\n")
    pd.DataFrame(summary_rows).to_csv(OUT / "period_accounting.csv", index=False, lineterminator="\n")
    decision_path.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("acquire", "run"))
    args = parser.parse_args()
    result = acquire() if args.command == "acquire" else run()
    print(f"{args.command}: {len(result):,}" if isinstance(result, pd.DataFrame)
          else json.dumps({"component_status": result["component_status"],
                           "conditions": result["conditions"]}, indent=2))


if __name__ == "__main__":
    main()
