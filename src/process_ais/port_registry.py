"""Build the frozen national port-complex universe from Census trade metadata."""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

BASE = "https://api.census.gov/data/timeseries/intltrade/imports/porths"
RANKING_YEARS = ("2017", "2018", "2019")
TOP_COMPLEXES = 20
COVERAGE = 0.90
MAX_COMPLEXES = 30
CONTIGUOUS_OCEAN_STATES = frozenset(
    {
        "AL",
        "CA",
        "CT",
        "DC",
        "DE",
        "FL",
        "GA",
        "LA",
        "MA",
        "MD",
        "ME",
        "MS",
        "NC",
        "NH",
        "NJ",
        "NY",
        "OR",
        "PA",
        "RI",
        "SC",
        "TX",
        "VA",
        "WA",
    }
)
# New York and Pennsylvania have both ocean-connected and Great Lakes/border ports.
EXCLUDED_GREAT_LAKES_AND_BORDER_PORT_CODES = frozenset(
    {"0701", "0704", "0708", "0712", "0901", "0903", "0904", "0905", "4106"}
)
CROSSWALK_VERSION = "crosswalk-v1-2026-07-13"
CROSSWALK_SOURCE_VINTAGE = (
    "Census Port-HS 2017-2019; UN/LOCODE 2025-1; "
    "USACE Port/PSA metadata accessed 2026-07-13"
)
MERGED_COMPLEXES = {
    "san_pedro_bay": {
        "name": "San Pedro Bay (Los Angeles/Long Beach)",
        "coast": "Pacific",
        "codes": ("2704", "2709"),
        "rule": "shared_harbour_approach",
    },
    "new_york_new_jersey": {
        "name": "Port of New York and New Jersey",
        "coast": "Atlantic",
        "codes": ("1001", "1003"),
        "rule": "official_shared_port_authority",
    },
}
PACIFIC_STATES = frozenset({"CA", "OR", "WA"})
GULF_STATES = frozenset({"AL", "LA", "MS", "TX"})
GULF_FLORIDA_PORT_CODES = frozenset({"1801", "1807", "1814", "1818", "1819", "1821", "5202"})
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CROSSWALK = ROOT / "config/registries/port_complex_crosswalk.csv"
DEFAULT_OUTPUT = ROOT / "data/processed/port_registry.csv"
DEFAULT_RECEIPT = ROOT / "prereg/governance/port_universe_receipt.json"
MONTHLY_PORT_ACTIVITY_FIELDS = frozenset({"CNT_VAL_MO", "CNT_WGT_MO", "VES_WGT_MO"})
MONTHLY_ACTIVITY_MANIFEST_COLUMNS = [
    "source_file", "source_url", "retrieved_at", "file_size_bytes", "sha256", "raw_row_count", "measure"
]


def _env_key(path: str = ".env") -> str | None:
    """Read the existing Census key convention without exposing it in output."""
    if not os.path.exists(path):
        return os.environ.get("CENSUS_API_KEY")
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() == "CENSUS_API_KEY":
            return value.strip().strip('"').strip("'")
    return os.environ.get("CENSUS_API_KEY")


def is_contiguous_seaport(port_code: str, port_name: str) -> bool:
    """Apply the registered contiguous ocean-coast scope to Census port metadata."""
    _location, separator, state = str(port_name).rpartition(",")
    return bool(
        separator
        and str(port_code) not in EXCLUDED_GREAT_LAKES_AND_BORDER_PORT_CODES
        and state.strip().upper() in CONTIGUOUS_OCEAN_STATES
    )


