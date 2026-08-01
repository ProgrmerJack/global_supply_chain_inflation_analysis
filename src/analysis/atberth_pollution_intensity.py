"""System-level 2025 At-Berth pollution-intensity analysis.

The governing protocol is
``prereg/amendments/2026-07-28_spb_atberth_pollution_intensity.md``.
Activity construction is outcome-free; ``run`` opens the untouched 2025 AQS
outcome only after the executable and protocol have been hash-frozen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import norm
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
PINGS = ROOT / "data/interim/nature_recovery/coastal_pings/year=*/month=*/*.parquet"
VESSELS = ROOT / "data/processed/vessel_characteristics.csv"
TERMINALS = ROOT / "config/registries/carb_atberth_spb_tanker_terminals.csv"
AQS = ROOT / "data/external/aqs_hourly/aqs_hourly_no2_los_angeles_2023_2025.csv"
WIND_FILES = tuple(ROOT / f"data/external/noaa_wind/noaa_hourly_wind_spb_{year}.csv" for year in (2024, 2025))
GHCNH_2025 = ROOT / "data/external/noaa_wind/noaa_hourly_wind_spb_2025_ghcnh_continuation.csv"
OLD_WIND = ROOT / "data/external/noaa_wind/noaa_hourly_wind_2019_2023.csv"
SMOKE_DIR = ROOT / "data/external/hms_smoke"
SOURCE_CELLS = ROOT / "data/processed/spb_atberth_source_cells_2023_2025.parquet"
OUT = ROOT / "results/confirmatory/spb_atberth_pollution_intensity_corrected"
START = pd.Timestamp("2023-01-01", tz="UTC")
POST = pd.Timestamp("2025-01-01", tz="UTC")
END = pd.Timestamp("2026-01-01", tz="UTC")
PRIMARY_RADIUS_KM = 1.5
PRIMARY_CAP_HOURS = 2.0
MIN_SITE_PERIOD_COVERAGE = 0.65
MIN_SITES = 3
MIN_PERIOD_SITE_HOURS = 12_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _haversine_sql(lat: float, lon: float) -> str:
    return (
        "6371.0 * 2 * asin(sqrt(pow(sin(radians(p.lat - " + str(lat) + ") / 2), 2) + "
        "cos(radians(p.lat)) * cos(radians(" + str(lat) + ")) * "
        "pow(sin(radians(p.lon - " + str(lon) + ") / 2), 2)))"
    )


def build_hourly_source_cells(
    output: Path = SOURCE_CELLS,
    *,
    terminal_radius_km: float = PRIMARY_RADIUS_KM,
    interval_cap_hours: float = PRIMARY_CAP_HOURS,
    memory_limit: str = "6GB",
    threads: int = 8,
) -> pd.DataFrame:
    """Stream coastal pings into hour/source-cell vessel-time."""
    if terminal_radius_km <= 0 or interval_cap_hours <= 0:
        raise ValueError("radius and interval cap must be positive")
    terminals = pd.read_csv(TERMINALS).loc[lambda x: x.assignment_eligible.eq(1)]
    distance = "least(" + ",".join(
        _haversine_sql(float(row.latitude), float(row.longitude))
        for row in terminals.itertuples()
    ) + ")"
    vessels = pd.read_csv(VESSELS, usecols=["mmsi", "length_m", "vessel_type"])
    vessels["source_population"] = np.select(
        [
            vessels.vessel_type.between(80, 89) & vessels.length_m.ge(121.92),
            vessels.vessel_type.between(70, 79),
        ],
        ["tanker", "cargo"],
        default="excluded",
    )
    vessels = vessels.loc[vessels.source_population.ne("excluded"), ["mmsi", "source_population"]]
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        con.execute(f"SET memory_limit='{memory_limit}'")
        con.execute(f"SET threads={int(threads)}")
        spill = Path(tempfile.gettempdir()) / "duckdb_atberth_pollution"
        spill.mkdir(exist_ok=True)
        con.execute(f"SET temp_directory='{spill.as_posix()}'")
        con.register("source_population", vessels)
        query = f"""
        WITH ordered AS (
            SELECT p.mmsi, p.timestamp AS start_ts, p.lat, p.lon, p.sog,
                   v.source_population,
                   lead(p.timestamp) OVER (PARTITION BY p.mmsi ORDER BY p.timestamp) AS next_ts,
                   {distance} AS terminal_distance_km
            FROM read_parquet('{PINGS.as_posix()}', hive_partitioning=true) p
            INNER JOIN source_population v USING (mmsi)
            WHERE p.port_complex_id = 'san_pedro_bay'
              AND p.timestamp >= TIMESTAMPTZ '2023-01-01 00:00:00+00'
              AND p.timestamp < TIMESTAMPTZ '2026-01-01 00:00:00+00'
        ), classified AS (
            SELECT *, CASE
                WHEN source_population='tanker' AND sog < 0.5
                     AND terminal_distance_km <= {terminal_radius_km} THEN 'terminal_tanker_stationary'
                WHEN source_population='tanker' AND sog < 0.5
                     AND terminal_distance_km BETWEEN 3.0 AND 15.0 THEN 'offshore_tanker_stationary'
                WHEN source_population='tanker' AND sog >= 3.0
                     AND terminal_distance_km <= {terminal_radius_km} THEN 'terminal_tanker_moving'
                WHEN source_population='cargo' AND sog < 0.5
                     AND terminal_distance_km <= 5.0 THEN 'cargo_stationary'
                ELSE NULL END AS source_class
            FROM ordered
        ), intervals AS (
            SELECT *, least(next_ts, start_ts + {interval_cap_hours} * INTERVAL '1 hour',
                            TIMESTAMPTZ '2026-01-01 00:00:00+00') AS end_ts
            FROM classified
            WHERE source_class IS NOT NULL AND next_ts > start_ts
        ), pieces AS (
            SELECT source_class, round(lat, 3) AS source_lat, round(lon, 3) AS source_lon,
                   h.hour_utc,
                   epoch(least(end_ts, h.hour_utc + INTERVAL '1 hour')
                       - greatest(start_ts, h.hour_utc)) / 3600.0 AS vessel_hours
            FROM intervals
            CROSS JOIN LATERAL generate_series(
                date_trunc('hour', start_ts),
                date_trunc('hour', end_ts - INTERVAL '1 microsecond'),
                INTERVAL '1 hour'
            ) h(hour_utc)
            WHERE end_ts > start_ts
        )
        SELECT hour_utc, source_class, source_lat, source_lon,
               sum(vessel_hours) AS vessel_hours, count(*) AS contributing_intervals
        FROM pieces
        GROUP BY 1,2,3,4
        ORDER BY 1,2,3,4
        """
        frame = con.execute(query).fetchdf()
    finally:
        con.close()
    frame["hour_utc"] = pd.to_datetime(frame.hour_utc, utc=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output, index=False)
    output.with_suffix(".manifest.json").write_text(json.dumps({
        "dataset": "SPB source-cell hourly vessel activity for At-Berth pollution design",
        "window": "2023-01-01/2025-12-31 UTC",
        "terminal_radius_km": terminal_radius_km,
        "interval_cap_hours": interval_cap_hours,
        "rows": len(frame),
        "classes": frame.groupby("source_class").vessel_hours.sum().to_dict(),
        "source_sha256": sha256(output),
        "terminal_config_sha256": sha256(TERMINALS),
        "vessel_characteristics_sha256": sha256(VESSELS),
    }, indent=2) + "\n", encoding="utf-8")
    return frame


def load_wind() -> pd.DataFrame:
    frames = []
    old = pd.read_csv(OLD_WIND)
    frames.append(old.loc[old.complex_id.eq("san_pedro_bay")])
    frames.extend(pd.read_csv(path) for path in WIND_FILES)
    data = pd.concat(frames, ignore_index=True)
    data["hour_utc"] = pd.to_datetime(data.DATE, utc=True, errors="coerce").dt.floor("h")
    data = data.loc[data.hour_utc.ge(START) & data.hour_utc.lt(END)]
    data["wind_dir_deg"] = pd.to_numeric(data.wind_dir_deg, errors="coerce")
    data["wind_speed_ms"] = pd.to_numeric(data.wind_speed_ms, errors="coerce")
    radians = np.deg2rad(data.wind_dir_deg)
    data["sin"] = np.sin(radians)
    data["cos"] = np.cos(radians)
    out = data.groupby("hour_utc", as_index=False).agg(
        wind_speed_ms=("wind_speed_ms", "mean"), sin=("sin", "mean"), cos=("cos", "mean")
    )
    out["wind_dir_deg"] = (np.rad2deg(np.arctan2(out.sin, out.cos)) + 360) % 360
    out = out.drop(columns=["sin", "cos"])
    if GHCNH_2025.exists():
        continuation = pd.read_csv(GHCNH_2025, low_memory=False)
        continuation["hour_utc"] = pd.to_datetime(continuation.DATE, utc=True, errors="coerce").dt.floor("h")
        continuation["wind_dir_deg"] = pd.to_numeric(continuation.wind_dir_deg, errors="coerce")
        continuation["wind_speed_ms"] = pd.to_numeric(continuation.wind_speed_ms, errors="coerce")
        continuation = continuation.loc[
            continuation.hour_utc.ge(START) & continuation.hour_utc.lt(END),
            ["hour_utc", "wind_speed_ms", "wind_dir_deg"],
        ].dropna(subset=["hour_utc"]).drop_duplicates("hour_utc")
        out = out.set_index("hour_utc").combine_first(continuation.set_index("hour_utc")).reset_index()
    out.loc[~out.wind_dir_deg.between(0, 360), "wind_dir_deg"] = np.nan
    return out


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.asarray, (lat1, lon1, lat2, lon2))
    p1, p2 = np.deg2rad(lat1), np.deg2rad(lat2)
    dlat, dlon = p2 - p1, np.deg2rad(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = np.deg2rad(lat1), np.deg2rad(lat2)
    dlon = np.deg2rad(np.asarray(lon2) - np.asarray(lon1))
    y = np.sin(dlon) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dlon)
    return (np.rad2deg(np.arctan2(y, x)) + 360) % 360


def build_plume_exposure(
    cells: pd.DataFrame,
    monitors: pd.DataFrame,
    wind: pd.DataFrame,
    *,
    rotate_degrees: float = 0.0,
    activity_shift_hours: int = 0,
) -> pd.DataFrame:
    """Map source-cell vessel-hours to monitor-hour plume-weighted exposure."""
    source = cells.copy()
    source["hour_utc"] += pd.Timedelta(hours=activity_shift_hours)
    source = source.merge(wind, on="hour_utc", how="inner")
    parts = []
    for monitor in monitors.itertuples():
        distance = haversine_km(monitor.latitude, monitor.longitude, source.source_lat, source.source_lon)
        direction = bearing_deg(monitor.latitude, monitor.longitude, source.source_lat, source.source_lon)
        difference = np.deg2rad((source.wind_dir_deg - direction - rotate_degrees + 180) % 360 - 180)
        weighted = source.vessel_hours.to_numpy() * np.maximum(np.cos(difference), 0) / (1 + distance)
        part = source.assign(site_id=monitor.site_id, weighted=weighted).groupby(
            ["site_id", "hour_utc", "source_class"], as_index=False
        ).weighted.sum()
        parts.append(part)
    long = pd.concat(parts, ignore_index=True)
    return long.pivot_table(
        index=["site_id", "hour_utc"], columns="source_class", values="weighted", fill_value=0
    ).reset_index().rename_axis(columns=None)


def load_aqs(path: Path = AQS, *, radius_km: float = 50.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the outcome-independent POC, duplicate and geographic rules."""
    data = pd.read_csv(path, low_memory=False)
    data["hour_utc"] = pd.to_datetime(
        data["Date GMT"].astype(str) + " " + data["Time GMT"].astype(str), utc=True, errors="coerce"
    )
    data["value"] = pd.to_numeric(data["Sample Measurement"], errors="coerce")
    data["POC"] = pd.to_numeric(data["POC"], errors="coerce")
    data["site_id"] = (
        data["State Code"].astype(int).astype(str).str.zfill(2) + "-"
        + data["County Code"].astype(int).astype(str).str.zfill(3) + "-"
        + data["Site Num"].astype(int).astype(str).str.zfill(4)
    )
    centroid = pd.read_csv(TERMINALS)[["latitude", "longitude"]].mean()
    data["distance_km"] = haversine_km(
        data.Latitude, data.Longitude, centroid.latitude, centroid.longitude
    )
    data = data.loc[
        data.hour_utc.ge(START) & data.hour_utc.lt(END)
        & data.value.notna() & data.distance_km.le(radius_km)
        & data["Units of Measure"].astype(str).str.contains("parts per billion", case=False, na=False)
    ].copy()
    pre = data.loc[data.hour_utc.lt(POST)]
    counts = pre.groupby(["site_id", "POC"], as_index=False).hour_utc.nunique()
    selected = counts.sort_values(["site_id", "hour_utc", "POC"], ascending=[True, False, True]).drop_duplicates("site_id")
    data = data.merge(selected[["site_id", "POC"]], on=["site_id", "POC"], how="inner")
    exact = ["site_id", "POC", "hour_utc", "value"]
    data = data.drop_duplicates(exact)
    conflicts = data.groupby(["site_id", "POC", "hour_utc"]).value.nunique()
    bad_sites = set(conflicts.loc[conflicts.gt(1)].index.get_level_values("site_id"))
    data = data.loc[~data.site_id.isin(bad_sites)]
    monitors = data.sort_values("hour_utc").groupby("site_id", as_index=False).agg(
        latitude=("Latitude", "first"), longitude=("Longitude", "first"),
        distance_km=("distance_km", "first"), poc=("POC", "first")
    )
    return data[["site_id", "hour_utc", "value"]].drop_duplicates(), monitors


