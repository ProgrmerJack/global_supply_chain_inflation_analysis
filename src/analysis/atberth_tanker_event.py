"""Preregistered CARB At-Berth tanker intervention: blind gate and H4 inputs.

This module implements the measurement firewall in
``prereg/amendments/2026-07-18_spb_atberth_tanker_intervention.md``.  The gate
may inspect only source coverage, counts, missingness, berth-geometry coverage,
and the frozen 2024 tanker-arrival comparator.  It neither estimates a policy
effect nor infers shore-power/CAECS compliance.

The full NOAA census is scanned with DuckDB under a memory cap.  Only the
eligible tanker MMSIs and one port at a time are materialised in pandas, so the
5.8-GB retained census is never loaded as one frame.

Run after the OSF registration is publicly approved::

    python src/analysis/atberth_tanker_event.py --blind-gate
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import intersects_xy
from shapely.ops import unary_union

try:
    from ..process_ais.port_call_segmentation import (
        assign_port_call_ids,
        assign_sea_to_port_visit_ids,
    )
    from ..governance.access import assert_nature_recovery_unlocked
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from process_ais.port_call_segmentation import (  # type: ignore
        assign_port_call_ids,
        assign_sea_to_port_visit_ids,
    )
    from governance.access import assert_nature_recovery_unlocked  # type: ignore


ROOT = Path(__file__).resolve().parents[2]
PINGS_DIR = ROOT / "data/interim/national_pings"
PINGS_GLOB = (PINGS_DIR / "year=*" / "month=*" / "*.parquet").as_posix()
INGESTION_MANIFEST = PINGS_DIR / "ingestion_manifest.csv"
VESSEL_CHARACTERISTICS = ROOT / "data/processed/vessel_characteristics.csv"
STATE_ZONES = ROOT / "config/geometry/national_state_zones.geojson"
OFFICIAL_2024_ARRIVALS = ROOT / "data/processed/carb_atberth_2024_tanker_arrivals.csv"
EXTERNAL_TIMESTAMP = ROOT / "prereg/studies/spb_atberth/spb_atberth_tanker_external_timestamp.json"
GATE_JSON = ROOT / "results/deep_case_SPB/atberth_tanker_blind_gate.json"
GATE_REPORT = ROOT / "results/deep_case_SPB/atberth_tanker_blind_gate.md"
H4_PANEL_DIR = ROOT / "data/processed/carb_atberth_tanker_panel"
RECOVERY_TERMINALS = ROOT / "config/registries/carb_atberth_spb_tanker_terminals.csv"
RECOVERY_DOMAINS = ROOT / "config/geometry/carb_atberth_recovery_coastal_domains.geojson"
RECOVERY_PINGS_DIR = ROOT / "data/interim/nature_recovery/coastal_pings"
RECOVERY_GATE_JSON = ROOT / "results/confirmatory/nature_recovery/r_g1_call_measurement.json"

REGISTRATION_ID = "w6zsg"
TREATED_PORT = "san_pedro_bay"
REGULATORY_MIN_LENGTH_M = 121.92
RECOVERY_INNER_BUFFER_M = 20_000.0
RECOVERY_OUTER_BUFFER_M = 40_000.0
RECOVERY_EXIT_HYSTERESIS_HOURS = 0.25
RECOVERY_MIN_EXIT_OBSERVATIONS = 2
RECOVERY_TERMINAL_CONTACT_M = 750.0
START_DATE = pd.Timestamp("2017-01-01", tz="UTC")
END_DATE_EXCLUSIVE = pd.Timestamp("2026-01-01", tz="UTC")
GATE_READ_START = pd.Timestamp("2023-12-01", tz="UTC")
PRIMARY_INTERVAL_CAP_HOURS = 2.0
PRIMARY_STATIONARY_SOG = 0.5
INTERVAL_CAP_SENSITIVITIES = (0.5, 2.0, 6.0)
PORT_TIMEZONES = {
    "baltimore_md": "America/New_York",
    "boston_ma": "America/New_York",
    "charleston_sc": "America/New_York",
    "houston_tx": "America/Chicago",
    "jacksonville_fl": "America/New_York",
    "miami_fl": "America/New_York",
    "mobile_al": "America/Chicago",
    "new_orleans_la": "America/Chicago",
    "new_york_new_jersey": "America/New_York",
    "norfolk_newport_news_va": "America/New_York",
    "philadelphia_pa": "America/New_York",
    "port_everglades_fl": "America/New_York",
    "san_pedro_bay": "America/Los_Angeles",
    "savannah_ga": "America/New_York",
    "wilmington_nc": "America/New_York",
}


def sha256_file(path: Path | str) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_public_registration(path: Path | str = EXTERNAL_TIMESTAMP) -> dict:
    """Fail closed until the exact prospective OSF registration is public."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"public At-Berth registration receipt is missing: {path}")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    state = receipt.get("osf_state_at_verification", {})
    if receipt.get("registration_id") != REGISTRATION_ID:
        raise RuntimeError("At-Berth registration receipt has the wrong registration id")
    if not state.get("public") or state.get("pending_registration_approval"):
        raise RuntimeError("At-Berth registration is not publicly approved")
    return receipt


