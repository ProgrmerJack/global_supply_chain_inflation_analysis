"""Prospective WCWLB AB 617 source-oriented air-quality analysis.

This module implements the design frozen in
``prereg/amendments/2026-07-18_spb_ab617_source_oriented_aq.md``.  Its activity,
wind, parsing, geometry and estimator functions can be tested without opening
AB 617 outcomes.  Outcome loading fails closed through the separately frozen
acquisition preflight.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[2]
SOURCE_LAT = 33.72
SOURCE_LON = -118.20
START_UTC = pd.Timestamp("2020-01-01", tz="UTC")
END_UTC = pd.Timestamp("2025-01-01", tz="UTC")
PRIMARY_SOG = 0.5
SOG_SENSITIVITIES = (0.3, 0.5, 0.7)
CAP_SENSITIVITIES = (1, 2)
MIN_ACTIVE_DAYS = 365
MIN_ACTIVE_COVERAGE = 0.50
MIN_MONTHLY_OBS = 20
MIN_PRIMARY_SITES = 3
MIN_CONCURRENT_SITE_HOURS = 20_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _ChartParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attributes: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if values.get("id") == "pollutantChart":
            self.attributes = values


def _csv_attribute(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_chart_html(
    content: bytes,
    *,
    site_id: int,
    parameter_id: str,
    duration_id: str,
    parameter_name: str,
) -> pd.DataFrame:
    """Parse the official chart fragment without silently repairing its data.

    The South Coast AQMD client reads ``data-average-values`` and
    ``data-average-date-times`` from ``#pollutantChart``.  The same attributes
    are retained here, with Pacific local timestamps converted explicitly to
    UTC. Ambiguous or nonexistent daylight-saving timestamps remain missing.
    """
    parser = _ChartParser()
    text = content.decode("utf-8", errors="replace")
    parser.feed(text)
    if parser.attributes is None:
        if "data-is-error-page=\"true\"" in text or "No Data Found!" in text:
            return pd.DataFrame({
                "site_id": [int(site_id)],
                "parameter_id": [str(parameter_id)],
                "duration_id": [str(duration_id)],
                "parameter_name": [str(parameter_name)],
                "average_name": [""],
                "unit": [""],
                "timestamp_utc": [pd.NaT],
                "value": [math.nan],
            })
        raise ValueError("official chart response lacks #pollutantChart")
    attrs = parser.attributes
    values = _csv_attribute(attrs.get("data-average-values", ""))
    dates = _csv_attribute(attrs.get("data-average-date-times", ""))
    if len(values) != len(dates):
        raise ValueError("official chart values and timestamps have unequal lengths")
    local = pd.to_datetime(pd.Series(dates, dtype="string"), format="mixed", errors="coerce")
    if getattr(local.dt, "tz", None) is None:
        local = local.dt.tz_localize("America/Los_Angeles", ambiguous="NaT", nonexistent="NaT")
    utc = local.dt.tz_convert("UTC")
    return pd.DataFrame({
        "site_id": int(site_id),
        "parameter_id": str(parameter_id),
        "duration_id": str(duration_id),
        "parameter_name": str(parameter_name),
        "average_name": attrs.get("data-average-name", ""),
        "unit": attrs.get("data-unit-name", ""),
        "timestamp_utc": utc,
        "value": pd.to_numeric(pd.Series(values), errors="coerce"),
    })


def pollutant_family(name: str) -> str:
    normalized = "".join(ch for ch in str(name).upper() if ch.isalnum())
    if "NO2" in normalized or "NITROGENDIOXIDE" in normalized:
        return "NO2"
    if "NOX" in normalized or "NITROGENOXIDES" in normalized:
        return "NOX"
    if normalized in {"BC", "BLACKCARBON"} or "BLACKCARBON" in normalized:
        return "BC"
    if "PM25" in normalized or "FINEPARTIC" in normalized:
        return "PM2.5"
    if "ULTRAFINE" in normalized or normalized == "UFP":
        return "UFP"
    if normalized in {"O3", "OZONE"} or "OZONE" in normalized:
        return "O3"
    return "OTHER"


def screen_site_series(observations: pd.DataFrame) -> pd.DataFrame:
    """Apply the frozen effect-blind availability rules to parsed series."""
    required = {"site_id", "parameter_id", "duration_id", "parameter_name", "average_name", "unit",
                "timestamp_utc", "value"}
    if missing := required.difference(observations.columns):
        raise ValueError(f"AB 617 observations lack columns: {sorted(missing)}")
    data = observations.copy()
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True, errors="coerce")
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    keys = ["site_id", "parameter_id", "duration_id", "parameter_name", "average_name", "unit"]
    rows: list[dict[str, object]] = []
    for key, group in data.groupby(keys, dropna=False, sort=True):
        group = group.loc[
            group["timestamp_utc"].ge(START_UTC)
            & group["timestamp_utc"].lt(END_UTC)
            & group["value"].notna()
        ].drop_duplicates(["site_id", "parameter_id", "duration_id", "timestamp_utc"])
        record = dict(zip(keys, key, strict=True))
        record["pollutant_family"] = pollutant_family(str(key[3]))
        if group.empty:
            record.update({
                "first_utc": pd.NaT,
                "last_utc": pd.NaT,
                "active_span_days": math.nan,
                "observations": 0,
                "active_span_expected_hours": 0.0,
                "active_span_coverage": 0.0,
                "minimum_month_observations": 0,
                "median_interval_hours": math.nan,
                "hourly_or_finer": False,
                "eligible": False,
            })
            rows.append(record)
            continue
        group = group.sort_values("timestamp_utc")
        first, last = group["timestamp_utc"].iloc[0], group["timestamp_utc"].iloc[-1]
        span_hours = max((last - first).total_seconds() / 3600.0 + 1.0, 1.0)
        gaps = group["timestamp_utc"].diff().dt.total_seconds().div(3600).dropna()
        median_interval = float(gaps.median()) if len(gaps) else math.nan
        declared = f"{key[4]} {key[2]}".lower()
        hourly_or_finer = (
            any(token in declared for token in ("hour", "minute", "min"))
            and (not math.isfinite(median_interval) or median_interval <= 1.5)
        )
        monthly_min = int(group.groupby(group["timestamp_utc"].dt.strftime("%Y-%m")).size().min())
        record.update({
            "first_utc": first,
            "last_utc": last,
            "active_span_days": (last - first).total_seconds() / 86400.0,
            "observations": int(len(group)),
            "active_span_expected_hours": span_hours,
            "active_span_coverage": len(group) / span_hours,
            "minimum_month_observations": monthly_min,
            "median_interval_hours": median_interval,
            "hourly_or_finer": bool(hourly_or_finer),
        })
        record["eligible"] = bool(
            hourly_or_finer
            and record["active_span_days"] >= MIN_ACTIVE_DAYS
            and record["active_span_coverage"] >= MIN_ACTIVE_COVERAGE
            and monthly_min >= MIN_MONTHLY_OBS
            and bool(str(key[5]).strip())
        )
        rows.append(record)
    return pd.DataFrame(rows)


def build_hourly_activity(
    parquet_glob: str | Path = ROOT / "data/interim/national_pings/year=*/month=*/pings_*.parquet",
    output: Path | None = ROOT / "data/processed/spb_hourly_freight_activity_2020_2024.csv",
    *,
    memory_limit: str = "4GB",
    threads: int = 4,
) -> pd.DataFrame:
    """Stream the retained census into hourly stationary/moving vessel-hours."""
    pattern = str(parquet_glob).replace("\\", "/")
    if not set(SOG_SENSITIVITIES).issuperset({PRIMARY_SOG}) or any(cap <= 0 for cap in CAP_SENSITIVITIES):
        raise RuntimeError("invalid frozen AB 617 activity sensitivities")
    thresholds = ", ".join(f"({value:.1f})" for value in SOG_SENSITIVITIES)
    caps = ", ".join(f"({value})" for value in CAP_SENSITIVITIES)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        con.execute(f"SET memory_limit='{memory_limit}'")
        con.execute(f"SET threads={int(threads)}")
        spill = ROOT / "data/interim/duckdb_spill"
        spill.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{str(spill).replace(chr(92), '/')}'")
        query = f"""
        WITH selected AS (
            SELECT mmsi, timestamp AS start_ts, sog,
                   lead(timestamp) OVER (PARTITION BY mmsi ORDER BY timestamp) AS next_ts
            FROM read_parquet('{pattern}', hive_partitioning=true)
            WHERE year BETWEEN 2020 AND 2024
              AND port_complex_id = 'san_pedro_bay'
              AND vessel_type BETWEEN 70 AND 89
              AND timestamp >= TIMESTAMPTZ '2020-01-01 00:00:00+00'
              AND timestamp < TIMESTAMPTZ '2025-01-01 00:00:00+00'
        ), expanded_caps AS (
            SELECT s.*, c.cap_hours,
                   least(s.next_ts, s.start_ts + c.cap_hours * INTERVAL '1 hour',
                         TIMESTAMPTZ '2025-01-01 00:00:00+00') AS end_ts
            FROM selected s CROSS JOIN (VALUES {caps}) c(cap_hours)
            WHERE s.next_ts > s.start_ts
        ), hour_segments AS (
            SELECT e.*, h.hour_utc,
                   epoch(least(e.end_ts, h.hour_utc + INTERVAL '1 hour')
                       - greatest(e.start_ts, h.hour_utc)) / 3600.0 AS overlap_hours
            FROM expanded_caps e
            CROSS JOIN LATERAL generate_series(
                date_trunc('hour', e.start_ts),
                date_trunc('hour', e.end_ts - INTERVAL '1 microsecond'),
                INTERVAL '1 hour'
            ) h(hour_utc)
            WHERE e.end_ts > e.start_ts
        )
        SELECT h.hour_utc, t.stationary_sog_threshold, h.cap_hours,
               sum(CASE WHEN h.sog < t.stationary_sog_threshold THEN h.overlap_hours ELSE 0 END)
                   AS stationary_hours,
               sum(CASE WHEN h.sog >= 3.0 THEN h.overlap_hours ELSE 0 END) AS moving_hours,
               sum(CASE WHEN h.sog IS NULL THEN h.overlap_hours ELSE 0 END) AS unresolved_sog_hours,
               count(*) AS contributing_segments
        FROM hour_segments h CROSS JOIN (VALUES {thresholds}) t(stationary_sog_threshold)
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """
        frame = con.execute(query).fetchdf()
    finally:
        con.close()
    frame["hour_utc"] = pd.to_datetime(frame["hour_utc"], utc=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index=False, lineterminator="\n")
        manifest = output.with_suffix(".manifest.json")
        manifest.write_text(json.dumps({
            "dataset": "SPB hourly retained cargo/tanker AIS activity, 2020-2024",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_glob": pattern,
            "port_complex_id": "san_pedro_bay",
            "vessel_type": "NMEA 70-89",
            "stationary_sog_thresholds_kn": list(SOG_SENSITIVITIES),
            "moving_sog_threshold_kn": 3.0,
            "interval_caps_hours": list(CAP_SENSITIVITIES),
            "rows": len(frame),
            "output_sha256": sha256(output),
        }, indent=2) + "\n", encoding="utf-8")
    return frame


def _circular_hourly_wind(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["hour_utc"] = pd.to_datetime(data["DATE"], utc=True, errors="coerce").dt.floor("h")
    data["wind_dir_deg"] = pd.to_numeric(data["wind_dir_deg"], errors="coerce")
    data["wind_speed_ms"] = pd.to_numeric(data["wind_speed_ms"], errors="coerce")
    radians = np.deg2rad(data["wind_dir_deg"])
    data["_sin"] = np.sin(radians)
    data["_cos"] = np.cos(radians)
    grouped = data.groupby("hour_utc", as_index=False).agg(
        wind_speed_ms=("wind_speed_ms", "mean"), _sin=("_sin", "mean"), _cos=("_cos", "mean")
    )
    grouped["wind_dir_deg"] = (np.rad2deg(np.arctan2(grouped["_sin"], grouped["_cos"])) + 360) % 360
    return grouped.drop(columns=["_sin", "_cos"])


def load_spb_wind() -> pd.DataFrame:
    paths = [
        ROOT / "data/external/noaa_wind/noaa_hourly_wind_2019_2023.csv",
        ROOT / "data/external/noaa_wind/noaa_hourly_wind_spb_2024.csv",
    ]
    frames = []
    for path in paths:
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        frames.append(frame.loc[frame["complex_id"].eq("san_pedro_bay")])
    if not frames:
        raise FileNotFoundError("San Pedro Bay NOAA wind inputs are unavailable")
    return _circular_hourly_wind(pd.concat(frames, ignore_index=True))


def _bearing(lat1: np.ndarray, lon1: np.ndarray, lat2: float, lon2: float) -> np.ndarray:
    phi1, phi2 = np.deg2rad(lat1), math.radians(lat2)
    dlon = math.radians(lon2) - np.deg2rad(lon1)
    y = np.sin(dlon) * math.cos(phi2)
    x = np.cos(phi1) * math.sin(phi2) - np.sin(phi1) * math.cos(phi2) * np.cos(dlon)
    return (np.rad2deg(np.arctan2(y, x)) + 360) % 360


def _distance_km(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    phi1, phi2 = np.deg2rad(lat), math.radians(SOURCE_LAT)
    dphi = math.radians(SOURCE_LAT) - phi1
    dlon = math.radians(SOURCE_LON) - np.deg2rad(lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * math.cos(phi2) * np.sin(dlon / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def add_plume_weight(panel: pd.DataFrame, *, rotate_degrees: float = 0.0) -> pd.DataFrame:
    required = {"latitude", "longitude", "wind_dir_deg"}
    if missing := required.difference(panel.columns):
        raise ValueError(f"plume panel lacks columns: {sorted(missing)}")
    out = panel.copy()
    lat = pd.to_numeric(out["latitude"], errors="coerce").to_numpy()
    lon = pd.to_numeric(out["longitude"], errors="coerce").to_numpy()
    direction_to_source = _bearing(lat, lon, SOURCE_LAT, SOURCE_LON)
    difference = np.deg2rad(
        (pd.to_numeric(out["wind_dir_deg"], errors="coerce").to_numpy()
         - direction_to_source - rotate_degrees + 180) % 360 - 180
    )
    out["distance_km"] = _distance_km(lat, lon)
    out["plume_weight"] = np.maximum(np.cos(difference), 0.0) / (1.0 + out["distance_km"])
    return out


def _residualize_two_way(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    entity: str = "site_id",
    time: str = "hour_utc",
    tolerance: float = 1e-10,
    max_iter: int = 500,
) -> pd.DataFrame:
    values = frame[columns].astype(float).copy()
    for _ in range(max_iter):
        before = values.to_numpy(copy=True)
        values -= values.groupby(frame[entity]).transform("mean")
        values -= values.groupby(frame[time]).transform("mean")
        if np.nanmax(np.abs(values.to_numpy() - before)) < tolerance:
            return values
    raise RuntimeError("two-way fixed-effect residualization did not converge")


def _cluster_meat(x: np.ndarray, residual: np.ndarray, groups: pd.Series) -> np.ndarray:
    score = x * residual[:, None]
    grouped = pd.DataFrame(score).groupby(pd.Series(groups).reset_index(drop=True)).sum().to_numpy()
    return grouped.T @ grouped


@dataclass(frozen=True)
class ModelResult:
    beta: float
    standard_error: float
    ci_low: float
    ci_high: float
    p_value: float
    observations: int
    sites: int
    dates: int


def fit_source_model(frame: pd.DataFrame, *, outcome: str = "outcome", exposure: str = "exposure") -> ModelResult:
    """Fit the frozen site/hour FE model with date/site clustered inference."""
    required = {"site_id", "hour_utc", outcome, exposure}
    if missing := required.difference(frame.columns):
        raise ValueError(f"source model lacks columns: {sorted(missing)}")
    data = frame.loc[:, list(required)].dropna().copy()
    data["hour_utc"] = pd.to_datetime(data["hour_utc"], utc=True, errors="raise")
    data["date_utc"] = data["hour_utc"].dt.strftime("%Y-%m-%d")
    residualized = _residualize_two_way(data, [outcome, exposure])
    y = residualized[outcome].to_numpy()
    x = residualized[[exposure]].to_numpy()
    bread = np.linalg.inv(x.T @ x)
    beta = float((bread @ x.T @ y)[0])
    residual = y - x[:, 0] * beta
    intersection = data["site_id"].astype(str) + "|" + data["date_utc"]
    meat = (
        _cluster_meat(x, residual, data["site_id"])
        + _cluster_meat(x, residual, data["date_utc"])
        - _cluster_meat(x, residual, intersection)
    )
    variance = float((bread @ meat @ bread)[0, 0])
    standard_error = math.sqrt(max(variance, 0.0))
    z = beta / standard_error if standard_error > 0 else math.copysign(math.inf, beta)
    return ModelResult(
        beta=beta,
        standard_error=standard_error,
        ci_low=beta - 1.959963984540054 * standard_error,
        ci_high=beta + 1.959963984540054 * standard_error,
        p_value=2 * norm.sf(abs(z)),
        observations=len(data),
        sites=int(data["site_id"].nunique()),
        dates=int(data["date_utc"].nunique()),
    )


def holm_adjust(p_values: list[float]) -> list[float]:
    values = np.asarray(p_values, dtype=float)
    order = np.argsort(values)
    adjusted = np.empty(len(values), dtype=float)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(values) - rank) * values[index])
        adjusted[index] = min(running, 1.0)
    return adjusted.tolist()


def load_registered_observations() -> pd.DataFrame:
    """Load every retained chart response only after the external gate passes."""
    sys.path.insert(0, str(ROOT / "src/acquire"))
    import ab617_observations as acquisition  # noqa: PLC0415

    acquisition.preflight()
    manifest = pd.read_csv(acquisition.OUT / "manifest.csv")
    rows = []
    for _, item in manifest.iterrows():
        rows.append(parse_chart_html(
            (acquisition.OUT / item["artifact"]).read_bytes(),
            site_id=int(item["site_id"]), parameter_id=str(item["parameter-id"]),
            duration_id=str(item["duration-id"]),
            parameter_name=str(item["parameter-name"]),
        ))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen WCWLB AB 617 source-oriented analysis utilities.")
    sub = parser.add_subparsers(dest="command", required=True)
    activity = sub.add_parser("build-activity")
    activity.add_argument("--memory-limit", default="4GB")
    activity.add_argument("--threads", type=int, default=4)
    sub.add_parser("screen-observations")
    args = parser.parse_args()
    if args.command == "build-activity":
        result = build_hourly_activity(memory_limit=args.memory_limit, threads=args.threads)
        print(f"wrote {len(result):,} hourly activity sensitivity rows")
    else:
        observations = load_registered_observations()
        screen = screen_site_series(observations)
        destination = ROOT / "results/development/spb_ab617_source_aq/availability_screen.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        screen.to_csv(destination, index=False, lineterminator="\n")
        valid_times = pd.to_datetime(observations["timestamp_utc"], utc=True, errors="coerce")
        decision = {
            "study": "WCWLB AB 617 source-oriented air-quality design",
            "registration": "https://osf.io/j6utx/",
            "decision": "FAIL_FEASIBILITY",
            "reason": "official endpoint supplied no observations inside the frozen 2020-2024 window",
            "declared_series": int(len(screen)),
            "chart_responses_with_values": int(observations["value"].notna().groupby(
                [observations["site_id"], observations["parameter_id"], observations["duration_id"]]
            ).any().sum()),
            "no_data_responses": int((screen["observations"].eq(0) & screen["average_name"].eq("")).sum()),
            "retrieved_value_rows": int(observations["value"].notna().sum()),
            "retrieved_first_utc": valid_times.min().isoformat() if valid_times.notna().any() else None,
            "retrieved_last_utc": valid_times.max().isoformat() if valid_times.notna().any() else None,
            "registered_window": "2020-01-01 through 2024-12-31",
            "in_window_observations": int(screen["observations"].sum()),
            "eligible_series": int(screen["eligible"].sum()),
            "eligible_primary_sites": 0,
            "required_primary_sites": MIN_PRIMARY_SITES,
            "concurrent_primary_site_hours": 0,
            "required_concurrent_primary_site_hours": MIN_CONCURRENT_SITE_HOURS,
            "source_model_estimated": False,
            "bounded_null_claim": False,
            "ns_g4_passed": False,
            "availability_screen_sha256": sha256(destination),
        }
        (destination.parent / "feasibility_decision.json").write_text(
            json.dumps(decision, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {len(screen):,} declared-series availability rows to {destination}")


if __name__ == "__main__":
    main()
