"""H1 rebuilt with CARGO-ONLY presence + ABSOLUTE vessel-hours across all rings (review Priority 3).

Fixes the earlier H1: (a) cargo-vessel filter (GFW `filters[0]=vessel_type='cargo'`, ~18% of all-vessel — now
MEASURED not assumed); (b) ABSOLUTE vessel-hours per ring (percent changes mislead when baselines differ);
(c) consistent measure across all rings (GFW cargo presence), so near and far are compared like-for-like.
CAVEAT (kept explicit): this cached H1 product was not speed-filtered, although the GFW API supports
categorical speed filters. It therefore measures cargo PRESENCE, not cargo WAITING; transiting cargo is
included, especially in 0-50 nm. A separately frozen speed-bin panel can measure low-speed presence, but low
speed still cannot be equated with individual operational waiting. Percent/ratio claims and "waiting relocated"
language are NOT made here.

Run: python src/analysis/h1_offshore_cargo.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/deep_case_SPB"
CACHE = ROOT / "data/external/gfw/spb_cargo_rings_by_month.csv"
SPEED_CACHE = ROOT / "data/external/gfw/spb_speed_bins"
BTS_QUEUE = ROOT / "data/external/bts_ops/weekly_ships_awaiting_berth.csv"
NATIONAL_ACTIVITY = ROOT / "data/processed/national_activity_month.csv"
OFFICIAL_CALLS = ROOT / "data/external/g1v2_official_annual/san_pedro_bay__container_vessel_calls__annual.csv"
TEU = ROOT / "data/external/g1v2_official/san_pedro_bay__container_teu_total.csv"
CENTER = (33.72, -118.20)
BOX = [-124.5, -112.0, 28.7, 38.7]
sys.path.insert(0, str(ROOT / "src/acquire"))
from gfw import SPEED_BINS, SMOKE_EXCLUSION, fetch_presence, require_spb_speed_registration


def _nm(lat, lon):
    R = 6371.0
    p1, p2 = np.radians(lat), np.radians(CENTER[0])
    dphi, dl = np.radians(CENTER[0] - lat), np.radians(CENTER[1] - lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a)) / 1.852


def _bearing(lat, lon):
    """Initial compass bearing from the frozen SPB reference point to cell centres."""
    p1, p2 = np.radians(CENTER[0]), np.radians(lat)
    dl = np.radians(lon - CENTER[1])
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(y, x)) + 360) % 360


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def speed_bin_daily_panel() -> pd.DataFrame:
    """Load only the registered, hash-verified GFW cache and assign frozen rings/sectors."""
    require_spb_speed_registration()
    manifest = pd.read_csv(SPEED_CACHE / "manifest.csv")
    expected = {(year, speed_bin) for year in range(2019, 2024) for speed_bin in SPEED_BINS}
    observed = set(zip(manifest["year"].astype(int), manifest["speed_bin"].astype(str)))
    if observed != expected or manifest.duplicated(["year", "speed_bin"]).any():
        raise RuntimeError("registered GFW speed-bin manifest is incomplete or duplicated")
    frames = []
    for row in manifest.to_dict("records"):
        path = SPEED_CACHE / row["artifact"]
        if not path.is_file() or _file_sha256(path) != row["sha256"]:
            raise RuntimeError(f"registered GFW speed-bin hash mismatch: {path.name}")
        frames.append(pd.read_parquet(path))
    cells = pd.concat(frames, ignore_index=True)
    if SMOKE_EXCLUSION in set(cells["date"]):
        raise RuntimeError("excluded GFW smoke-test date entered the analytic cache")
    distance = _nm(cells["lat"].to_numpy(), cells["lon"].to_numpy())
    cells["ring"] = np.select(
        [distance <= 50, distance <= 150, distance <= 300],
        ["0-50nm", "50-150nm", "150-300nm"],
        default="beyond",
    )
    bearing = _bearing(cells["lat"].to_numpy(), cells["lon"].to_numpy())
    cells["sector"] = np.select(
        [(bearing >= 225) & (bearing < 315), (bearing >= 315) | (bearing < 45),
         (bearing >= 135) & (bearing < 225)],
        ["west", "north", "south"],
        default="east",
    )
    return (cells.groupby(["date", "speed_bin", "ring", "sector"], as_index=False)
            .agg(hours=("hours", "sum"), vessel_positions=("vessel_positions", "sum")))


def _complete_daily_series(panel: pd.DataFrame) -> pd.DataFrame:
    """Make registered daily totals; absent rows in successful yearly reports are observed zeros."""
    inside = panel[panel["ring"] != "beyond"]
    grouped = inside.groupby(["date", "speed_bin", "ring"])["hours"].sum()
    dates = pd.date_range("2019-01-01", "2023-12-31", freq="D").strftime("%Y-%m-%d")
    dates = dates[dates != SMOKE_EXCLUSION]
    index = pd.MultiIndex.from_product(
        [dates, SPEED_BINS, ["0-50nm", "50-150nm", "150-300nm"]],
        names=["date", "speed_bin", "ring"],
    )
    daily = grouped.reindex(index, fill_value=0).rename("hours").reset_index()
    pivot = daily.pivot_table(index="date", columns=["speed_bin", "ring"], values="hours", fill_value=0)
    out = pd.DataFrame(index=pd.to_datetime(pivot.index, utc=True))
    for ring in ["0-50nm", "50-150nm", "150-300nm"]:
        out[f"low_{ring}"] = pivot[("<2", ring)].to_numpy()
    out["low_total_0_300"] = out[["low_0-50nm", "low_50-150nm", "low_150-300nm"]].sum(axis=1)
    movement = ["10-15", "15-25", ">25"]
    out["movement_total_0_300"] = sum(
        pivot[(speed_bin, ring)].to_numpy()
        for speed_bin in movement for ring in ["0-50nm", "50-150nm", "150-300nm"]
    )
    return out


def bts_weekly_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Align GFW mean daily hours to each official BTS observation's trailing seven UTC dates."""
    daily = _complete_daily_series(panel)
    queue = pd.read_csv(BTS_QUEUE)
    queue["date"] = pd.to_datetime(queue["date"], utc=True).dt.normalize()
    rows = []
    value_columns = list(daily.columns)
    for record in queue.to_dict("records"):
        end = record["date"]
        window = daily.loc[end - pd.Timedelta(days=6):end]
        row = {**record, "days_included": len(window)}
        row.update({column: float(window[column].mean()) if len(window) else np.nan
                    for column in value_columns})
        rows.append(row)
    return pd.DataFrame(rows)