def require_passing_blind_gate(path: Path | str = GATE_JSON) -> dict:
    """Prevent construction of any treatment panel after a failed/missing gate."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"At-Berth blind-gate decision is missing: {path}")
    decision = json.loads(path.read_text(encoding="utf-8"))
    if decision.get("status") != "pass" or not decision.get("effect_estimation_authorized"):
        raise RuntimeError("At-Berth blind gate did not authorize effect estimation")
    return decision


def source_day_coverage(
    manifest_path: Path | str = INGESTION_MANIFEST,
    pings_dir: Path | str = PINGS_DIR,
    *,
    start: str = "2017-01-01",
    end: str = "2025-12-31",
) -> tuple[dict, pd.DataFrame]:
    """Resolve append-only ingestion attempts into one auditable status per day.

    A date is complete when at least one manifest attempt is ``ok`` and its
    deterministic retained parquet exists.  Earlier failed attempts remain
    counted in the audit but do not overwrite a later successful retry.
    """
    manifest = pd.read_csv(manifest_path, dtype={"date": "string", "status": "string"})
    required = {"date", "status"}
    if missing := required - set(manifest.columns):
        raise ValueError(f"ingestion manifest missing columns: {sorted(missing)}")
    manifest["date"] = pd.to_datetime(manifest["date"], errors="coerce").dt.date
    if manifest["date"].isna().any():
        raise ValueError("ingestion manifest contains an invalid date")

    expected = pd.date_range(start, end, freq="D")
    successful = set(manifest.loc[manifest.status.eq("ok"), "date"])
    files = {
        pd.to_datetime(path.stem.removeprefix("pings_"), errors="coerce").date()
        for path in Path(pings_dir).glob("year=*/month=*/pings_*.parquet")
    }
    rows = pd.DataFrame({"date": expected})
    rows["manifest_ok"] = rows.date.dt.date.isin(successful)
    rows["parquet_present"] = rows.date.dt.date.isin(files)
    rows["source_day_ok"] = rows.manifest_ok & rows.parquet_present
    rows["year_month"] = rows.date.dt.strftime("%Y-%m")
    monthly = rows.groupby("year_month", as_index=False).agg(
        expected_days=("date", "size"),
        source_days_ok=("source_day_ok", "sum"),
    )
    monthly["source_day_coverage"] = monthly.source_days_ok / monthly.expected_days
    missing_dates = rows.loc[~rows.source_day_ok, "date"].dt.strftime("%Y-%m-%d").tolist()
    summary = {
        "expected_dates": int(len(rows)),
        "dates_ok": int(rows.source_day_ok.sum()),
        "all_dates_ok": not missing_dates,
        "missing_dates": missing_dates,
        "minimum_month_coverage": float(monthly.source_day_coverage.min()),
        "months_below_95pct": monthly.loc[
            monthly.source_day_coverage.lt(0.95), "year_month"
        ].tolist(),
        "prior_non_ok_attempts": int((~manifest.status.eq("ok")).sum()),
    }
    return summary, monthly


def classify_tanker_population(
    static_types: pd.DataFrame,
    ping_types: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the frozen static-first tanker rule with disagreement exclusion."""
    static = static_types.loc[:, ["mmsi", "vessel_type"]].rename(
        columns={"vessel_type": "static_vessel_type"}
    )
    ping = ping_types.loc[:, ["mmsi", "vessel_type"]].rename(
        columns={"vessel_type": "ping_vessel_type"}
    )
    ledger = static.merge(ping, on="mmsi", how="outer", validate="one_to_one")
    for column in ("static_vessel_type", "ping_vessel_type"):
        ledger[column] = pd.to_numeric(ledger[column], errors="coerce")
    static_known = ledger.static_vessel_type.notna()
    ping_known = ledger.ping_vessel_type.notna()
    static_tanker = ledger.static_vessel_type.between(80, 89, inclusive="both")
    ping_tanker = ledger.ping_vessel_type.between(80, 89, inclusive="both")
    ledger["tanker_status_disagreement"] = static_known & ping_known & static_tanker.ne(ping_tanker)
    ledger["selected_vessel_type"] = ledger.static_vessel_type.where(
        static_known, ledger.ping_vessel_type
    )
    ledger["is_tanker"] = (
        ~ledger.tanker_status_disagreement
        & ledger.selected_vessel_type.between(80, 89, inclusive="both")
    )
    ledger["type_source"] = np.select(
        [static_known, ~static_known & ping_known], ["vessel_characteristics", "census_modal"], default="missing"
    )
    return ledger.sort_values("mmsi", kind="stable").reset_index(drop=True)


def classify_regulatory_tanker_population(
    static_types: pd.DataFrame,
    ping_types: pd.DataFrame,
    *,
    minimum_length_m: float = REGULATORY_MIN_LENGTH_M,
) -> pd.DataFrame:
    """Identify the observable CARB ocean-going tanker population.

    CARB defines an ocean-going vessel by a disjunctive length, gross-tonnage
    or engine-displacement rule. NOAA AIS exposes length but not auditable gross
    tonnage or cylinder displacement here. The confirmatory population is
    therefore tanker type 80--89 with observed length at least 400 ft
    (121.92 m). Tankers with shorter or missing length remain in an explicitly
    labelled NMEA-only sensitivity; they are never silently treated as
    regulatory-eligible.
    """
    if minimum_length_m <= 0:
        raise ValueError("minimum regulatory tanker length must be positive")
    if "length_m" not in ping_types.columns:
        raise ValueError("regulatory tanker classification requires recovered-source length_m")
    ledger = classify_tanker_population(static_types, ping_types)
    dimensions = ping_types.loc[:, ["mmsi", "length_m"]].drop_duplicates("mmsi")
    dimensions["length_m"] = pd.to_numeric(dimensions.length_m, errors="coerce")
    ledger = ledger.merge(dimensions, on="mmsi", how="left", validate="one_to_one")
    ledger["nmea_tanker_sensitivity"] = ledger.is_tanker
    ledger["regulatory_length_observed"] = ledger.length_m.notna()
    ledger["regulatory_eligible_tanker"] = (
        ledger.is_tanker
        & ledger.length_m.ge(minimum_length_m)
    )
    ledger["regulatory_exclusion_reason"] = np.select(
        [
            ledger.tanker_status_disagreement,
            ~ledger.is_tanker,
            ledger.length_m.isna(),
            ledger.length_m.lt(minimum_length_m),
        ],
        [
            "tanker_type_disagreement",
            "not_tanker",
            "missing_regulatory_length",
            "below_400ft_observable_rule",
        ],
        default="eligible_observed_length",
    )
    return ledger.sort_values("mmsi", kind="stable").reset_index(drop=True)


def recovery_domain_geometries(
    path: Path | str = RECOVERY_DOMAINS,
) -> dict[str, dict[str, object]]:
    """Load exactly one inner and outer frozen coastal domain per port."""
    domains = gpd.read_file(path).to_crs("EPSG:4326")
    required = {"port_complex_id", "domain", "geometry"}
    if missing := required - set(domains.columns):
        raise ValueError(f"recovery coastal domains missing columns: {sorted(missing)}")
    if set(domains.domain) != {"coastal_inner", "coastal_outer"}:
        raise ValueError("recovery coastal domains require inner and outer rows")
    if domains.duplicated(["port_complex_id", "domain"]).any():
        raise ValueError("recovery coastal domains contain duplicate port-domain rows")
    return {
        port: group.set_index("domain").geometry.to_dict()
        for port, group in domains.groupby("port_complex_id", sort=True)
    }


def tanker_terminal_points(
    path: Path | str = RECOVERY_TERMINALS,
    *,
    verify_sources: bool = True,
) -> gpd.GeoDataFrame:
    """Load plan-published SPB tanker points and optionally verify source PDFs."""
    table = pd.read_csv(path)
    required = {
        "terminal_id", "port", "latitude", "longitude", "source_artifact",
        "source_sha256", "assignment_eligible",
    }
    if missing := required - set(table.columns):
        raise ValueError(f"SPB tanker terminals missing columns: {sorted(missing)}")
    table = table.loc[table.assignment_eligible.eq(1)].copy()
    if table.empty or table.terminal_id.duplicated().any():
        raise ValueError("SPB tanker terminals require unique eligible terminal rows")
    if verify_sources:
        for artifact, expected in table.groupby("source_artifact").source_sha256.first().items():
            source = ROOT / "data/external/carb_atberth" / artifact
            if sha256_file(source) != expected:
                raise ValueError(f"SPB tanker-terminal source hash mismatch: {artifact}")
    return gpd.GeoDataFrame(
        table,
        geometry=gpd.points_from_xy(table.longitude, table.latitude),
        crs="EPSG:4326",
    ).sort_values("terminal_id", kind="stable").reset_index(drop=True)


def terminal_contact_geometry(
    terminals: gpd.GeoDataFrame,
    *,
    buffer_m: float = RECOVERY_TERMINAL_CONTACT_M,
) -> object:
    """Union fixed-radius buffers around plan-published tanker points."""
    if buffer_m <= 0:
        raise ValueError("terminal contact buffer must be positive")
    projected = terminals.to_crs("EPSG:32611")
    return unary_union(projected.geometry.buffer(buffer_m).tolist())


