"""Declared official monthly port-activity series for G1 (docs/implementation_plan.md §5).

Maps a declared US Census monthly vessel-import measure (fetched through the existing `port_registry`
client — no second Census client) onto the frozen national port complexes using their registered
`component_port_codes`.  `CNT_VAL_MO` is an economic diagnostic only; physical shipping-weight measures
are available only when named explicitly before retrieval.

Output: data/processed/official_port_activity.csv
        [port_complex_id, year_month, official_activity]  (USD containerized vessel value)

Run from repo root:
  python src/process_ais/official_port_activity.py --months 2021-01:2021-12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

try:
    from .port_registry import MONTHLY_PORT_ACTIVITY_FIELDS, fetch_monthly_vessel_activity_by_port
    from ..governance.access import assert_confirmatory_unlocked
except ImportError:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[1]))
    sys.path.insert(0, str(_here.parents[0]))
    from port_registry import MONTHLY_PORT_ACTIVITY_FIELDS, fetch_monthly_vessel_activity_by_port  # type: ignore
    from governance.access import assert_confirmatory_unlocked  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "data/processed/port_registry.csv"
DEFAULT_OUT = ROOT / "data/processed/official_port_activity.csv"
DEFAULT_RAW_ROOT = ROOT / "data/interim/official_port_activity"


def map_ports_to_complexes(
    monthly: pd.DataFrame, registry: pd.DataFrame, *, value_column: str = "cnt_val_mo"
) -> pd.DataFrame:
    """Sum one declared monthly Census measure into INCLUDED complexes via component codes."""
    for name, frame, cols in (("monthly", monthly, {"port_code", "year_month", value_column}),
                              ("registry", registry, {"port_complex_id", "component_port_codes", "inclusion_status"})):
        if missing := cols - set(frame.columns):
            raise ValueError(f"{name} missing columns: {sorted(missing)}")

    included = registry.loc[registry["inclusion_status"] == "included"]
    code_to_complex: dict[str, str] = {}
    for row in included.itertuples(index=False):
        for code in str(row.component_port_codes).split(";"):
            code = code.strip()
            if code:
                code_to_complex[code] = row.port_complex_id

    df = monthly.copy()
    df["port_code"] = df["port_code"].astype(str)
    df["port_complex_id"] = df["port_code"].map(code_to_complex)
    mapped = df.dropna(subset=["port_complex_id"])
    activity = (
        mapped.groupby(["port_complex_id", "year_month"], sort=True)[value_column]
        .sum()
        .rename("official_activity")
        .reset_index()
    )
    return activity


def _expand_months(spec: str) -> list[str]:
    """'2021-01:2021-12' -> ['2021-01',...]; also accepts a comma list of YYYY-MM."""
    if ":" in spec:
        lo, hi = spec.split(":")
        months = pd.period_range(lo, hi, freq="M")
        return [str(p) for p in months]
    return [m.strip() for m in spec.split(",") if m.strip()]


def build_official_activity(months: list[str], *, registry_path: Path = DEFAULT_REGISTRY,
                            out_path: Path = DEFAULT_OUT, key: str | None = None,
                            measure: str = "CNT_VAL_MO", raw_dir: Path | None = None) -> pd.DataFrame:
    measure = str(measure).upper()
    if measure not in MONTHLY_PORT_ACTIVITY_FIELDS:
        raise ValueError(f"unsupported monthly Census measure: {measure!r}")
    if measure != "CNT_VAL_MO" and Path(out_path) == DEFAULT_OUT:
        raise ValueError("a physical Census measure requires an explicit non-default output path")
    registry = pd.read_csv(registry_path, dtype={"component_port_codes": str})
    raw_dir = Path(raw_dir) if raw_dir is not None else DEFAULT_RAW_ROOT / measure.lower()
    monthly = fetch_monthly_vessel_activity_by_port(months, measure=measure, key=key, raw_dir=raw_dir)
    activity = map_ports_to_complexes(monthly, registry, value_column=measure.lower())
    out_path = Path(out_path)
    assert_confirmatory_unlocked(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    activity.to_csv(out_path, index=False, lineterminator="\n")
    print(f"official activity ({measure}): {len(activity)} complex-months, {activity.port_complex_id.nunique()} complexes, "
          f"months {activity.year_month.min()}..{activity.year_month.max()} -> {out_path}")
    return activity


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a declared official monthly Census port-activity series.")
    ap.add_argument("--months", default="2021-01:2021-12", help="YYYY-MM:YYYY-MM range or comma list")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--measure", default="CNT_VAL_MO", choices=sorted(MONTHLY_PORT_ACTIVITY_FIELDS),
                    help="Census field; CNT_VAL_MO is diagnostic, physical weights require an explicit --out")
    ap.add_argument("--raw-dir", type=Path, default=None,
                    help="immutable raw-response directory (default: data/interim/official_port_activity/<measure>)")
    args = ap.parse_args()
    build_official_activity(_expand_months(args.months), out_path=args.out, measure=args.measure, raw_dir=args.raw_dir)


if __name__ == "__main__":
    main()
