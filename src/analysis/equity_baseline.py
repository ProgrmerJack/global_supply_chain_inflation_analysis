"""Reproduce the predeclared San Pedro Bay descriptive equity baseline."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
ACS = ROOT / "data/external/acs/acs5_2022_port_county_tracts.csv"
CES = "zip://data/external/calenviroscreen/calenviroscreen50_shp.zip!calenviroscreen50results_F_070126.shp/CES5_final_shapefile.shp"
OUT = ROOT / "results/deep_case_SPB/H5_equity_baseline.csv"
COMMUNITIES = r"Long Beach|Wilmington|San Pedro|Carson|Harbor|Terminal"


def _weighted(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    return float(np.average(values[valid], weights=weights[valid]))


def build() -> pd.DataFrame:
    acs = pd.read_csv(ACS, dtype={"geoid": str})
    acs = acs.loc[acs.complex_id.eq("san_pedro_bay")].copy()
    acs["geoid"] = acs.geoid.str.zfill(11)
    ces = gpd.read_file(CES)
    ces["geoid"] = ces.tract.astype("Int64").astype(str).str.zfill(11)
    joined = ces.merge(acs, on="geoid", suffixes=("_ces", "_acs"))
    port = joined.loc[joined.approx_loc.str.contains(COMMUNITIES, case=False, na=False)].copy()

    for frame in (acs, joined, port):
        for column in ("total_pop", "median_hh_income", "race_universe", "black_acs", "hisp_universe", "hispanic", "CIscoreP", "pm"):
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
                frame.loc[frame[column] < 0, column] = np.nan

    def summarize(name: str, census: pd.DataFrame, environment: pd.DataFrame) -> dict[str, float | int | str]:
        return {
            "group": name,
            "tracts": int(len(census)),
            "population": int(census.total_pop.sum()),
            "population_weighted_tract_median_income_usd": _weighted(census.median_hh_income, census.total_pop),
            "hispanic_share_pct": 100 * float(census.hispanic.sum() / census.hisp_universe.sum()),
            "black_share_pct": 100 * float(census.black_acs.sum() / census.race_universe.sum()),
            "mean_ces_score_percentile": float(environment.CIscoreP.mean()),
            "mean_pm25_ug_m3": float(environment.pm.mean()),
        }

    port_acs = port
    county_acs = acs.rename(columns={"black": "black_acs"})
    return pd.DataFrame([
        summarize("port_adjacent", port_acs, port),
        summarize("los_angeles_county", county_acs, joined),
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    result = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, float_format="%.6f", lineterminator="\n")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