def mark_recovery_trajectory_zones(
    pings: pd.DataFrame,
    *,
    inner_geometry: object,
    outer_geometry: object,
    contact_geometry: object,
    contact_geometry_crs: str = "EPSG:32611",
) -> pd.Series:
    """Classify retained coastal pings without using speed or AIS status."""
    required = {"lon", "lat"}
    if missing := required - set(pings.columns):
        raise ValueError(f"recovery trajectory pings missing columns: {sorted(missing)}")
    lon = pd.to_numeric(pings.lon, errors="coerce").to_numpy(dtype=float)
    lat = pd.to_numeric(pings.lat, errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(lon) & np.isfinite(lat)
    inside_outer = np.zeros(len(pings), dtype=bool)
    inside_inner = np.zeros(len(pings), dtype=bool)
    inside_contact = np.zeros(len(pings), dtype=bool)
    # Keep the frozen coastal polygons in their native CRS, matching ingestion exactly.
    # Reprojecting their sparse boundary segments can move the boundary across retained pings.
    inside_outer[finite] = intersects_xy(outer_geometry, lon[finite], lat[finite])
    inside_inner[finite] = intersects_xy(inner_geometry, lon[finite], lat[finite])
    contact_points = gpd.GeoSeries(
        gpd.points_from_xy(lon[finite], lat[finite]), crs="EPSG:4326"
    ).to_crs(contact_geometry_crs)
    inside_contact[finite] = intersects_xy(
        contact_geometry,
        contact_points.x.to_numpy(dtype=float),
        contact_points.y.to_numpy(dtype=float),
    )
    if not inside_outer[finite].all():
        raise ValueError("recovery pings fall outside their assigned outer domain")
    zones = pd.Series("outside", index=pings.index, dtype="string")
    zones.loc[inside_inner] = "coastal"
    zones.loc[inside_contact] = "port_contact"
    return zones


def attach_spb_terminal_assignments(
    pings: pd.DataFrame,
    terminals: gpd.GeoDataFrame,
    *,
    max_distance_m: float = RECOVERY_TERMINAL_CONTACT_M,
) -> pd.DataFrame:
    """Assign each SPB ping to the nearest frozen tanker point within radius."""
    if max_distance_m <= 0:
        raise ValueError("terminal assignment distance must be positive")
    required = {"lon", "lat"}
    if missing := required - set(pings.columns):
        raise ValueError(f"terminal-assignment pings missing columns: {sorted(missing)}")
    ordered = terminals.sort_values("terminal_id", kind="stable").to_crs("EPSG:32611")
    points = gpd.GeoSeries(
        gpd.points_from_xy(
            pd.to_numeric(pings.lon, errors="coerce"),
            pd.to_numeric(pings.lat, errors="coerce"),
        ),
        crs="EPSG:4326",
        index=pings.index,
    ).to_crs("EPSG:32611")
    distances = np.column_stack([
        points.distance(geometry).to_numpy(dtype=float)
        for geometry in ordered.geometry
    ])
    nearest = np.argmin(distances, axis=1)
    minimum = distances[np.arange(len(points)), nearest]
    assigned = minimum <= max_distance_m
    out = pings.copy()
    out["terminal_id"] = pd.Series(pd.NA, index=out.index, dtype="string")
    out["terminal_port"] = pd.Series(pd.NA, index=out.index, dtype="string")
    out.loc[assigned, "terminal_id"] = ordered.iloc[nearest[assigned]].terminal_id.to_numpy()
    out.loc[assigned, "terminal_port"] = ordered.iloc[nearest[assigned]].port.to_numpy()
    out["terminal_distance_m"] = minimum
    return out


def build_spb_recovery_visits(
    pings: pd.DataFrame,
    terminals: gpd.GeoDataFrame,
    *,
    exit_hysteresis_hours: float = RECOVERY_EXIT_HYSTERESIS_HOURS,
    min_exit_observations: int = RECOVERY_MIN_EXIT_OBSERVATIONS,
    terminal_distance_m: float = RECOVERY_TERMINAL_CONTACT_M,
) -> pd.DataFrame:
    """Build complete SPB sea-to-terminal visits from already zoned pings."""
    required = {
        "mmsi", "timestamp", "port_complex_id", "trajectory_zone", "lon", "lat",
    }
    if missing := required - set(pings.columns):
        raise ValueError(f"SPB recovery pings missing columns: {sorted(missing)}")
    zoned = assign_sea_to_port_visit_ids(
        pings,
        exit_hysteresis_hours=exit_hysteresis_hours,
        min_exit_observations=min_exit_observations,
    )
    assigned = attach_spb_terminal_assignments(
        zoned.loc[zoned.visit_id.notna()].copy(),
        terminals,
        max_distance_m=terminal_distance_m,
    )
    if assigned.empty:
        return pd.DataFrame(
            columns=[
                "visit_id", "mmsi", "arrival_timestamp", "terminal_contact_timestamp",
                "terminal_id", "terminal_port", "visit_valid", "visit_left_censored",
                "visit_right_censored", "complete_regulatory_visit", "n_pings",
            ]
        )
    assigned = assigned.sort_values(["visit_id", "timestamp"], kind="stable")
    first_contact = (
        assigned.loc[assigned.terminal_id.notna()]
        .drop_duplicates("visit_id", keep="first")
        .set_index("visit_id")
    )
    visits = assigned.groupby("visit_id", as_index=False).agg(
        mmsi=("mmsi", "first"),
        arrival_timestamp=("timestamp", "min"),
        visit_valid=("visit_valid", "first"),
        visit_left_censored=("visit_left_censored", "first"),
        visit_right_censored=("visit_right_censored", "first"),
        n_pings=("timestamp", "size"),
    )
    visits["terminal_contact_timestamp"] = visits.visit_id.map(first_contact.timestamp)
    visits["terminal_id"] = visits.visit_id.map(first_contact.terminal_id).astype("string")
    visits["terminal_port"] = visits.visit_id.map(first_contact.terminal_port).astype("string")
    visits["complete_regulatory_visit"] = (
        visits.visit_valid
        & ~visits.visit_left_censored
        & ~visits.visit_right_censored
        & visits.terminal_id.notna()
    )
    return visits


def build_generic_recovery_visits(
    pings: pd.DataFrame,
    *,
    exit_hysteresis_hours: float = RECOVERY_EXIT_HYSTERESIS_HOURS,
    min_exit_observations: int = RECOVERY_MIN_EXIT_OBSERVATIONS,
) -> pd.DataFrame:
    """Aggregate complete sea-to-port visits where terminal identity is absent."""
    zoned = assign_sea_to_port_visit_ids(
        pings,
        exit_hysteresis_hours=exit_hysteresis_hours,
        min_exit_observations=min_exit_observations,
    )
    assigned = zoned.loc[zoned.visit_id.notna()].copy()
    if assigned.empty:
        return pd.DataFrame(
            columns=[
                "visit_id", "mmsi", "port_complex_id", "arrival_timestamp",
                "port_contact_timestamp", "visit_valid", "visit_left_censored",
                "visit_right_censored", "complete_regulatory_visit", "n_pings",
            ]
        )
    contact = (
        assigned.loc[assigned.trajectory_zone.eq("port_contact")]
        .groupby("visit_id").timestamp.min()
    )
    visits = assigned.groupby("visit_id", as_index=False).agg(
        mmsi=("mmsi", "first"),
        port_complex_id=("port_complex_id", "first"),
        arrival_timestamp=("timestamp", "min"),
        visit_valid=("visit_valid", "first"),
        visit_left_censored=("visit_left_censored", "first"),
        visit_right_censored=("visit_right_censored", "first"),
        n_pings=("timestamp", "size"),
    )
    visits["port_contact_timestamp"] = visits.visit_id.map(contact)
    visits["complete_regulatory_visit"] = (
        visits.visit_valid
        & ~visits.visit_left_censored
        & ~visits.visit_right_censored
        & visits.port_contact_timestamp.notna()
    )
    return visits


def evaluate_recovery_call_gate(
    spb_visits: pd.DataFrame,
    donor_visits: pd.DataFrame,
    *,
    source_summary: dict,
    official: dict,
    population_summary: dict,
) -> dict:
    """Evaluate the prospectively frozen R-G1 call-measurement conditions."""
    required = {
        "terminal_contact_timestamp", "terminal_port", "complete_regulatory_visit",
    }
    if missing := required - set(spb_visits.columns):
        raise ValueError(f"R-G1 SPB visits missing columns: {sorted(missing)}")
    spb = spb_visits.copy()
    spb["contact_year"] = pd.to_datetime(
        spb.terminal_contact_timestamp, errors="coerce", utc=True
    ).dt.year
    candidates_2024 = spb.loc[spb.contact_year.eq(2024)]
    complete_2024 = candidates_2024.loc[candidates_2024.complete_regulatory_visit]
    ais_by_port = (
        complete_2024.groupby("terminal_port").size().astype(int).to_dict()
    )
    official_by_port = {
        "Los Angeles": int(official["port_totals"]["Port of Los Angeles"]),
        "Long Beach": int(official["port_totals"]["Port of Long Beach"]),
    }
    errors_by_port = {
        port: abs(int(ais_by_port.get(port, 0)) - count) / count
        for port, count in official_by_port.items()
    }
    ais_total = int(len(complete_2024))
    official_total = int(official["spb_total"])
    combined_error = abs(ais_total - official_total) / official_total
    complete_share = (
        float(candidates_2024.complete_regulatory_visit.mean())
        if len(candidates_2024)
        else 0.0
    )

    donor = donor_visits.copy()
    donor["contact_year"] = pd.to_datetime(
        donor.port_contact_timestamp, errors="coerce", utc=True
    ).dt.year
    donor_counts = (
        donor.loc[
            donor.complete_regulatory_visit & donor.contact_year.isin([2024, 2025])
        ]
        .groupby(["port_complex_id", "contact_year"])
        .size()
        .unstack(fill_value=0)
    )
    for year in (2024, 2025):
        if year not in donor_counts:
            donor_counts[year] = 0
    eligible_donors = donor_counts.index[
        (donor_counts[2024] >= 20) & (donor_counts[2025] >= 20)
    ].tolist()
    spb_2025 = int(
        (
            spb.complete_regulatory_visit
            & spb.contact_year.eq(2025)
        ).sum()
    )

    conditions = {
        "all_2017_2025_source_dates_resolved": bool(source_summary["all_dates_ok"]),
        "every_month_at_least_95pct": not source_summary["months_below_95pct"],
        "observable_regulatory_length_coverage_at_least_90pct": (
            population_summary["regulatory_length_coverage"] >= 0.90
        ),
        "complete_2024_visit_share_at_least_95pct": complete_share >= 0.95,
        "combined_2024_arrival_error_at_most_15pct": combined_error <= 0.15,
        "each_port_2024_arrival_error_at_most_25pct": all(
            error <= 0.25 for error in errors_by_port.values()
        ),
        "spb_at_least_50_complete_visits_in_2025": spb_2025 >= 50,
        "at_least_five_donors_with_20_visits_each_year": len(eligible_donors) >= 5,
    }
    passed = all(conditions.values())
    return {
        "gate": "R-G1 corrected regulatory tanker sea-to-port call measurement",
        "status": "pass" if passed else "fail",
        "effect_estimation_authorized": passed,
        "source_coverage": source_summary,
        "population": population_summary,
        "official_2024_comparator": {
            **official,
            "ais_complete_regulatory_visits": ais_total,
            "ais_by_terminal_port": ais_by_port,
            "absolute_fractional_error_combined": combined_error,
            "absolute_fractional_error_by_port": errors_by_port,
            "candidate_visits": int(len(candidates_2024)),
            "complete_visit_share": complete_share,
        },
        "sample_adequacy": {
            "spb_complete_visits_2025": spb_2025,
            "eligible_donor_count": len(eligible_donors),
            "eligible_donors": eligible_donors,
        },
        "conditions": conditions,
        "treatment_effects_opened": False,
        "compliance_validated": False,
        "emissions_validated": False,
    }


def build_recovery_gate_visits(
    *,
    memory_limit: str = "4GB",
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Build only 2024-comparator/2025-adequacy visits from guarded pings."""
    assert_nature_recovery_unlocked(RECOVERY_PINGS_DIR)
    parquet_glob = (
        RECOVERY_PINGS_DIR / "year=*" / "month=*" / "*.parquet"
    ).as_posix()
    if not any(RECOVERY_PINGS_DIR.glob("year=*/month=*/*.parquet")):
        raise FileNotFoundError("guarded recovery coastal pings are missing")
    static = pd.read_csv(VESSEL_CHARACTERISTICS)
    con = _duckdb(memory_limit)
    try:
        ping_type = modal_ping_types(con, parquet_glob)
        recovered_length = con.execute(f"""
            SELECT mmsi,
                   median(length) FILTER (WHERE length > 0) AS length_m
            FROM read_parquet('{parquet_glob}', hive_partitioning=true)
            WHERE mmsi IS NOT NULL
            GROUP BY mmsi
        """).df()
        ping_type = ping_type.merge(
            recovered_length, on="mmsi", how="left", validate="one_to_one"
        )
        population = classify_regulatory_tanker_population(static, ping_type)
        eligible = population.loc[
            population.regulatory_eligible_tanker, ["mmsi", "length_m"]
        ]
        con.register("eligible_recovery_tankers", eligible)
        domains = recovery_domain_geometries()
        berth = berth_geometries()
        terminals = tanker_terminal_points()
        terminal_geometry = terminal_contact_geometry(terminals)
        spb_parts = []
        donor_parts = []
        for port in sorted(domains):
            query = f"""
                SELECT p.mmsi, p.timestamp, p.lon, p.lat, p.sog,
                       p.port_complex_id, e.length_m
                FROM read_parquet('{parquet_glob}', hive_partitioning=true) p
                INNER JOIN eligible_recovery_tankers e USING (mmsi)
                WHERE p.port_complex_id = ?
                  AND p.timestamp >= TIMESTAMPTZ '2023-12-01 00:00:00+00'
                  AND p.timestamp < TIMESTAMPTZ '2026-02-01 00:00:00+00'
                ORDER BY p.mmsi, p.timestamp
            """
            pings = con.execute(query, [port]).df()
            if pings.empty:
                continue
            pings["timestamp"] = pd.to_datetime(pings.timestamp, utc=True)
            contact = terminal_geometry if port == TREATED_PORT else berth[port]
            contact_crs = "EPSG:32611" if port == TREATED_PORT else "EPSG:4326"
            pings["trajectory_zone"] = mark_recovery_trajectory_zones(
                pings,
                inner_geometry=domains[port]["coastal_inner"],
                outer_geometry=domains[port]["coastal_outer"],
                contact_geometry=contact,
                contact_geometry_crs=contact_crs,
            )
            if port == TREATED_PORT:
                visits = build_spb_recovery_visits(pings, terminals)
                spb_parts.append(visits)
            else:
                donor_parts.append(build_generic_recovery_visits(pings))
        spb_visits = (
            pd.concat(spb_parts, ignore_index=True)
            if spb_parts else pd.DataFrame()
        )
        donor_visits = (
            pd.concat(donor_parts, ignore_index=True)
            if donor_parts else pd.DataFrame()
        )
        nmea = population.loc[population.nmea_tanker_sensitivity]
        population_summary = {
            "nmea_tanker_mmsis": int(len(nmea)),
            "regulatory_length_observed_mmsis": int(
                nmea.regulatory_length_observed.sum()
            ),
            "regulatory_eligible_mmsis": int(
                population.regulatory_eligible_tanker.sum()
            ),
            "regulatory_length_coverage": (
                float(nmea.regulatory_length_observed.mean())
                if len(nmea) else 0.0
            ),
            "observable_rule": "NMEA 80-89 and length >=121.92m",
            "unobservable_gt_or_engine_eligibility_imputed": False,
        }
        return spb_visits, donor_visits, population_summary
    finally:
        con.close()


def run_recovery_call_gate(*, memory_limit: str = "4GB") -> dict:
    """Fire the independent, registration-guarded R-G1 gate exactly once."""
    assert_nature_recovery_unlocked(RECOVERY_GATE_JSON)
    if RECOVERY_GATE_JSON.exists():
        raise FileExistsError(f"R-G1 is one-shot and already exists: {RECOVERY_GATE_JSON}")
    source, _ = source_day_coverage(
        RECOVERY_PINGS_DIR / "ingestion_manifest.csv",
        RECOVERY_PINGS_DIR,
        start="2017-01-01",
        end="2025-12-31",
    )
    spb, donors, population = build_recovery_gate_visits(
        memory_limit=memory_limit
    )
    decision = evaluate_recovery_call_gate(
        spb,
        donors,
        source_summary=source,
        official=official_tanker_arrivals(),
        population_summary=population,
    )
    decision["run_once_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    RECOVERY_GATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    RECOVERY_GATE_JSON.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return decision


def verify_recovery_call_gate(*, memory_limit: str = "4GB") -> dict:
    """Recompute R-G1 from the frozen inputs and diff it against the stored decision.

    Added 2026-08-06. R-G1 is one-shot, so the only check previously available on Paper C's claims
    M08-M10 (the 1.735% combined and 29.371% Port of Los Angeles arrival errors) was re-hashing the
    file that states them. This path re-runs the identical visit construction and gate arithmetic and
    compares every numeric field. It writes nothing and cannot refire the gate.

    Run: python src/analysis/atberth_tanker_event.py --verify-recovery-gate
    """
    if not RECOVERY_GATE_JSON.exists():
        raise RuntimeError("nothing to verify: R-G1 has not been fired")
    stored = json.loads(RECOVERY_GATE_JSON.read_text(encoding="utf-8"))

    source, _ = source_day_coverage(
        RECOVERY_PINGS_DIR / "ingestion_manifest.csv",
        RECOVERY_PINGS_DIR,
        start="2017-01-01",
        end="2025-12-31",
    )
    spb, donors, population = build_recovery_gate_visits(memory_limit=memory_limit)
    recomputed = evaluate_recovery_call_gate(
        spb,
        donors,
        source_summary=source,
        official=official_tanker_arrivals(),
        population_summary=population,
    )

    def flat(d, prefix=""):
        out = {}
        for k, v in d.items():
            if k == "run_once_at_utc":      # wall-clock stamp; necessarily differs
                continue
            if isinstance(v, dict):
                out.update(flat(v, f"{prefix}{k}."))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{prefix}{k}"] = float(v)
        return out

    a, b = flat(stored), flat(recomputed)
    shared = sorted(set(a) & set(b))
    diffs = [(k, a[k], b[k]) for k in shared if abs(a[k] - b[k]) > 1e-9]
    print("=== R-G1 read-only verification ===")
    print(f"  compared {len(shared)} numeric fields against the stored decision")
    for k in sorted(shared):
        if "error" in k or "arriv" in k:
            print(f"    {k:46s} stored {a[k]:.6f}   recomputed {b[k]:.6f}")
    if diffs:
        for k, x, y in diffs[:10]:
            print(f"  MISMATCH {k}: stored {x!r} recomputed {y!r}")
        raise RuntimeError(f"{len(diffs)} field(s) do not reproduce from the frozen inputs")
    print("  PASS: every numeric field reproduces exactly. Gate NOT refired; nothing written.")
    return recomputed


def modal_ping_types(con: duckdb.DuckDBPyConnection, parquet_glob: str = PINGS_GLOB) -> pd.DataFrame:
    """Return deterministic per-MMSI modal ping type (lowest code breaks ties)."""
    query = f"""
        WITH counts AS (
            SELECT mmsi, CAST(vessel_type AS INTEGER) AS vessel_type, count(*) AS n
            FROM read_parquet('{parquet_glob}', hive_partitioning=true)
            WHERE mmsi IS NOT NULL AND vessel_type IS NOT NULL
            GROUP BY 1, 2
        ), ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY mmsi ORDER BY n DESC, vessel_type ASC
            ) AS rank
            FROM counts
        )
        SELECT mmsi, vessel_type FROM ranked WHERE rank = 1 ORDER BY mmsi
    """
    return con.execute(query).df()


def berth_geometries(path: Path | str = STATE_ZONES) -> dict[str, object]:
    """Load one unioned official berth-candidate geometry per frozen complex."""
    zones = gpd.read_file(path).to_crs("EPSG:4326")
    required = {"port_complex_id", "state", "geometry"}
    if missing := required - set(zones.columns):
        raise ValueError(f"state zones missing columns: {sorted(missing)}")
    berth = zones.loc[zones.state.eq("berth")]
    return {
        port: unary_union(group.geometry.tolist())
        for port, group in berth.groupby("port_complex_id", sort=True)
    }


def mark_berth_pings(pings: pd.DataFrame, geometry: object) -> pd.Series:
    """Return a boundary-inclusive berth flag for finite lon/lat points."""
    lon = pd.to_numeric(pings["lon"], errors="coerce").to_numpy(dtype=float)
    lat = pd.to_numeric(pings["lat"], errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(lon) & np.isfinite(lat)
    inside = np.zeros(len(pings), dtype=bool)
    inside[finite] = intersects_xy(geometry, lon[finite], lat[finite])
    return pd.Series(inside, index=pings.index, dtype=bool)


def call_interval_metrics(
    pings: pd.DataFrame,
    *,
    interval_cap_hours: float = PRIMARY_INTERVAL_CAP_HOURS,
    stationary_sog: float = PRIMARY_STATIONARY_SOG,
) -> pd.DataFrame:
    """Build physical call metrics under the frozen 24-hour/interval rules."""
    if interval_cap_hours <= 0 or stationary_sog <= 0:
        raise ValueError("interval cap and stationary threshold must be positive")
    required = {"mmsi", "timestamp", "port_complex_id", "sog", "berth_inside"}
    if missing := required - set(pings.columns):
        raise ValueError(f"tanker call pings missing columns: {sorted(missing)}")
    calls = assign_port_call_ids(pings)
    calls["sog"] = pd.to_numeric(calls.sog, errors="coerce")
    calls["berth_inside"] = calls.berth_inside.fillna(False).astype(bool)
    grouped = calls.groupby("call_id", sort=False)
    calls["next_timestamp"] = grouped.timestamp.shift(-1)
    raw_hours = (calls.next_timestamp - calls.timestamp).dt.total_seconds() / 3600.0
    valid = raw_hours.gt(0) & np.isfinite(raw_hours)
    calls["interval_hours"] = raw_hours.where(valid).clip(upper=interval_cap_hours)
    calls["unresolved_sog_hours"] = calls.interval_hours.where(calls.sog.isna(), 0.0).fillna(0.0)
    stationary = calls.sog.notna() & calls.sog.lt(stationary_sog)
    calls["berth_stationary_hours"] = calls.interval_hours.where(
        stationary & calls.berth_inside, 0.0
    ).fillna(0.0)
    calls["outside_berth_stationary_hours"] = calls.interval_hours.where(
        stationary & ~calls.berth_inside, 0.0
    ).fillna(0.0)
    calls["moving_10kt_hours"] = calls.interval_hours.where(calls.sog.ge(10), 0.0).fillna(0.0)
    calls["valid_interval"] = valid

    result = grouped.agg(
        port_complex_id=("port_complex_id", "first"),
        mmsi=("mmsi", "first"),
        first_timestamp=("timestamp", "min"),
        last_timestamp=("timestamp", "max"),
        n_pings=("timestamp", "size"),
        valid_intervals=("valid_interval", "sum"),
        interval_hours=("interval_hours", "sum"),
        unresolved_sog_hours=("unresolved_sog_hours", "sum"),
        berth_stationary_hours=("berth_stationary_hours", "sum"),
        outside_berth_stationary_hours=("outside_berth_stationary_hours", "sum"),
        moving_10kt_hours=("moving_10kt_hours", "sum"),
    ).reset_index()
    result["elapsed_hours"] = (
        result.last_timestamp - result.first_timestamp
    ).dt.total_seconds() / 3600.0
    result["year_month"] = result.first_timestamp.dt.strftime("%Y-%m")
    result["year"] = result.first_timestamp.dt.year
    result["resolved_call"] = result.valid_intervals.gt(0) & result.interval_hours.gt(0)
    result["has_berth_stationary_interval"] = result.berth_stationary_hours.gt(0)
    return result


def add_call_covariates(calls: pd.DataFrame, vessel_characteristics: pd.DataFrame) -> pd.DataFrame:
    """Attach frozen vessel dimensions and calendar-safe arrival covariates."""
    dimensions = vessel_characteristics.loc[:, ["mmsi", "length_m", "width_m", "draft_m"]].drop_duplicates("mmsi")
    out = calls.merge(dimensions, on="mmsi", how="left", validate="many_to_one")
    out = out.sort_values(["port_complex_id", "mmsi", "first_timestamp"], kind="stable").reset_index(drop=True)
    out["new_to_port_vessel"] = ~out.duplicated(["port_complex_id", "mmsi"], keep="first")
    out["arrival_local_hour"] = np.nan
    out["weekend_arrival"] = False
    missing_timezones = sorted(set(out.port_complex_id) - set(PORT_TIMEZONES))
    if missing_timezones:
        raise ValueError("missing frozen port timezones: " + ", ".join(missing_timezones))
    for port, timezone in PORT_TIMEZONES.items():
        mask = out.port_complex_id.eq(port)
        if not mask.any():
            continue
        local = out.loc[mask, "first_timestamp"].dt.tz_convert(timezone)
        out.loc[mask, "arrival_local_hour"] = (
            local.dt.hour + local.dt.minute / 60.0 + local.dt.second / 3600.0
        )
        out.loc[mask, "weekend_arrival"] = local.dt.dayofweek.ge(5).to_numpy()
    return out


def aggregate_monthly_call_panel(calls: pd.DataFrame) -> pd.DataFrame:
    """Aggregate audited call records to the registered port-month outcomes."""
    required = {
        "port_complex_id", "year_month", "mmsi", "resolved_call", "interval_hours",
        "berth_stationary_hours", "outside_berth_stationary_hours", "elapsed_hours",
        "moving_10kt_hours", "unresolved_sog_hours", "length_m", "width_m", "draft_m",
        "new_to_port_vessel", "arrival_local_hour", "weekend_arrival",
    }
    if missing := required - set(calls.columns):
        raise ValueError(f"monthly tanker panel missing call columns: {sorted(missing)}")
    keys = ["port_complex_id", "year_month"]
    base = calls.groupby(keys, as_index=False).agg(
        tanker_calls=("mmsi", "size"),
        unique_tankers=("mmsi", "nunique"),
        new_to_port_vessel_share=("new_to_port_vessel", "mean"),
        median_length_m=("length_m", "median"),
        median_width_m=("width_m", "median"),
        median_draft_m=("draft_m", "median"),
        median_arrival_local_hour=("arrival_local_hour", "median"),
        weekend_arrival_share=("weekend_arrival", "mean"),
    )
    resolved = calls.loc[calls.resolved_call].copy()
    duration = resolved.groupby(keys, as_index=False).agg(
        resolved_tanker_calls=("mmsi", "size"),
        mean_berth_stationary_hours=("berth_stationary_hours", "mean"),
        mean_outside_berth_stationary_hours=("outside_berth_stationary_hours", "mean"),
        mean_interval_hours=("interval_hours", "mean"),
        mean_elapsed_hours=("elapsed_hours", "mean"),
        mean_moving_10kt_hours=("moving_10kt_hours", "mean"),
        total_berth_stationary_hours=("berth_stationary_hours", "sum"),
        total_outside_berth_stationary_hours=("outside_berth_stationary_hours", "sum"),
        total_interval_hours=("interval_hours", "sum"),
        unresolved_sog_hours=("unresolved_sog_hours", "sum"),
    )
    panel = base.merge(duration, on=keys, how="left", validate="one_to_one")
    panel["unresolved_sog_time_share"] = panel.unresolved_sog_hours / panel.total_interval_hours
    panel["year"] = panel.year_month.str[:4].astype(int)
    panel["month"] = panel.year_month.str[5:7].astype(int)
    return panel.sort_values(keys, kind="stable").reset_index(drop=True)


def official_tanker_arrivals(path: Path | str = OFFICIAL_2024_ARRIVALS) -> dict:
    """Validate source hashes and total the frozen type-to-type comparator."""
    table = pd.read_csv(path)
    required = {
        "port_complex_id", "port", "vessel_subtype", "official_tanker_arrivals",
        "source_artifact", "source_sha256", "table_id", "pdf_physical_page", "printed_page",
    }
    if missing := required - set(table.columns):
        raise ValueError(f"official tanker comparator missing columns: {sorted(missing)}")
    for artifact, expected in table.groupby("source_artifact").source_sha256.first().items():
        source = ROOT / "data/external/spb_emissions_inventories" / artifact
        if sha256_file(source) != expected:
            raise ValueError(f"official inventory hash mismatch: {artifact}")
    port_totals = table.groupby("port", sort=True).official_tanker_arrivals.sum().astype(int).to_dict()
    return {
        "year": 2024,
        "measure": "tanker arrivals from sea to berth or anchorage before shifting to berth",
        "port_totals": port_totals,
        "spb_total": int(table.official_tanker_arrivals.sum()),
        "subtype_rows": int(len(table)),
        "derived_table_sha256": sha256_file(path),
    }


def evaluate_blind_gate(
    calls: pd.DataFrame,
    source_summary: dict,
    official: dict,
) -> dict:
    """Evaluate only the six frozen feasibility/measurement conditions."""
    required = {
        "port_complex_id", "year", "resolved_call", "interval_hours",
        "unresolved_sog_hours", "has_berth_stationary_interval",
    }
    if missing := required - set(calls.columns):
        raise ValueError(f"blind-gate call table missing columns: {sorted(missing)}")
    sample = calls.loc[calls.year.isin([2024, 2025])].copy()
    resolved = sample.loc[sample.resolved_call]
    counts = resolved.groupby(["port_complex_id", "year"]).size().unstack(fill_value=0)
    for year in (2024, 2025):
        if year not in counts:
            counts[year] = 0
    spb_counts = {str(year): int(counts.reindex([TREATED_PORT], fill_value=0).loc[TREATED_PORT, year]) for year in (2024, 2025)}
    donors = counts.drop(index=TREATED_PORT, errors="ignore")
    eligible_donors = donors.index[(donors[2024] >= 20) & (donors[2025] >= 20)].tolist()

    ais_2024_calls = int(
        sample.loc[(sample.port_complex_id.eq(TREATED_PORT)) & sample.year.eq(2024)].shape[0]
    )
    official_total = int(official["spb_total"])
    comparator_error = abs(ais_2024_calls - official_total) / official_total

    spb_resolved = resolved.loc[resolved.port_complex_id.eq(TREATED_PORT)]
    geometry_coverage = (
        float(spb_resolved.has_berth_stationary_interval.mean()) if len(spb_resolved) else 0.0
    )
    total_interval = float(spb_resolved.interval_hours.sum())
    unresolved_share = (
        float(spb_resolved.unresolved_sog_hours.sum()) / total_interval if total_interval else 1.0
    )
    conditions = {
        "all_source_dates_ok": bool(source_summary["all_dates_ok"]),
        "every_month_at_least_95pct": not source_summary["months_below_95pct"],
        "spb_at_least_50_resolved_calls_each_year": all(value >= 50 for value in spb_counts.values()),
        "at_least_five_donors_with_20_calls_each_year": len(eligible_donors) >= 5,
        "official_2024_tanker_call_error_at_most_20pct": comparator_error <= 0.20,
        "berth_geometry_coverage_at_least_80pct": geometry_coverage >= 0.80,
        "unresolved_sog_time_at_most_10pct": unresolved_share <= 0.10,
    }
    return {
        "gate": "CARB At-Berth SPB tanker blind feasibility and measurement gate",
        "registration": f"https://osf.io/{REGISTRATION_ID}/",
        "source_coverage": source_summary,
        "sample_adequacy": {
            "spb_resolved_calls": spb_counts,
            "eligible_donor_count": len(eligible_donors),
            "eligible_donors": eligible_donors,
        },
        "official_2024_comparator": {
            **official,
            "ais_spb_tanker_calls": ais_2024_calls,
            "absolute_fractional_error": comparator_error,
        },
        "geometry_and_sog": {
            "spb_resolved_calls_2024_2025": int(len(spb_resolved)),
            "calls_with_berth_stationary_interval": int(spb_resolved.has_berth_stationary_interval.sum()),
            "berth_geometry_coverage": geometry_coverage,
            "interval_hours": total_interval,
            "unresolved_sog_hours": float(spb_resolved.unresolved_sog_hours.sum()),
            "unresolved_sog_time_share": unresolved_share,
        },
        "conditions": conditions,
        "status": "pass" if all(conditions.values()) else "fail",
        "effect_estimation_authorized": all(conditions.values()),
        "pillar_b_passed": False,
        "compliance_validated": False,
        "emissions_validated": False,
    }


def _duckdb(memory_limit: str = "4GB") -> duckdb.DuckDBPyConnection:
    spill = Path(tempfile.gettempdir()) / "duckdb_atberth_tanker"
    spill.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{spill.as_posix()}'")
    return con


def build_physical_call_tables(
    *,
    read_start: pd.Timestamp,
    output_start: pd.Timestamp,
    interval_caps: tuple[float, ...],
    attach_covariates: bool,
    memory_limit: str = "4GB",
) -> tuple[dict[float, pd.DataFrame], dict]:
    """Build call tables for one or more interval caps in a single census scan."""
    if not any(PINGS_DIR.glob("year=*/month=*/*.parquet")):
        raise FileNotFoundError("retained national census is missing")
    if not interval_caps or any(cap <= 0 for cap in interval_caps):
        raise ValueError("at least one positive interval cap is required")
    static = pd.read_csv(VESSEL_CHARACTERISTICS)
    con = _duckdb(memory_limit)
    try:
        ping_type = modal_ping_types(con)
        population = classify_tanker_population(static, ping_type)
        tankers = population.loc[population.is_tanker, ["mmsi"]].copy()
        con.register("eligible_tankers", tankers)
        geometries = berth_geometries()
        parts: dict[float, list[pd.DataFrame]] = {float(cap): [] for cap in interval_caps}
        for port in sorted(geometries):
            query = f"""
                SELECT p.mmsi, p.timestamp, p.lon, p.lat, p.sog, p.port_complex_id
                FROM read_parquet('{PINGS_GLOB}', hive_partitioning=true) p
                INNER JOIN eligible_tankers t USING (mmsi)
                WHERE p.port_complex_id = ?
                  AND p.timestamp >= ? AND p.timestamp < ?
                ORDER BY p.mmsi, p.timestamp
            """
            pings = con.execute(query, [port, read_start, END_DATE_EXCLUSIVE]).df()
            if pings.empty:
                continue
            pings["timestamp"] = pd.to_datetime(pings.timestamp, utc=True)
            pings["berth_inside"] = mark_berth_pings(pings, geometries[port])
            for cap in parts:
                parts[cap].append(call_interval_metrics(pings, interval_cap_hours=cap))
        call_tables: dict[float, pd.DataFrame] = {}
        for cap, cap_parts in parts.items():
            calls = pd.concat(cap_parts, ignore_index=True) if cap_parts else pd.DataFrame()
            if attach_covariates and len(calls):
                calls = add_call_covariates(calls, static)
            if len(calls):
                calls = calls.loc[calls.first_timestamp.ge(output_start)].reset_index(drop=True)
            call_tables[cap] = calls
        classification = {
            "mmsis_with_any_type": int(population.selected_vessel_type.notna().sum()),
            "eligible_tanker_mmsis": int(population.is_tanker.sum()),
            "excluded_tanker_status_disagreements": int(population.tanker_status_disagreement.sum()),
            "static_type_selected": int(population.type_source.eq("vessel_characteristics").sum()),
            "census_modal_fallback_selected": int(population.type_source.eq("census_modal").sum()),
        }
        return call_tables, classification
    finally:
        con.close()


def build_gate_call_table(*, memory_limit: str = "4GB") -> tuple[pd.DataFrame, dict]:
    """Build 2024--2025 physical call records without aggregating a policy contrast."""
    tables, classification = build_physical_call_tables(
        read_start=GATE_READ_START,
        output_start=pd.Timestamp("2024-01-01", tz="UTC"),
        interval_caps=(PRIMARY_INTERVAL_CAP_HOURS,),
        attach_covariates=False,
        memory_limit=memory_limit,
    )
    return tables[PRIMARY_INTERVAL_CAP_HOURS], classification


def _cap_label(cap: float) -> str:
    return str(cap).replace(".", "p") + "h"


def build_h4_panels(*, memory_limit: str = "4GB") -> dict:
    """Build the registered physical H4 panel only after a passing gate."""
    registration = require_public_registration()
    gate = require_passing_blind_gate()
    outputs = [
        H4_PANEL_DIR / f"calls_cap_{_cap_label(cap)}.parquet"
        for cap in INTERVAL_CAP_SENSITIVITIES
    ] + [
        H4_PANEL_DIR / f"port_month_cap_{_cap_label(cap)}.csv"
        for cap in INTERVAL_CAP_SENSITIVITIES
    ] + [H4_PANEL_DIR / "build_receipt.json"]
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError("immutable H4 panel outputs already exist: " + ", ".join(existing))

    tables, classification = build_physical_call_tables(
        read_start=pd.Timestamp("2015-01-01", tz="UTC"),
        output_start=START_DATE,
        interval_caps=INTERVAL_CAP_SENSITIVITIES,
        attach_covariates=True,
        memory_limit=memory_limit,
    )
    H4_PANEL_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for cap, calls in tables.items():
        call_path = H4_PANEL_DIR / f"calls_cap_{_cap_label(cap)}.parquet"
        panel_path = H4_PANEL_DIR / f"port_month_cap_{_cap_label(cap)}.csv"
        calls.to_parquet(call_path, index=False)
        panel = aggregate_monthly_call_panel(calls)
        panel.to_csv(panel_path, index=False, lineterminator="\n")
        artifacts[str(cap)] = {
            "call_rows": int(len(calls)),
            "port_month_rows": int(len(panel)),
            "calls_sha256": sha256_file(call_path),
            "panel_sha256": sha256_file(panel_path),
        }
    receipt = {
        "artifact": "CARB At-Berth physical H4 call and port-month panels",
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "registration_id": registration["registration_id"],
        "blind_gate_sha256": sha256_file(GATE_JSON),
        "blind_gate_status": gate["status"],
        "classification": classification,
        "interval_caps_hours": list(INTERVAL_CAP_SENSITIVITIES),
        "artifacts": artifacts,
        "compliance_observed": False,
        "emissions_validated": False,
    }
    (H4_PANEL_DIR / "build_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def _write_gate_report(decision: dict, classification: dict, monthly: pd.DataFrame) -> str:
    condition_lines = "\n".join(
        f"- {name.replace('_', ' ')}: **{'PASS' if value else 'FAIL'}**"
        for name, value in decision["conditions"].items()
    )
    sample = decision["sample_adequacy"]
    comparator = decision["official_2024_comparator"]
    geometry = decision["geometry_and_sog"]
    return f"""# CARB At-Berth tanker blind-gate decision

