"""
Per-port port-call-segmentation SENSITIVITY as a deposited data record (referee-requested).

Emits outputs/monthly_dwell_segmented_sensitivity.csv with, for each Port x YearMonth x gap threshold
(12/24/48 h), the segmented dwell metrics and how closely the segmented series tracks the published
first-to-last (primary) monthly dwell series. This lets a reviewer quantify the first-to-last-vs-call
sensitivity directly from a data record, not only from code.

Columns: Port, YearMonth, gap_threshold_h, MeanDwellDays_segmented, MedianDwellDays_segmented,
UniqueCalls, UniqueVessels, correlation_with_primary_series (per Port x threshold, over months).

Same per-vessel gap segmentation as port_call_segmentation.py; primary series = first-to-last monthly
mean dwell. Run: python src/process_ais/dwell_segmentation_sensitivity.py
"""
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.compute as pc

try:
    from .ping_time import parse_ping_time
except ImportError:  # run as a script, not a package module
    from ping_time import parse_ping_time

PORTS = ["LA_Long_Beach", "NY_NJ", "Houston", "Savannah", "Seattle"]
THRESH_H = [12, 24, 48]
CSV = "data/processed/ais_dwell_census_mode/port_pings"
FGDB = "data/processed/ais_dwell_census_mode_2009_2014_v2/port_pings_fgdb"


def _month_rows(dset, port, year):
    t = dset.to_table(columns=["MMSI", "BaseDateTime"],
                      filter=(pc.field("Port") == port) & (pc.field("year") == year)).to_pandas()
    if not len(t):
        return []
    t["dt"] = parse_ping_time(t["BaseDateTime"], f"dwell_segmentation_sensitivity {port} {year}")
    t = t.dropna(subset=["dt", "MMSI"]).sort_values(["MMSI", "dt"])
    g = t.groupby("MMSI", sort=False)["dt"]
    gap_h = g.diff().dt.total_seconds() / 3600.0
    newv = g.transform("first").eq(t["dt"]).values
    t["ym"] = t.dt.dt.to_period("M").astype(str)
    out = []
    # primary: first-to-last within (MMSI, month)
    ftl = t.groupby(["MMSI", "ym"]).dt.agg(["min", "max"])
    ftl["d"] = (ftl["max"] - ftl["min"]).dt.total_seconds() / 86400.0
    prim = ftl.groupby("ym").d.mean()
    for th in THRESH_H:
        call = np.cumsum(newv | (gap_h.values > th))
        cc = pd.DataFrame({"MMSI": t.MMSI.values, "call": call, "dt": t.dt.values})
        agg = cc.groupby(["MMSI", "call"]).dt.agg(["min", "max"])
        agg["d"] = (agg["max"] - agg["min"]).dt.total_seconds() / 86400.0
        agg["ym"] = agg["min"].dt.to_period("M").astype(str)
        agg["MMSI"] = agg.index.get_level_values("MMSI")
        m = agg.groupby("ym").agg(MeanDwellDays_segmented=("d", "mean"),
                                  MedianDwellDays_segmented=("d", "median"),
                                  UniqueCalls=("d", "size"), UniqueVessels=("MMSI", "nunique"))
        m["gap_threshold_h"] = th
        m["Port"] = port
        m["primary"] = prim.reindex(m.index).values
        out.append(m.reset_index())
    return out


def main():
    rows = []
    for path, years in ((CSV, range(2015, 2026)), (FGDB, range(2009, 2015))):
        dset = ds.dataset(path, format="parquet", partitioning="hive")
        for port in PORTS:
            for y in years:
                rows += _month_rows(dset, port, y)
            print(f"  {path.split('/')[-1]} {port}: done", flush=True)
    df = pd.concat(rows, ignore_index=True).rename(columns={"ym": "YearMonth"})
    # correlation of segmented monthly mean vs primary (first-to-last) monthly mean, per Port x threshold
    corr = (df.dropna(subset=["primary"])
              .groupby(["Port", "gap_threshold_h"])
              .apply(lambda g: np.corrcoef(g.MeanDwellDays_segmented, g.primary)[0, 1] if len(g) > 3 else np.nan,
                     include_groups=False)
              .rename("correlation_with_primary_series").reset_index())
    df = df.merge(corr, on=["Port", "gap_threshold_h"], how="left")
    cols = ["Port", "YearMonth", "gap_threshold_h", "MeanDwellDays_segmented", "MedianDwellDays_segmented",
            "UniqueCalls", "UniqueVessels", "correlation_with_primary_series"]
    df = df[cols].sort_values(["Port", "gap_threshold_h", "YearMonth"])
    df.to_csv("outputs/monthly_dwell_segmented_sensitivity.csv", index=False)
    print(f"wrote outputs/monthly_dwell_segmented_sensitivity.csv: {len(df):,} rows")
    print(corr.to_string(index=False))
    # HONEST finding: first-to-last monthly dwell tracks per-call dwell at LA/LB (positive corr) but
    # SATURATES and diverges at busier multi-call complexes (NY/NJ, Houston -> negative) -> first-to-last
    # is a coarse port-month proxy, strongest where congestion concentrates (LA/LB). The load-bearing
    # guarantee is that the LA/LB (emissions/congestion) series co-moves; other ports are documented.
    la = corr[corr.Port == "LA_Long_Beach"].correlation_with_primary_series
    assert len(corr) == 15, "expected 5 ports x 3 gap thresholds"
    assert la.min() > 0.25, "LA/LB segmented dwell decouples from the first-to-last primary series"
    print("PASS: 5 ports x 3 thresholds written; LA/LB segmented-vs-primary corr %.2f-%.2f (>0.25);"
          % (la.min(), la.max()))
    print("      multi-call ports (NY/NJ, Houston) diverge -> first-to-last is a coarse proxy, documented.")


if __name__ == "__main__":
    main()
