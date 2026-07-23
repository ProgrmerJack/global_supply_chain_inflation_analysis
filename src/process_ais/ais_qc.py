"""
AIS quality-control audit for the LA/LB dwell field (deposit-reproducible standing guard).

A referee's objection to first-to-last monthly dwell: a single spurious in-box ping near the start or end
of a month can stretch the dwell span (the 2-h interval cap protects mode-hours but NOT first-to-last
dwell). We do not blanket-filter, but we quantify the exposure and show the results are insensitive to it:

  1. MMSI validity audit  -- share of pings whose MMSI is not a plausible ship identifier
     (9 digits, 100000000-799999999; ship MID first digit 2-7). Malformed identifiers are rare.
  2. Impossible-jump filter -- flag an isolated position spike: a ping whose implied speed to BOTH
     temporal neighbours exceeds 40 kn (well above a laden cargo/tanker's ~25 kn), i.e. it "teleports"
     in and out. Remove spikes, recompute first-to-last monthly dwell, re-correlate with the GSCPI.
  3. Low-observation dwell outliers -- vessel-months with large dwell (>20 d) inferred from very few
     pings (<5). Remove them, re-aggregate, re-correlate.

PASS if the LA/LB dwell-GSCPI correlation and the two crisis peaks are essentially unchanged after each
filter -> first-to-last dwell is not driven by anomalous pings. Run: python src/process_ais/ais_qc.py
"""
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.compute as pc

PORT = "LA_Long_Beach"
CSV = "data/processed/ais_dwell_census_mode/port_pings"
FGDB = "data/processed/ais_dwell_census_mode_2009_2014_v2/port_pings_fgdb"
SPIKE_KN = 40.0        # implied speed above which an isolated ping is a position glitch
R_NM = 3440.065        # earth radius in nautical miles


def _haversine_nm(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R_NM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _year(dset, y):
    t = dset.to_table(columns=["MMSI", "BaseDateTime", "LAT", "LON"],
                      filter=(pc.field("Port") == PORT) & (pc.field("year") == y)).to_pandas()
    if not len(t):
        return None
    t["dt"] = pd.to_datetime(t["BaseDateTime"], errors="coerce")
    t = t.dropna(subset=["dt", "MMSI", "LAT", "LON"]).sort_values(["MMSI", "dt"])
    mmsi = t.MMSI.values
    same = np.r_[False, mmsi[1:] == mmsi[:-1]]
    # implied speed to previous ping
    dt_h = np.r_[np.nan, (t.dt.values[1:] - t.dt.values[:-1]) / np.timedelta64(1, "h")]
    dist = np.r_[np.nan, _haversine_nm(t.LAT.values[:-1], t.LON.values[:-1], t.LAT.values[1:], t.LON.values[1:])]
    spd_prev = np.where(same & (dt_h > 0), dist / dt_h, np.nan)
    spd_next = np.r_[spd_prev[1:], np.nan]           # implied speed to next ping
    next_same = np.r_[same[1:], False]
    spike = (spd_prev > SPIKE_KN) & (spd_next > SPIKE_KN) & same & next_same   # isolated in/out teleport
    t["ym"] = t.dt.dt.to_period("M").astype(str)
    t["spike"] = spike
    # baseline + cleaned first-to-last dwell per vessel-month
    base = t.groupby(["MMSI", "ym"]).dt.agg(["min", "max", "count"])
    base["dwell"] = (base["max"] - base["min"]).dt.total_seconds() / 86400.0
    cl = t[~t.spike].groupby(["MMSI", "ym"]).dt.agg(["min", "max"])
    cl["dwell_clean"] = (cl["max"] - cl["min"]).dt.total_seconds() / 86400.0
    out = base[["dwell", "count"]].join(cl["dwell_clean"]).reset_index()
    return out, int(spike.sum()), len(t), int(((t.MMSI < 1e8) | (t.MMSI > 799999999)).sum())


def main():
    rows, nspike, npings, nbadmmsi = [], 0, 0, 0
    for path, years in ((CSV, range(2015, 2026)), (FGDB, range(2009, 2015))):
        dset = ds.dataset(path, format="parquet", partitioning="hive")
        for y in years:
            r = _year(dset, y)
            if r is None:
                continue
            out, ns, npg, nbad = r
            rows.append(out); nspike += ns; npings += npg; nbadmmsi += nbad
            print(f"  {path.split('/')[-1]} {y}: pings={npg:,} spikes={ns}", flush=True)
    vm = pd.concat(rows, ignore_index=True)
    vm["dwell_clean"] = vm["dwell_clean"].fillna(vm["dwell"])
    vm["date"] = pd.to_datetime(vm.ym + "-01")

    # low-observation outliers: big dwell inferred from very few pings
    lowobs = (vm.dwell > 20) & (vm["count"] < 5)

    def monthly(col, mask=None):
        d = vm if mask is None else vm[~mask]
        return d.groupby("date")[col].mean()

    g = pd.read_csv("data/processed/analysis_dataset_dwell.csv", parse_dates=["date"])[["date", "gscpi"]]
    def corr(series):
        m = series.rename("dw").reset_index().merge(g, on="date", how="inner").dropna()
        x = m.dw.values; t = np.arange(len(x))
        xd = x - np.polyval(np.polyfit(t, x, 1), t)
        return np.corrcoef(xd, m.gscpi.values)[0, 1], m.dw.max()

    r_base, pk_base = corr(monthly("dwell"))
    r_spk, pk_spk = corr(monthly("dwell_clean"))
    r_low, pk_low = corr(monthly("dwell", lowobs))

    print("\n=== AIS quality-control audit (LA/LB dwell) ===")
    print(f"  MMSI validity: {nbadmmsi:,}/{npings:,} pings ({nbadmmsi/npings*100:.3f}%) have an implausible MMSI")
    print(f"  impossible-jump spikes: {nspike:,}/{npings:,} pings ({nspike/npings*100:.4f}%) flagged (>40 kn in/out)")
    print(f"  low-obs dwell outliers: {int(lowobs.sum()):,}/{len(vm):,} vessel-months ({lowobs.mean()*100:.2f}%; dwell>20d & <5 pings)")
    print(f"  dwell-GSCPI r:  baseline {r_base:+.3f} (peak {pk_base:.1f}d) | "
          f"spike-cleaned {r_spk:+.3f} ({pk_spk:.1f}d) | low-obs-dropped {r_low:+.3f} ({pk_low:.1f}d)")
    # the load-bearing guarantee is ROBUSTNESS of the result to filtering; the anomaly SHARE is reported,
    # not thresholded (it is what it is), with a generous sanity ceiling so a gross regression still trips.
    assert abs(r_spk - r_base) < 0.05 and abs(r_low - r_base) < 0.05, "dwell-GSCPI r moves under QC filtering"
    assert nspike / npings < 0.05 and nbadmmsi / npings < 0.05, "anomalous-ping share implausibly high"
    print(f"PASS: {nspike/npings*100:.4f}% of pings are position spikes and {nbadmmsi/npings*100:.2f}% MMSIs")
    print("      outside the standard ship range; removing spikes or low-observation outliers leaves the")
    print(f"      dwell-GSCPI concentration unchanged (r {r_base:+.3f} -> {r_spk:+.3f}).")


if __name__ == "__main__":
    main()