**Registration:** [OSF {REGISTRATION_ID}](https://osf.io/{REGISTRATION_ID}/)  
**Gate:** {decision['status'].upper()}  
**H4 effect estimation:** {'AUTHORIZED' if decision['effect_estimation_authorized'] else 'STOPPED'}

This report contains counts, missingness, source coverage and the frozen 2024
tanker-to-tanker comparator only. It contains no policy-effect estimate and does
not establish Pillar-B, compliance or emissions validity.

## Conditions

{condition_lines}

## Fixed inputs and denominators

- Source dates complete: {decision['source_coverage']['dates_ok']:,}/{decision['source_coverage']['expected_dates']:,}; minimum monthly coverage {decision['source_coverage']['minimum_month_coverage']:.3f}.
- Eligible tanker MMSIs: {classification['eligible_tanker_mmsis']:,}; status disagreements excluded: {classification['excluded_tanker_status_disagreements']:,}.
- SPB resolved calls: 2024 = {sample['spb_resolved_calls']['2024']:,}; 2025 = {sample['spb_resolved_calls']['2025']:,}.
- Donors with at least 20 resolved calls in both years: {sample['eligible_donor_count']} ({', '.join(sample['eligible_donors'])}).
- Official 2024 SPB tanker arrivals: {comparator['spb_total']:,}; AIS 24-hour-gap tanker calls: {comparator['ais_spb_tanker_calls']:,}; absolute error {comparator['absolute_fractional_error']:.1%}.
- Resolved SPB calls with a stationary berth-geometry interval: {geometry['calls_with_berth_stationary_interval']:,}/{geometry['spb_resolved_calls_2024_2025']:,} ({geometry['berth_geometry_coverage']:.1%}).
- Unresolved-SOG interval time: {geometry['unresolved_sog_hours']:.1f}/{geometry['interval_hours']:.1f} hours ({geometry['unresolved_sog_time_share']:.1%}).

The append-only ingestion ledger contains {decision['source_coverage']['prior_non_ok_attempts']:,}
earlier non-OK attempts; a later successful retry plus its retained parquet is
the final status used for source-day completeness. All attempts remain auditable.
"""


def run_blind_gate(*, memory_limit: str = "4GB") -> dict:
    """Fire the externally registered blind gate once and persist its decision."""
    require_public_registration()
    existing = [str(path) for path in (GATE_JSON, GATE_REPORT) if path.exists()]
    if existing:
        raise FileExistsError("blind gate is one-shot and already exists: " + ", ".join(existing))
    source, monthly = source_day_coverage()
    calls, classification = build_gate_call_table(memory_limit=memory_limit)
    decision = evaluate_blind_gate(calls, source, official_tanker_arrivals())
    decision["tanker_classification"] = classification
    decision["run_once_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    decision["treatment_effects_opened"] = False
    GATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    GATE_JSON.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    GATE_REPORT.write_text(_write_gate_report(decision, classification, monthly), encoding="utf-8")
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--blind-gate", action="store_true", help="fire the registered metadata/count gate once")
    actions.add_argument(
        "--build-h4-panels", action="store_true",
        help="after a passing gate, build the immutable call and port-month panels",
    )
    actions.add_argument(
        "--recovery-call-gate",
        action="store_true",
        help="fire the separately registered corrected R-G1 sea-to-port gate",
    )
    actions.add_argument(
        "--verify-recovery-gate", action="store_true",
        help="read-only: recompute R-G1 and diff against the stored decision (cannot refire it)",
    )
    parser.add_argument("--memory-limit", default="4GB", help="DuckDB memory cap; excess spills to disk")
    args = parser.parse_args()
    if args.blind_gate:
        result = run_blind_gate(memory_limit=args.memory_limit)
    elif args.verify_recovery_gate:
        result = verify_recovery_call_gate(memory_limit=args.memory_limit)
    elif args.recovery_call_gate:
        result = run_recovery_call_gate(memory_limit=args.memory_limit)
    else:
        result = build_h4_panels(memory_limit=args.memory_limit)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