def screen_sites(aqs: pd.DataFrame, monitors: pd.DataFrame, wind: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_wind = wind.loc[wind.wind_speed_ms.between(1, 10) & wind.wind_dir_deg.notna(), ["hour_utc"]]
    data = aqs.merge(valid_wind, on="hour_utc", how="inner")
    expected_pre = int(valid_wind.hour_utc.lt(POST).sum())
    expected_post = int(valid_wind.hour_utc.ge(POST).sum())
    rows = []
    for site, group in data.groupby("site_id"):
        monthly_min = int(group.groupby(group.hour_utc.dt.strftime("%Y-%m")).size().min())
        pre_n = int(group.hour_utc.lt(POST).sum())
        post_n = int(group.hour_utc.ge(POST).sum())
        rows.append({
            "site_id": site, "pre_hours": pre_n, "post_hours": post_n,
            "pre_coverage": pre_n / expected_pre, "post_coverage": post_n / expected_post,
            "minimum_month_hours": monthly_min,
            "eligible": pre_n / expected_pre >= MIN_SITE_PERIOD_COVERAGE
                        and post_n / expected_post >= MIN_SITE_PERIOD_COVERAGE
                        and monthly_min >= 20,
        })
    screen = pd.DataFrame(rows).merge(monitors, on="site_id", how="left")
    eligible = set(screen.loc[screen.eligible, "site_id"])
    return data.loc[data.site_id.isin(eligible)], screen


def smoke_flags(monitors: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in (2023, 2024, 2025):
        polygons = gpd.read_file(f"zip://{(SMOKE_DIR / f'hms_smoke{year}.zip').as_posix()}").to_crs("EPSG:4326")
        polygons["start"] = pd.to_datetime(polygons.Start, format="%Y%j %H%M", utc=True, errors="coerce")
        polygons["end"] = pd.to_datetime(polygons.End, format="%Y%j %H%M", utc=True, errors="coerce")
        for monitor in monitors.itertuples():
            hit = polygons.loc[polygons.geometry.covers(Point(monitor.longitude, monitor.latitude))]
            for polygon in hit.itertuples():
                start = polygon.start.floor("h")
                end = polygon.end.ceil("h")
                if pd.isna(start) or pd.isna(end):
                    continue
                rows.extend((monitor.site_id, hour, str(polygon.Density).lower())
                            for hour in pd.date_range(start, end, freq="h", inclusive="left"))
    if not rows:
        return pd.DataFrame(columns=["site_id", "hour_utc", "smoke_density"])
    rank = {"light": 1, "medium": 2, "heavy": 3}
    out = pd.DataFrame(rows, columns=["site_id", "hour_utc", "smoke_density"])
    out["rank"] = out.smoke_density.map(rank).fillna(1)
    return out.sort_values("rank").drop_duplicates(["site_id", "hour_utc"], keep="last").drop(columns="rank")


def _within(data: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    values = data[columns].astype(float).copy()
    for _ in range(200):
        before = values.to_numpy(copy=True)
        values -= values.groupby(data["site_sector"]).transform("mean")
        values -= values.groupby(data["hour_utc"]).transform("mean")
        if np.max(np.abs(values.to_numpy() - before)) < 1e-10:
            return values
    raise RuntimeError("fixed-effect residualization did not converge")


def fit_policy_model(
    panel: pd.DataFrame,
    *,
    post_date: pd.Timestamp = POST,
    bootstrap_draws: int = 2000,
    seed: int = 20250728,
) -> dict:
    """Estimate the frozen relative tanker-intensity contrast."""
    exposure = {
        "tanker": "terminal_tanker_stationary", "cargo": "cargo_stationary",
        "offshore": "offshore_tanker_stationary",
    }
    required = {"site_id", "hour_utc", "value", "wind_dir_deg", *exposure.values()}
    if missing := required - set(panel):
        raise ValueError(f"policy panel missing columns: {sorted(missing)}")
    data = panel.dropna(subset=list(required)).copy()
    data["post"] = data.hour_utc.ge(post_date).astype(float)
    data["site_sector"] = data.site_id.astype(str) + "|" + ((data.wind_dir_deg // 45) % 8).astype(int).astype(str)
    scales = {}
    for short, column in exposure.items():
        scale = float(data.loc[data.post.eq(0), column].std())
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError(f"pre-policy {column} has no variation")
        data[short] = data[column] / scale
        scales[short] = scale
    data["tanker_post"] = data.tanker * data.post
    data["cargo_post"] = data.cargo * data.post
    xcols = ["tanker", "cargo", "offshore", "tanker_post", "cargo_post"]
    within = _within(data, ["value", *xcols])
    y = within.value.to_numpy()
    x = within[xcols].to_numpy()
    bread = np.linalg.inv(x.T @ x)
    beta = bread @ x.T @ y
    residual = y - x @ beta
    dates = data.hour_utc.dt.strftime("%Y-%m-%d")
    score = pd.DataFrame(x * residual[:, None]).assign(date=dates.to_numpy()).groupby("date").sum().to_numpy()
    covariance = bread @ (score.T @ score) @ bread
    contrast = np.array([0, 0, 0, 1, -1], dtype=float)
    estimate = float(contrast @ beta)
    se = math.sqrt(max(float(contrast @ covariance @ contrast), 0))

    sufficient = []
    for day, indices in data.groupby(dates).indices.items():
        xd, yd = x[indices], y[indices]
        sufficient.append((day, xd.T @ xd, xd.T @ yd))
    by_day = {day: (xx, xy) for day, xx, xy in sufficient}
    boundary = post_date.strftime("%Y-%m-%d")
    pre_days = sorted(day for day in by_day if day < boundary)
    post_days = sorted(day for day in by_day if day >= boundary)
    rng = np.random.default_rng(seed)

    def draw_counts(days: list[str]) -> dict[str, int]:
        sampled = []
        while len(sampled) < len(days):
            start = int(rng.integers(0, max(len(days) - 6, 1)))
            sampled.extend(days[start:start + 7])
        return pd.Series(sampled[:len(days)]).value_counts().to_dict()

    draws = []
    for _ in range(bootstrap_draws):
        counts = draw_counts(pre_days)
        for key, value in draw_counts(post_days).items():
            counts[key] = counts.get(key, 0) + value
        xx = sum((count * by_day[day][0] for day, count in counts.items()), np.zeros((len(xcols), len(xcols))))
        xy = sum((count * by_day[day][1] for day, count in counts.items()), np.zeros(len(xcols)))
        try:
            draws.append(float(contrast @ np.linalg.solve(xx, xy)))
        except np.linalg.LinAlgError:
            continue
    ci = np.quantile(draws, [0.025, 0.975]) if draws else [math.nan, math.nan]
    z = estimate / se if se else math.copysign(math.inf, estimate)
    return {
        "coefficient_order": xcols,
        "coefficients": dict(zip(xcols, beta.tolist(), strict=True)),
        "exposure_pre_sd_raw_units": scales,
        "relative_policy_effect_ppb": estimate,
        "date_clustered_se": se,
        "date_clustered_p": float(2 * norm.sf(abs(z))),
        "block7_bootstrap_draws_retained": len(draws),
        "block7_ci95": [float(ci[0]), float(ci[1])],
        "pre_tanker_response_ppb": float(beta[0]),
        "post_tanker_response_ppb": float(beta[0] + beta[3]),
        "observations": len(data),
        "sites": int(data.site_id.nunique()),
        "dates": int(dates.nunique()),
    }


def assemble_panel(
    cells: pd.DataFrame,
    *,
    rotate_degrees: float = 0.0,
    activity_shift_hours: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    wind = load_wind()
    aqs, monitors = load_aqs()
    aqs, screen = screen_sites(aqs, monitors, wind)
    eligible = monitors.loc[monitors.site_id.isin(screen.loc[screen.eligible, "site_id"])]
    if len(eligible) < MIN_SITES:
        raise RuntimeError(f"only {len(eligible)} eligible AQS sites; {MIN_SITES} required")
    valid_wind = wind.loc[wind.wind_speed_ms.between(1, 10) & wind.wind_dir_deg.notna()].copy()
    exposure = build_plume_exposure(
        cells, eligible, valid_wind,
        rotate_degrees=rotate_degrees, activity_shift_hours=activity_shift_hours,
    )
    panel = aqs.merge(valid_wind, on="hour_utc", how="inner").merge(
        exposure, on=["site_id", "hour_utc"], how="left"
    )
    classes = ["terminal_tanker_stationary", "cargo_stationary", "offshore_tanker_stationary",
               "terminal_tanker_moving"]
    for column in classes:
        panel[column] = panel.get(column, 0.0).fillna(0.0)
    smoke = smoke_flags(eligible)
    panel = panel.merge(smoke, on=["site_id", "hour_utc"], how="left")
    quality = {
        "eligible_sites": int(len(eligible)),
        "source_record_coverage": float(len(wind) / len(pd.date_range(START, END, freq="h", inclusive="left"))),
        "analysis_wind_hours": int(len(valid_wind)),
        "pre_site_hours_before_smoke": int(panel.hour_utc.lt(POST).sum()),
        "post_site_hours_before_smoke": int(panel.hour_utc.ge(POST).sum()),
        "medium_heavy_smoke_site_hours": int(panel.smoke_density.isin(["medium", "heavy"]).sum()),
        "all_smoke_site_hours": int(panel.smoke_density.notna().sum()),
    }
    return panel, screen, quality


def run_complete() -> dict:
    """Fire the frozen primary, falsifications and activity sensitivities once."""
    OUT.mkdir(parents=True, exist_ok=True)
    decision_path = OUT / "decision.json"
    if decision_path.exists():
        raise FileExistsError(f"one-shot decision already exists: {decision_path}")
    primary_cells = pd.read_parquet(SOURCE_CELLS)
    full_panel, screen, quality = assemble_panel(primary_cells)
    primary_panel = full_panel.loc[~full_panel.smoke_density.isin(["medium", "heavy"])].copy()
    primary = fit_policy_model(primary_panel)
    placebo = fit_policy_model(
        primary_panel.loc[primary_panel.hour_utc.lt(POST)],
        post_date=pd.Timestamp("2024-01-01", tz="UTC"), seed=20250729,
    )
    _, _, _ = primary, placebo, quality
    future_panel, _, _ = assemble_panel(primary_cells, activity_shift_hours=-6)
    future = fit_policy_model(future_panel.loc[~future_panel.smoke_density.isin(["medium", "heavy"])], seed=20250730)
    rotated_panel, _, _ = assemble_panel(primary_cells, rotate_degrees=180)
    rotated = fit_policy_model(rotated_panel.loc[~rotated_panel.smoke_density.isin(["medium", "heavy"])], seed=20250731)
    moving_panel = primary_panel.copy()
    moving_panel["terminal_tanker_stationary"] = moving_panel.terminal_tanker_moving
    moving = fit_policy_model(moving_panel, seed=20250732)
    leave_one_out = {
        site: fit_policy_model(primary_panel.loc[primary_panel.site_id.ne(site)], seed=20250800 + index)
        for index, site in enumerate(sorted(primary_panel.site_id.unique()))
    }
    smoke_sensitivities = {
        "exclude_all": fit_policy_model(full_panel.loc[full_panel.smoke_density.isna()], seed=20250901),
        "full_calendar": fit_policy_model(full_panel, seed=20250902),
    }
    activity_sensitivities = {}
    sensitivity_paths = {
        "radius_0p75_cap_2": ROOT / "data/processed/spb_atberth_source_cells_radius_0p75_cap_2.parquet",
        "radius_2p5_cap_2": ROOT / "data/processed/spb_atberth_source_cells_radius_2p5_cap_2.parquet",
        "radius_1p5_cap_1": ROOT / "data/processed/spb_atberth_source_cells_radius_1p5_cap_1.parquet",
    }
    for index, (name, path) in enumerate(sensitivity_paths.items()):
        if not path.exists():
            raise FileNotFoundError(f"predeclared activity sensitivity is missing: {path}")
        panel, _, _ = assemble_panel(pd.read_parquet(path))
        panel = panel.loc[~panel.smoke_density.isin(["medium", "heavy"])]
        activity_sensitivities[name] = fit_policy_model(panel, seed=20251000 + index)

    effect = primary["relative_policy_effect_ppb"]
    half = abs(effect) / 2
    def null_and_small(result):
        low, high = result["block7_ci95"]
        return low <= 0 <= high and abs(result["relative_policy_effect_ppb"]) <= half

    loo_values = [item["relative_policy_effect_ppb"] for item in leave_one_out.values()]
    falsifications = {
        "2024_pseudo_policy_null_and_smaller": null_and_small(placebo),
        "future_activity_null_and_smaller": null_and_small(future),
        "rotated_plume_null_and_smaller": null_and_small(rotated),
        "moving_tanker_does_not_reproduce": not (
            moving["relative_policy_effect_ppb"] < 0 and moving["block7_ci95"][1] < 0
        ) and abs(moving["relative_policy_effect_ppb"]) <= abs(effect),
        "leave_one_site_sign_and_influence": all(value < 0 for value in loo_values)
            and all(abs(value - effect) <= half for value in loo_values),
        "activity_sensitivity_sign": all(
            item["relative_policy_effect_ppb"] < 0 for item in activity_sensitivities.values()
        ),
        "smoke_sensitivity_sign": all(
            item["relative_policy_effect_ppb"] < 0 for item in smoke_sensitivities.values()
        ),
    }
    treated_weeks = primary_cells.loc[
        primary_cells.source_class.eq("terminal_tanker_stationary")
    ].hour_utc.dt.to_period("W").nunique()
    expected_weeks = pd.date_range(START, END, freq="W", inclusive="left").size
    support = {
        "source_record_coverage_at_least_85pct": quality["source_record_coverage"] >= 0.85,
        "at_least_three_sites": quality["eligible_sites"] >= MIN_SITES,
        "pre_concurrent_site_hours_at_least_12000": quality["pre_site_hours_before_smoke"] >= MIN_PERIOD_SITE_HOURS,
        "post_concurrent_site_hours_at_least_12000": quality["post_site_hours_before_smoke"] >= MIN_PERIOD_SITE_HOURS,
        "treated_activity_in_at_least_80pct_weeks": treated_weeks / expected_weeks >= 0.80,
    }
    policy = {
        "positive_pre_tanker_response": primary["pre_tanker_response_ppb"] > 0,
        "negative_relative_effect": effect < 0,
        "bootstrap_upper_below_zero": primary["block7_ci95"][1] < 0,
        "nonnegative_implied_post_tanker_response": primary["post_tanker_response_ppb"] >= 0,
        "all_falsifications": all(falsifications.values()),
    }
    supportive = all(support.values()) and all(policy.values())
    lower = primary["block7_ci95"][0]
    bounded_null = (
        all(support.values()) and all(falsifications.values())
        and primary["block7_ci95"][0] <= 0 <= primary["block7_ci95"][1]
        and lower > -0.10 * primary["pre_tanker_response_ppb"]
    )
    decision = {
        "study": "System-level 2025 At-Berth pollution intensity",
        "status": "supportive_policy_response" if supportive else "informative_bounded_null" if bounded_null else "fail_inconclusive",
        "distribution_layer_authorized": bool(supportive or bounded_null),
        "primary": primary,
        "support": support,
        "policy_conditions": policy,
        "falsifications": falsifications,
        "placebo_2024": placebo,
        "future_activity": future,
        "rotated_plume": rotated,
        "moving_tanker": moving,
        "leave_one_site_out": leave_one_out,
        "smoke_sensitivities": smoke_sensitivities,
        "activity_sensitivities": activity_sensitivities,
        "quality": quality,
        "outcome": "EPA AQS hourly NO2 (42602), ppb",
        "compliance_inferred": False,
        "port_specific_effect_inferred": False,
    }
    screen.to_csv(OUT / "availability_screen.csv", index=False, lineterminator="\n")
    primary_panel.to_parquet(OUT / "primary_analysis_panel.parquet", index=False)
    decision_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return decision


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-activity")
    build.add_argument("--memory-limit", default="6GB")
    build.add_argument("--threads", type=int, default=8)
    build.add_argument("--radius-km", type=float, default=PRIMARY_RADIUS_KM)
    build.add_argument("--cap-hours", type=float, default=PRIMARY_CAP_HOURS)
    build.add_argument("--output", type=Path, default=SOURCE_CELLS)
    sub.add_parser("screen-aqs")
    sub.add_parser("run")
    args = parser.parse_args()
    if args.command == "build-activity":
        frame = build_hourly_source_cells(
            output=args.output, terminal_radius_km=args.radius_km,
            interval_cap_hours=args.cap_hours, memory_limit=args.memory_limit, threads=args.threads,
        )
        print(f"wrote {len(frame):,} source-cell hours")
        return
    if args.command == "run":
        print(json.dumps(run_complete(), indent=2))
        return
    aqs, monitors = load_aqs()
    screened, report = screen_sites(aqs, monitors, load_wind())
    OUT.mkdir(parents=True, exist_ok=True)
    report.to_csv(OUT / "availability_screen.csv", index=False, lineterminator="\n")
    print(report.to_string(index=False))
    print(f"eligible observations: {len(screened):,}")


if __name__ == "__main__":
    main()