def _correlation(x: np.ndarray, y: np.ndarray, method: str) -> float:
    if method == "spearman":
        x, y = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    return float(np.corrcoef(x, y)[0, 1])


def _moving_block_bootstrap(queue: np.ndarray, low: np.ndarray, movement: np.ndarray,
                            *, draws: int = 10000, block: int = 4, seed: int = 20260718) -> dict:
    rng = np.random.default_rng(seed)
    n = len(queue)
    starts = np.arange(n - block + 1)
    samples = {key: [] for key in ("low_pearson", "low_spearman", "diff_pearson", "diff_spearman")}
    for _ in range(draws):
        chosen = rng.choice(starts, size=int(np.ceil(n / block)), replace=True)
        index = np.concatenate([np.arange(start, start + block) for start in chosen])[:n]
        for method in ("pearson", "spearman"):
            low_r = _correlation(queue[index], low[index], method)
            movement_r = _correlation(queue[index], movement[index], method)
            samples[f"low_{method}"].append(low_r)
            samples[f"diff_{method}"].append(low_r - movement_r)
    return {key: [float(value) for value in np.quantile(values, [0.025, 0.975])]
            for key, values in samples.items()}


def _lag_table(weekly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lag in range(-8, 9):
        shifted = weekly["low_total_0_300"].shift(lag)
        keep = shifted.notna() & weekly["los_angeles_long_beach"].notna()
        for method in ("pearson", "spearman"):
            rows.append({
                "gfw_shift_observations": lag,
                "method": method,
                "correlation": _correlation(
                    weekly.loc[keep, "los_angeles_long_beach"].to_numpy(float),
                    shifted[keep].to_numpy(float),
                    method,
                ),
            })
    return pd.DataFrame(rows)


def evaluate_bts_gate(weekly: pd.DataFrame, *, draws: int = 10000) -> tuple[dict, pd.DataFrame]:
    """Apply the registered direction, timing and movement-specificity conditions."""
    columns = ["los_angeles_long_beach", "low_total_0_300", "movement_total_0_300"]
    complete = weekly.dropna(subset=columns)
    queue, low, movement = (complete[column].to_numpy(float) for column in columns)
    estimates = {
        "low_pearson": _correlation(queue, low, "pearson"),
        "low_spearman": _correlation(queue, low, "spearman"),
        "movement_pearson": _correlation(queue, movement, "pearson"),
        "movement_spearman": _correlation(queue, movement, "spearman"),
    }
    intervals = _moving_block_bootstrap(queue, low, movement, draws=draws)
    lags = _lag_table(complete)
    best_lags = {
        method: int(group.loc[group["correlation"].abs().idxmax(), "gfw_shift_observations"])
        for method, group in lags.groupby("method")
    }
    conditions = {
        "positive_association": all(intervals[f"low_{method}"][0] > 0 for method in ("pearson", "spearman")),
        "timing_within_one_observation": all(abs(best_lags[method]) <= 1 for method in ("pearson", "spearman")),
        "stronger_than_movement_control": all(intervals[f"diff_{method}"][0] > 0
                                                for method in ("pearson", "spearman")),
    }
    return {
        "n_bts_observations": len(complete),
        "estimates": estimates,
        "bootstrap_95_ci": intervals,
        "best_gfw_shift_observations": best_lags,
        "conditions": conditions,
        "status": "pass" if all(conditions.values()) else "fail",
        "conservative_implementation": "Both Pearson and Spearman must satisfy each ambiguous registered association clause.",
    }, lags


def annual_call_check() -> tuple[dict, pd.DataFrame]:
    """Report the frozen ±20% annual call-coverage check without rescuing a construct mismatch."""
    activity = pd.read_csv(NATIONAL_ACTIVITY)
    activity = activity[activity["port_complex_id"] == "san_pedro_bay"].copy()
    activity["year"] = activity["year_month"].str[:4].astype(int)
    ais = activity.groupby("year")["cargo_port_calls"].sum().rename("ais_cargo_calls")
    official = pd.read_csv(OFFICIAL_CALLS).set_index("year")["value"].rename("official_container_calls")
    table = pd.concat([ais, official], axis=1).dropna().loc[2020:2023].reset_index()
    table["coverage_ratio"] = table["ais_cargo_calls"] / table["official_container_calls"]
    table["pct_error"] = 100 * (table["coverage_ratio"] - 1)
    within = table["coverage_ratio"].between(0.8, 1.2)
    return {
        "status": "pass" if within.all() else "fail",
        "years_within_20pct": int(within.sum()),
        "years_tested": len(table),
        "median_coverage_ratio": float(table["coverage_ratio"].median()),
        "pearson_across_four_years": float(table["ais_cargo_calls"].corr(table["official_container_calls"])),
        "construct_note": "The current AIS product is cargo-class and port-area based, not container-terminal restricted; failure cannot be relabelled as container-call validation.",
    }, table


def run_direct_gate(*, draws: int = 10000) -> dict:
    """Open the registered aggregate outcomes once and write the component-separated NS-G1 decision."""
    OUT.mkdir(parents=True, exist_ok=True)
    panel = speed_bin_daily_panel()
    weekly = bts_weekly_panel(panel)
    bts_gate, lags = evaluate_bts_gate(weekly, draws=draws)
    call_gate, call_table = annual_call_check()
    geometry_provenance = json.loads((ROOT / "config/protocol/national_state_zone_provenance.json").read_text(encoding="utf-8"))
    decision = {
        "gate": "NS-G1 direct-observable San Pedro Bay components",
        "registration": "https://osf.io/5sc3v/",
        "run_once_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "gfw_bts_aggregate_operational_relevance": bts_gate,
        "annual_container_call_check": call_gate,
        "official_geometry": {
            "status": "pass",
            "eligible_complexes": len(geometry_provenance["eligible_port_complex_ids"]),
            "source_snapshot_sha256": geometry_provenance["source_snapshot"]["sha256"],
            "state_zones_sha256": geometry_provenance["artifacts"]["state_zones"]["sha256"],
        },
        "decision": {
            "full_ns_g1_pass": bts_gate["status"] == "pass" and call_gate["status"] == "pass",
            "gfw_spatial_policy_branch_authorized": bts_gate["status"] == "pass",
            "annual_call_claim_authorized": call_gate["status"] == "pass",
            "individual_waiting_or_anchor_berth_claim_authorized": False,
            "status": "pass" if bts_gate["status"] == "pass" and call_gate["status"] == "pass" else "component_failure",
        },
        "claim_boundary": "A passing GFW/BTS component validates aggregate operational relevance only; it does not validate individual waiting or semantic vessel state.",
    }
    weekly.to_csv(OUT / "NS_G1_direct_measurement_weekly.csv", index=False, lineterminator="\n")
    lags.to_csv(OUT / "NS_G1_direct_measurement_lags.csv", index=False, lineterminator="\n")
    call_table.to_csv(OUT / "NS_G1_direct_measurement_annual_calls.csv", index=False, lineterminator="\n")
    (OUT / "NS_G1_direct_measurement_gate.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    condition_lines = "\n".join(
        f"- {name.replace('_', ' ')}: **{'PASS' if value else 'FAIL'}**"
        for name, value in bts_gate["conditions"].items()
    )
    call_rows = "\n".join(
        f"| {int(row.year)} | {int(row.ais_cargo_calls):,} | {int(row.official_container_calls):,} | "
        f"{row.coverage_ratio:.2f} | {row.pct_error:+.1f}% |"
        for row in call_table.itertuples(index=False)
    )
    report = f"""# NS-G1 direct-measurement decision

**Registered protocol:** [OSF 5sc3v](https://osf.io/5sc3v/)  
**Aggregate GFW/BTS relevance:** {bts_gate['status'].upper()}  
**Annual container-call check:** {call_gate['status'].upper()}  
**Full NS-G1:** {'PASS' if decision['decision']['full_ns_g1_pass'] else 'NOT PASSED (component failure)'}

## Aggregate queue relevance

The primary series is mean daily `<2`-knot GFW cargo presence within 0–300 nautical miles over the trailing
seven dates ending at each of {bts_gate['n_bts_observations']} BTS observations. GFW cargo is broader than
container ships and the result is aggregate operational relevance, not individual waiting validation.

{condition_lines}

| Association | Estimate | 95% moving-block bootstrap CI |
| --- | ---: | ---: |
| Low-speed Pearson | {bts_gate['estimates']['low_pearson']:.3f} | [{bts_gate['bootstrap_95_ci']['low_pearson'][0]:.3f}, {bts_gate['bootstrap_95_ci']['low_pearson'][1]:.3f}] |
| Low-speed Spearman | {bts_gate['estimates']['low_spearman']:.3f} | [{bts_gate['bootstrap_95_ci']['low_spearman'][0]:.3f}, {bts_gate['bootstrap_95_ci']['low_spearman'][1]:.3f}] |
| Movement-control Pearson | {bts_gate['estimates']['movement_pearson']:.3f} | — |
| Movement-control Spearman | {bts_gate['estimates']['movement_spearman']:.3f} | — |

Best GFW shifts are {bts_gate['best_gfw_shift_observations']['pearson']} BTS observations (Pearson) and
{bts_gate['best_gfw_shift_observations']['spearman']} (Spearman). Both correlation families were required to
pass each registered association clause; this is the conservative implementation of wording that did not name
one family as primary.

## Annual call-count component

| Year | AIS cargo calls | Official container calls | Coverage | Error |
| ---: | ---: | ---: | ---: | ---: |
{call_rows}

The frozen ±20% rule passes in {call_gate['years_within_20pct']}/{call_gate['years_tested']} years. The present
AIS product covers cargo-class calls across the port area and is not restricted to container terminals, while
the official comparator is container-vessel calls. The mismatch is reported as a failed component; it is not
used to invalidate a separately passing physical GFW/BTS branch or to claim container-call accuracy.

## Branch decision

* GFW spatial policy analysis: **{'AUTHORIZED' if decision['decision']['gfw_spatial_policy_branch_authorized'] else 'BLOCKED'}**.
* Annual container-call claims: **{'AUTHORIZED' if decision['decision']['annual_call_claim_authorized'] else 'BLOCKED'}**.
* Individual waiting, anchor/berth state and Pillar-B claims: **BLOCKED**.
"""
    (OUT / "NS_G1_direct_measurement_report.md").write_text(report, encoding="utf-8")
    return decision


def _fetch(date_range):
    return fetch_presence(BOX, date_range, filters=("vessel_type='cargo'",))


def rings():
    if CACHE.exists():
        return pd.read_csv(CACHE)
    frames = []
    for yr in range(2019, 2024):
        d = _fetch(f"{yr}-01-01,{yr}-12-31")
        d["hours"] = pd.to_numeric(d["hours"], errors="coerce")
        d["lat"], d["lon"] = pd.to_numeric(d["lat"]), pd.to_numeric(d["lon"])
        nm = _nm(d["lat"].values, d["lon"].values)
        d["ring"] = np.where(nm <= 50, "0-50nm", np.where(nm <= 150, "50-150nm", np.where(nm <= 300, "150-300nm", "beyond")))
        frames.append(d[d.ring != "beyond"].groupby(["date", "ring"])["hours"].sum().reset_index())
        print(f"  fetched cargo {yr}")
    out = pd.concat(frames, ignore_index=True); out.to_csv(CACHE, index=False, lineterminator="\n")
    return out


def _prepost(s, ev, win=12):
    idx = sorted(s.dropna().index); e = [i for i in idx if i >= ev]
    if not e:
        return np.nan, np.nan
    e0 = idx.index(e[0])
    return s.iloc[max(0, e0 - win):e0].mean(), s.iloc[e0:e0 + win].mean()


def throughput_sensitivity(rings: pd.DataFrame) -> pd.DataFrame:
    """Return the frozen 12-month contrast per million official container TEU."""
    event_pos = list(rings.index).index("2021-11")
    rings = rings.iloc[event_pos - 12:event_pos + 12]
    if len(rings) != 24:
        raise ValueError("H1 throughput sensitivity requires 12 pre- and 12 post-reform months")
    teu = pd.read_csv(TEU).set_index("year_month")["value"].rename("teu")
    joined = rings.join(teu, how="left")
    if joined["teu"].isna().any() or (joined["teu"] <= 0).any():
        raise ValueError("H1 throughput sensitivity requires positive TEU for every cargo-presence month")
    adjusted = joined.drop(columns="teu").div(joined["teu"] / 1_000_000, axis=0)
    rows = []
    for ring in ["0-50nm", "50-150nm", "150-300nm", "total_0_300"]:
        pre, post = _prepost(adjusted[ring], "2021-11")
        rows.append({"ring": ring, "pre_vhr_per_mteu": pre, "post_vhr_per_mteu": post,
                     "abs_change_per_mteu": post - pre, "pct_change": 100 * (post / pre - 1)})
    return pd.DataFrame(rows)


def analyse():
    OUT.mkdir(parents=True, exist_ok=True)
    r = rings().pivot(index="date", columns="ring", values="hours").sort_index()
    r["total_0_300"] = r[["0-50nm", "50-150nm", "150-300nm"]].sum(axis=1)
    print("\nH1 ABSOLUTE cargo-vessel presence-hours per ring (monthly mean, pre vs post 2021-11 reform):")
    print(f"{'ring':12} {'pre':>12} {'post':>12} {'d abs':>12} {'d %':>8}")
    rows = []
    for ring in ["0-50nm", "50-150nm", "150-300nm", "total_0_300"]:
        pre, post = _prepost(r[ring], "2021-11")
        rows.append({"ring": ring, "pre_vhr_mo": round(pre), "post_vhr_mo": round(post),
                     "abs_change": round(post - pre), "pct": round(100 * (post - pre) / pre, 1)})
        print(f"{ring:12} {pre:12.0f} {post:12.0f} {post-pre:12.0f} {100*(post-pre)/pre:7.1f}%")
    tab = pd.DataFrame(rows); tab.to_csv(OUT / "H1_cargo_massbalance.csv", index=False, lineterminator="\n")
    near = rows[0]["abs_change"]; far = rows[2]["abs_change"]; tot = rows[3]["abs_change"]
    print(f"\nAbsolute: 0-50nm {near:+,.0f}  150-300nm {far:+,.0f}  TOTAL 0-300nm {tot:+,.0f} cargo vessel-hrs/mo")
    print("Interpretation: is the far-ring absolute GAIN comparable to the near-ring absolute change, or much smaller?")

    adjusted = throughput_sensitivity(r)
    adjusted.to_csv(OUT / "H1_cargo_throughput_sensitivity.csv", index=False, float_format="%.3f",
                    lineterminator="\n")
    print("\nThroughput sensitivity (cargo vessel-hours per million official container TEU):")
    print(adjusted.to_string(index=False, formatters={
        "pre_vhr_per_mteu": "{:.0f}".format,
        "post_vhr_per_mteu": "{:.0f}".format,
        "abs_change_per_mteu": "{:+.0f}".format,
        "pct_change": "{:+.1f}%".format,
    }))
    # placebo far/near ratio robustness
    print("\nPlacebo check (far/near log-ratio change):")
    r["fn"] = np.log(r["150-300nm"] / r["0-50nm"])
    for lab, ev in [("EVENT 2021-11", "2021-11"), ("2019-11", "2019-11"), ("2020-11", "2020-11"), ("2022-11", "2022-11")]:
        pre, post = _prepost(r["fn"], ev)
        print(f"  {lab:14} dlog(far/near) = {post-pre:+.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-gate", action="store_true",
                        help="run the OSF-registered GFW/BTS direct-measurement gate")
    args = parser.parse_args()
    run_direct_gate() if args.direct_gate else analyse()