def _coast_for(port_code: str, port_name: str) -> str:
    """Return the registered coast for an already eligible Census port."""
    _location, _separator, state = str(port_name).rpartition(",")
    state = state.strip().upper()
    if state in PACIFIC_STATES:
        return "Pacific"
    if state in GULF_STATES or str(port_code) in GULF_FLORIDA_PORT_CODES:
        return "Gulf"
    return "Atlantic"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _record_monthly_activity_response(raw_dir: Path, measure: str, month: str, rows: list) -> None:
    """Persist an immutable, secret-free Census response and its retrieval manifest row."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = f"imports_porths_{measure}_{month}.json"
    raw_path = raw_dir / filename
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    if raw_path.exists():
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != digest:
            raise FileExistsError(f"immutable Census response differs from cached source: {raw_path}")
        return
    raw_path.write_bytes(payload)
    record = {
        "source_file": filename,
        "source_url": f"{BASE}?{urlencode({'get': f'PORT,PORT_NAME,{measure}', 'time': month})}",
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "file_size_bytes": len(payload),
        "sha256": digest,
        "raw_row_count": max(len(rows) - 1, 0),
        "measure": measure,
    }
    manifest_path = raw_dir / "requests_manifest.csv"
    pd.DataFrame([record], columns=MONTHLY_ACTIVITY_MANIFEST_COLUMNS).to_csv(
        manifest_path, mode="a", header=not manifest_path.exists(), index=False, lineterminator="\n"
    )


def build_crosswalk(port_values: pd.DataFrame) -> pd.DataFrame:
    """Build the outcome-blind operational-complex crosswalk from frozen rules."""
    required = {"port_code", "port_name", "cnt_val_annual_usd"}
    if missing := required - set(port_values.columns):
        raise ValueError(f"port values missing columns: {sorted(missing)}")

    values = port_values.copy()
    values["port_code"] = values["port_code"].astype(str)
    if values.port_code.duplicated().any():
        raise ValueError("port values must have one row per Census port")
    port_codes = set(values.port_code)
    rows: list[dict[str, str]] = []
    consumed: set[str] = set()
    for complex_id, definition in MERGED_COMPLEXES.items():
        component_codes = set(definition["codes"])
        overlap = component_codes & port_codes
        if overlap and overlap != component_codes:
            raise ValueError(f"incomplete registered complex {complex_id}: {sorted(component_codes - overlap)}")
        if overlap:
            rows.append(
                {
                    "port_complex_id": complex_id,
                    "port_complex_name": definition["name"],
                    "coast": definition["coast"],
                    "component_port_codes": ";".join(definition["codes"]),
                    "geometry_version": CROSSWALK_VERSION,
                    "source_vintage": CROSSWALK_SOURCE_VINTAGE,
                    "operational_rule": definition["rule"],
                }
            )
            consumed.update(component_codes)

    for row in values.sort_values("port_code", kind="stable").itertuples(index=False):
        if row.port_code in consumed:
            continue
        location, _separator, state = row.port_name.rpartition(",")
        rows.append(
            {
                "port_complex_id": f"{_slug(location)}_{state.strip().lower()}",
                "port_complex_name": row.port_name.title(),
                "coast": _coast_for(row.port_code, row.port_name),
                "component_port_codes": row.port_code,
                "geometry_version": CROSSWALK_VERSION,
                "source_vintage": CROSSWALK_SOURCE_VINTAGE,
                "operational_rule": "single_census_customs_port",
            }
        )

    crosswalk = pd.DataFrame(rows).sort_values("port_complex_id", kind="stable").reset_index(drop=True)
    if crosswalk.port_complex_id.duplicated().any():
        raise ValueError("registered crosswalk generated duplicate complex IDs")
    return crosswalk


def fetch_containerized_by_port(
    years: tuple[str, ...] = RANKING_YEARS, key: str | None = None
) -> pd.DataFrame:
    """Return mean annual 2017–2019 vessel-container import value by Census port."""
    if tuple(years) != RANKING_YEARS:
        raise ValueError(f"ranking years are frozen at {RANKING_YEARS}")
    key = key or _env_key()
    if not key:
        raise RuntimeError("CENSUS_API_KEY is required in .env")

    totals: collections.defaultdict[str, float] = collections.defaultdict(float)
    names: dict[str, str] = {}
    for year in years:
        response = requests.get(
            BASE,
            params={
                "get": "PORT,PORT_NAME,CNT_VAL_YR",
                "time": f"{year}-12",
                "key": key,
            },
            timeout=120,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows or rows[0] != ["PORT", "PORT_NAME", "CNT_VAL_YR", "time"]:
            raise RuntimeError(f"unexpected Census response schema for {year}")
        for port_code, port_name, value, _ in rows[1:]:
            port_code = str(port_code)
            if len(port_code) != 4 or not port_code.isdigit():
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if numeric_value <= 0:
                continue
            if not is_contiguous_seaport(port_code, str(port_name)):
                continue
            totals[port_code] += numeric_value
            names[port_code] = str(port_name).strip()

    return (
        pd.DataFrame(
            {
                "port_code": list(totals),
                "port_name": [names[port] for port in totals],
                "cnt_val_annual_usd": [totals[port] / len(years) for port in totals],
            }
        )
        .sort_values(["cnt_val_annual_usd", "port_code"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )


def fetch_monthly_vessel_activity_by_port(
    months: list[str], *, measure: str = "CNT_VAL_MO", key: str | None = None, raw_dir: Path | None = None
) -> pd.DataFrame:
    """Return one declared monthly Census vessel-activity measure per eligible customs port.

    The Port-HS endpoint supplies price-bearing container value plus physical containerized and all-vessel
    shipping weights.  The caller must declare one supported field before retrieval; this client neither
    searches measures nor chooses one after inspecting a correlation.  No commodity predicate is sent, so
    each response is the Census monthly total for a customs port.  When ``raw_dir`` is supplied, each
    response is immutably retained with a secret-free request manifest.
    """
    measure = str(measure).upper()
    if measure not in MONTHLY_PORT_ACTIVITY_FIELDS:
        raise ValueError(f"unsupported monthly Census measure: {measure!r}")
    key = key or _env_key()
    if not key:
        raise RuntimeError("CENSUS_API_KEY is required in .env")
    records = []
    for month in months:
        response = requests.get(
            BASE,
            params={"get": f"PORT,PORT_NAME,{measure}", "time": month, "key": key},
            timeout=120,
        )
        response.raise_for_status()
        rows = response.json()
        if raw_dir is not None:
            _record_monthly_activity_response(Path(raw_dir), measure, month, rows)
        if not rows or rows[0] != ["PORT", "PORT_NAME", measure, "time"]:
            raise RuntimeError(f"unexpected Census monthly schema for {month}")
        for port_code, port_name, value, timestamp in rows[1:]:
            port_code = str(port_code)
            if len(port_code) != 4 or not port_code.isdigit():
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if numeric_value < 0 or not is_contiguous_seaport(port_code, str(port_name)):
                continue
            records.append({"port_code": port_code, "port_name": str(port_name).strip(),
                            "year_month": str(timestamp), measure.lower(): numeric_value})
    return pd.DataFrame(records, columns=["port_code", "port_name", "year_month", measure.lower()])


def fetch_monthly_containerized_by_port(months: list[str], key: str | None = None) -> pd.DataFrame:
    """Compatibility wrapper for the existing monthly containerized-import value diagnostic."""
    return fetch_monthly_vessel_activity_by_port(months, measure="CNT_VAL_MO", key=key)


def aggregate_port_complexes(port_values: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Census ports to declared operational complexes before ranking."""
    required_ports = {"port_code", "port_name", "cnt_val_annual_usd"}
    required_crosswalk = {
        "port_complex_id",
        "port_complex_name",
        "coast",
        "component_port_codes",
        "geometry_version",
        "source_vintage",
    }
    if missing := required_ports - set(port_values.columns):
        raise ValueError(f"port values missing columns: {sorted(missing)}")
    if missing := required_crosswalk - set(crosswalk.columns):
        raise ValueError(f"crosswalk missing columns: {sorted(missing)}")

    membership: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    for index, row in crosswalk.reset_index(drop=True).iterrows():
        codes = [code.strip() for code in str(row.component_port_codes).split(";") if code.strip()]
        if not codes:
            raise ValueError(f"empty component_port_codes for {row.port_complex_id}")
        for code in codes:
            if code in membership:
                raise ValueError(f"Census port {code} appears in multiple complexes")
            membership[code] = index
        rows.append(dict(row))

    values = port_values.copy()
    values["port_code"] = values["port_code"].astype(str)
    unmapped = sorted(set(values.port_code) - set(membership))
    if unmapped:
        raise ValueError(f"crosswalk omits Census ports: {', '.join(unmapped[:10])}")

    values["_crosswalk_row"] = values.port_code.map(membership)
    template = pd.DataFrame(rows).reset_index(names="_crosswalk_row")
    merged = values.merge(template, on="_crosswalk_row", validate="many_to_one")
    grouped = (
        merged.groupby(
            [
                "port_complex_id",
                "port_complex_name",
                "coast",
                "component_port_codes",
                "geometry_version",
                "source_vintage",
            ],
            as_index=False,
        )["cnt_val_annual_usd"]
        .sum()
        .rename(columns={"cnt_val_annual_usd": "ranking_value_2017_2019"})
        .sort_values(["ranking_value_2017_2019", "port_complex_id"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )
    return grouped


def select_complexes(
    values: list[float] | np.ndarray,
    coverage: float = COVERAGE,
    top_complexes: int = TOP_COMPLEXES,
    max_complexes: int = MAX_COMPLEXES,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Apply the top-20, cumulative-90%, maximum-30 inclusion rule."""
    values_array = np.asarray(values, dtype=float)
    if values_array.ndim != 1 or len(values_array) == 0:
        raise ValueError("values must be a non-empty one-dimensional array")
    if np.any(values_array < 0) or values_array.sum() <= 0:
        raise ValueError("values must be non-negative with a positive total")
    if not 0 < coverage <= 1 or top_complexes < 1 or max_complexes < top_complexes:
        raise ValueError("invalid selection rule")

    order = np.argsort(-values_array, kind="stable")
    cumulative_ranked = np.cumsum(values_array[order]) / values_array.sum()
    first_coverage_count = int(np.searchsorted(cumulative_ranked, coverage, side="left")) + 1
    selected_count = min(max(min(top_complexes, len(values_array)), first_coverage_count), max_complexes)
    keep = np.zeros(len(values_array), dtype=bool)
    keep[order[:selected_count]] = True
    cumulative_share = np.empty(len(values_array), dtype=float)
    cumulative_share[order] = cumulative_ranked
    return keep, cumulative_share, bool(cumulative_ranked[selected_count - 1] >= coverage)


def build_registry(
    crosswalk_path: Path = DEFAULT_CROSSWALK,
    output_path: Path = DEFAULT_OUTPUT,
    receipt_path: Path = DEFAULT_RECEIPT,
) -> pd.DataFrame:
    """Write the full ranked registry and its metadata-only reproducibility receipt."""
    crosswalk_path = Path(crosswalk_path)
    output_path = Path(output_path)
    receipt_path = Path(receipt_path)
    crosswalk = pd.read_csv(crosswalk_path, dtype=str)
    complexes = aggregate_port_complexes(fetch_containerized_by_port(), crosswalk)
    keep, cumulative_share, reached_coverage = select_complexes(complexes.ranking_value_2017_2019.to_numpy())
    complexes.insert(0, "rank", np.arange(1, len(complexes) + 1))
    complexes["cumulative_share"] = cumulative_share
    complexes["inclusion_status"] = np.where(keep, "included", "excluded_by_selection_rule")
    complexes["inclusion_reason"] = np.where(
        complexes["rank"] <= TOP_COMPLEXES,
        "top_20",
        np.where(keep, "cumulative_90_percent", "outside_selected_coverage"),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    complexes.to_csv(output_path, index=False, lineterminator="\n")
    receipt = {
        "schema_version": 1,
        "created_on": date.today().isoformat(),
        "outcome_data_accessed": False,
        "source": {
            "endpoint": BASE,
            "measure": "CNT_VAL_YR",
            "ranking_years": list(RANKING_YEARS),
            "observation_months": [f"{year}-12" for year in RANKING_YEARS],
        },
        "candidate_universe": {
            "definition": "positive containerized vessel import value at contiguous US ocean-coast customs ports",
            "included_state_codes": sorted(CONTIGUOUS_OCEAN_STATES),
            "excluded_great_lakes_or_border_port_codes": sorted(EXCLUDED_GREAT_LAKES_AND_BORDER_PORT_CODES),
            "census_ports": int(sum(len(codes.split(";")) for codes in crosswalk.component_port_codes)),
            "operational_complexes": int(len(complexes)),
        },
        "crosswalk": {"path": _receipt_path(crosswalk_path), "sha256": _sha256(crosswalk_path)},
        "selection": {
            "top_complexes": TOP_COMPLEXES,
            "coverage_target": COVERAGE,
            "maximum_complexes": MAX_COMPLEXES,
            "included_complexes": int(keep.sum()),
            "achieved_coverage": float(complexes.loc[keep, "cumulative_share"].max()),
            "reached_coverage_target": reached_coverage,
        },
        "registry": {"path": _receipt_path(output_path), "sha256": _sha256(output_path)},
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"selected {int(keep.sum())} complexes covering {complexes.loc[keep, 'cumulative_share'].max():.1%}; "
        f"90% reached={reached_coverage}"
    )
    print(f"wrote {output_path}")
    print(f"wrote {receipt_path}")
    return complexes


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    build_registry()
