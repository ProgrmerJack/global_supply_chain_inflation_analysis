"""Build the four manuscript figure sets from frozen repository artifacts.

    python scripts/build_publication_figures.py --paper all
    python scripts/build_publication_figures.py --paper A

Each paper is a self-sufficient bundle under manuscript/: figures land in
manuscript/<bundle>/figures/ as a 300-dpi PNG plus a vector PDF, named paper{A,B,C,D}_*.
Papers B/C/D are drawn here from results/ and data/ artifacts; Paper A delegates to the analysis
modules that produce and assert its numbers (see paperA below).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.dates import YearLocator, DateFormatter
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BUNDLES = {"A": "paper_A_CEE", "B": "paper_B_scidata", "C": "paper_C_trip", "D": "paper_D_ocm"}
BLUE, ORANGE, GREEN, RED, GREY = "#1f5a7a", "#d97706", "#39734d", "#b33a3a", "#68737d"


def _save(fig: plt.Figure, name: str) -> None:
    """Write into the owning paper's self-sufficient bundle, inferred from the paperX_ prefix."""
    out = ROOT / "manuscript" / BUNDLES[name[len("paper")]] / "figures"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / name, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out / Path(name).with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _paperB_graphical_abstract() -> None:
    panel = pd.read_csv(ROOT / "data/processed/national_activity_month.csv")
    manifest = pd.read_csv(ROOT / "data/interim/national_pings/ingestion_manifest.csv")
    daily = manifest.loc[manifest.status.eq("ok")].drop_duplicates("date", keep="last").copy()
    daily["date"] = pd.to_datetime(daily.date, format="%Y-%m-%d")
    daily = daily.sort_values("date")
    cov = panel.pivot(index="port_complex_id", columns="year_month", values="days_sampled")

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.1), gridspec_kw={"width_ratios": [1.45, 1.2, .8]})
    ax = axes[0]
    ax.plot(daily.date, daily.retained_pings, color=BLUE, alpha=.22, lw=.45)
    ax.plot(daily.date, daily.retained_pings.rolling(31, center=True, min_periods=15).median(),
            color=ORANGE, lw=1.45)
    ax.set(xlabel="UTC source date", ylabel="Retained reports per day", title="a  Daily corpus volume")
    ax.grid(alpha=.16)

    ax = axes[1]
    im = ax.imshow(cov, aspect="auto", vmin=0, vmax=31, cmap="Blues")
    ticks = np.arange(0, len(cov.columns), 24)
    ax.set_xticks(ticks, labels=[cov.columns[i][:4] for i in ticks], rotation=45)
    ax.set_yticks([])
    ax.set(xlabel="Complex-month", ylabel="15 port complexes", title="b  Daily temporal support")
    fig.colorbar(im, ax=ax, label="Days sampled", fraction=.047, pad=.03)

    ax = axes[2]
    values = np.array([daily.retained_pings.sum(), len(panel),
                       len(pd.read_csv(ROOT / "data/processed/vessel_characteristics.csv"))])
    labels = ["Retained\nreports", "Complex-\nmonths", "Vessel\nrecords"]
    ax.bar(labels, values, color=[BLUE, GREEN, ORANGE])
    ax.set_yscale("log")
    ax.set(ylabel="Record count (log scale)", title="c  Published products", ylim=(500, 2e9))
    for i, value in enumerate(values):
        ax.text(i, value * 1.25, f"{value:,.0f}", ha="center", fontsize=8)
    ax.grid(axis="y", alpha=.16)
    fig.suptitle("National terrestrial AIS corpus: observed coverage and released products",
                 x=.06, ha="left", fontsize=14, weight="bold", color=BLUE)
    fig.text(.06, .01, "Scope: activity records; not operational-state, emissions, exposure, or causal ground truth.",
             fontsize=9, color=RED)
    fig.subplots_adjust(top=.78, bottom=.22, wspace=.38)
    _save(fig, "paperB_graphical_abstract.png")


def _paperC_graphical_abstract() -> None:
    g1 = json.loads((ROOT / "results/development/G1_ais_fullcensus/gate_decision_ves_wgt_mo.json").read_text())
    spb = pd.read_csv(ROOT / "results/development/spb_queue_boundary_reanalysis/date_placebos.csv")
    audit = json.loads((ROOT / "results/confirmatory/baltimore_shock/b_g2_audit.json").read_text())
    corr = pd.Series(g1["components"]["activity_correlation"]["per_port_correlations"]).sort_values()
    date_col = "event" if "event" in spb.columns else next(c for c in spb.columns if "date" in c.lower())
    effect_col = next((c for c in spb.columns if c.lower() in {"estimate", "effect", "ddd"}), None)
    if effect_col is None:
        effect_col = next(c for c in spb.select_dtypes("number").columns if "p" not in c.lower())
    spb[date_col] = pd.to_datetime(spb[date_col], format="%Y-%m-%d", errors="coerce")
    gaps = pd.DataFrame(audit["gap_sensitivity"])
    rg1 = json.loads((ROOT / "results/confirmatory/nature_recovery/r_g1_call_measurement.json").read_text())

    fig, axes = plt.subplots(1, 4, figsize=(16.6, 4.2))
    ax = axes[0]
    ax.plot(corr.to_numpy(), np.arange(1, len(corr) + 1), "o", color=BLUE, ms=5)
    ax.axvline(.8, color=RED, ls="--", label="Registered minimum")
    ax.axvline(corr.median(), color=ORANGE, ls=":", label=f"Median {corr.median():.3f}")
    ax.set(xlabel="Within-port correlation", ylabel="Ordered port complex", title="a  Construct validity")
    ax.legend(frameon=False, fontsize=8); ax.grid(alpha=.16)

    ax = axes[1]
    ax.plot(spb[date_col], spb[effect_col], "o-", color=BLUE, ms=3, lw=1)
    ax.axhline(0, color=GREY, lw=.8)
    ax.axvline(pd.Timestamp("2021-11-16"), color=RED, ls="--", label="Policy date")
    ax.xaxis.set_major_locator(YearLocator())
    ax.xaxis.set_major_formatter(DateFormatter("%Y"))
    ax.set(xlabel="Candidate intervention date", ylabel="Boundary estimate", title="b  Temporal specificity")
    ax.legend(frameon=False, fontsize=8); ax.grid(alpha=.16)

    ax = axes[2]
    ax.plot(gaps.gap_hours, gaps.receiver_ddd, "o-", color=BLUE, label="Receiver network")
    ax.plot(gaps.gap_hours, gaps.placebo_ddd, "s--", color=RED, label="Negative controls")
    ax.axhline(0, color=GREY, lw=.8)
    ax.set(xlabel="Episode gap (hours)", ylabel="DDD estimate", title="c  Network specificity")
    ax.legend(frameon=False, fontsize=8); ax.grid(alpha=.16)

    ax = axes[3]
    comp = rg1["official_2024_comparator"]
    units = ["Los\nAngeles", "Long\nBeach", "Combined\ncomplex"]
    errs = [comp["absolute_fractional_error_by_port"]["Los Angeles"] * 100,
            comp["absolute_fractional_error_by_port"]["Long Beach"] * 100,
            comp["absolute_fractional_error_combined"] * 100]
    lims = [25, 25, 15]
    ax.bar(units, errs, .55, color=[RED if e > t else GREEN for e, t in zip(errs, lims)])
    ax.axhline(25, color=RED, ls="--", lw=1, label="Per-port limit")
    ax.set(ylabel="Arrival error (%)", title="d  Unit of analysis")
    ax.legend(frameon=False, fontsize=8); ax.grid(axis="y", alpha=.16)

    fig.suptitle("Reliable AIS measurement is not sufficient for valid causal inference",
                 x=.05, ha="left", fontsize=14, weight="bold", color=BLUE)
    fig.text(.05, .015, "Split-half reliability r = 0.993; preregistered construct, unit and specificity tests fail.",
             fontsize=9, color=RED)
    fig.subplots_adjust(top=.78, bottom=.22, wspace=.34)
    _save(fig, "paperC_graphical_abstract.png")


def _paperD_graphical_abstract() -> None:
    h1 = pd.read_csv(ROOT / "results/deep_case_SPB/H1_cargo_massbalance.csv")
    inv = pd.read_csv(ROOT / "results/development/spb_freight_boundary/spb_sector_pollutant_2018_2024.csv")
    aq = pd.read_csv(ROOT / "results/deep_case_SPB/aq_wind_oriented.csv")
    totals = inv.drop_duplicates(["year", "pollutant"])[["year", "pollutant", "spb_all_sector_total"]]
    change = totals.pivot(index="pollutant", columns="year", values="spb_all_sector_total")
    pct = (100 * (change[2024] / change[2018] - 1)).reindex(["CO2e", "NOx", "DPM", "SOx"])

    ring_labels = {"0-50nm": "0–50", "50-150nm": "50–150", "150-300nm": "150–300",
                   "total_0_300": "Total"}
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    ax = axes[0]
    ax.bar([ring_labels.get(r, str(r)) for r in h1.ring], h1.abs_change,
           color=np.where(h1.abs_change < 0, RED, BLUE))
    ax.axhline(0, color=GREY, lw=.8)
    ax.set(xlabel="Frozen distance ring (nm)", ylabel="Change (vessel-hours month$^{-1}$)",
           title="a  Cargo-presence redistribution")
    ax.tick_params(axis="x", rotation=25); ax.grid(axis="y", alpha=.16)

    ax = axes[1]
    ax.bar(pct.index, pct.values, color=np.where(pct.values < 0, GREEN, ORANGE))
    ax.axhline(0, color=GREY, lw=.8)
    ax.set(xlabel="Pollutant", ylabel="2018–2024 change (%)", title="b  Official boundary inventory")
    span = pct.values.max() - pct.values.min()
    ax.set_ylim(pct.values.min() - .22 * span, pct.values.max() + .22 * span)
    for i, value in enumerate(pct.values):
        offset = .06 * span if value >= 0 else -.06 * span
        ax.text(i, value + offset, f"{value:+.1f}%", ha="center", fontsize=8,
                va="bottom" if value >= 0 else "top")
    ax.grid(axis="y", alpha=.16)

    ax = axes[2]
    ax.bar(aq.site.astype(str), aq.downwind_excess, color=RED)
    ax.axhline(0, color=GREY, lw=.8)
    ax.set(xlabel="AQS site", ylabel="Downwind − upwind NO₂ (ppb)", title="c  Observed monitor contrast")
    ax.tick_params(axis="x", rotation=25); ax.grid(axis="y", alpha=.16)
    fig.suptitle("San Pedro Bay: redistribution evidence with explicit outcome boundaries",
                 x=.06, ha="left", fontsize=14, weight="bold", color=BLUE)
    fig.text(.06, .015, "Presence shifts and inventory trends are supported; the registered observed NO₂ link is not.",
             fontsize=9, color=RED)
    fig.subplots_adjust(top=.78, bottom=.24, wspace=.36)
    _save(fig, "paperD_graphical_abstract.png")


def paperB() -> None:
    _paperB_graphical_abstract()
    panel = pd.read_csv(ROOT / "data/processed/national_activity_month.csv")
    vessels = pd.read_csv(ROOT / "data/processed/vessel_characteristics.csv")
    areas = gpd.read_file(ROOT / "config/geometry/port_areas_usace.geojson")
    assignment = pd.read_csv(ROOT / "config/registries/port_area_assignment_coverage.csv")
    assignable = set(assignment.loc[assignment.spatial_assignment_status.eq("assignable"), "port_complex_id"])
    areas = areas[areas.port_complex_id.isin(assignable)]
    assert len(areas) == len(assignable) == 15, "The publication map must contain exactly the 15 assignable complexes"
    # At national scale each assignment polygon is only a few km across, so inline labels
    # collide along the east coast. Number the complexes on the map and key them alongside.
    geo = areas.to_crs(4326).copy()
    points = geo.geometry.representative_point()
    geo["lon_pt"] = points.x.to_numpy()
    geo["lat_pt"] = points.y.to_numpy()
    geo["label"] = geo.port_complex_id.astype(str).str.replace("_", " ")
    geo = geo.sort_values("label").reset_index(drop=True)
    fig, (ax, key) = plt.subplots(1, 2, figsize=(11, 5.4), gridspec_kw={"width_ratios": [3, 1]})
    geo.plot(ax=ax, color=BLUE, edgecolor=BLUE, linewidth=.4)
    ax.scatter(geo["lon_pt"], geo["lat_pt"], s=115, facecolor="white",
               edgecolor=BLUE, linewidth=1.2, zorder=3)
    for i, row in geo.iterrows():
        ax.annotate(str(i + 1), (row["lon_pt"], row["lat_pt"]), ha="center", va="center",
                    fontsize=7.5, color=BLUE, weight="bold", zorder=4)
    ax.set(xlim=(-127, -64), ylim=(23, 48), xlabel="Longitude", ylabel="Latitude",
           title="Fifteen spatially assignable port complexes")
    ax.grid(alpha=.2)
    key.axis("off")
    key.set_title("Complex key", fontsize=9, loc="left")
    for i, row in geo.iterrows():
        key.text(0, .96 - i * .064, f"{i + 1:>2}  {row['label']}", fontsize=8.5,
                 va="top", family="monospace", transform=key.transAxes)
    fig.tight_layout()
    _save(fig, "paperB_scope_map.png")

    cov = panel.pivot(index="port_complex_id", columns="year_month", values="days_sampled")
    fig, ax = plt.subplots(figsize=(12, 5.5))
    im = ax.imshow(cov, aspect="auto", vmin=0, vmax=31, cmap="Blues")
    ax.set_yticks(range(len(cov)), labels=[x.replace("_", " ") for x in cov.index], fontsize=8)
    ticks = np.arange(0, len(cov.columns), 12)
    ax.set_xticks(ticks, labels=[cov.columns[i][:4] for i in ticks], rotation=45)
    ax.set(title="Daily support in every complex-month", xlabel="Month")
    fig.colorbar(im, ax=ax, label="Days sampled")
    _save(fig, "paperB_coverage.png")

    annual = panel.assign(year=panel.year_month.str[:4].astype(int)).groupby("year", as_index=False).agg(
        freight_calls=("freight_port_calls", "sum"), ship_days=("ship_days", "sum"))
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.plot(annual.year, annual.freight_calls, marker="o", color=BLUE, label="Freight call starts")
    ax.set(xlabel="Year", ylabel="Freight call starts", title="National monthly-panel activity products")
    ax2 = ax.twinx()
    ax2.plot(annual.year, annual.ship_days, marker="s", color=ORANGE, label="Ship-days")
    ax2.set_ylabel("Ship-days", color=ORANGE)
    ax.grid(alpha=.2)
    _save(fig, "paperB_activity.png")

    coverage = vessels[["length_m", "width_m", "draft_m", "vessel_type", "imo"]].notna().mean().mul(100)
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.bar(coverage.index.str.replace("_", " "), coverage, color=[BLUE, BLUE, BLUE, GREEN, GREY])
    ax.set(ylabel="Non-missing records (%)", ylim=(0, 105), title="Sparse-sample vessel-characteristic coverage")
    for i, value in enumerate(coverage):
        ax.text(i, value + 2, f"{value:.1f}%", ha="center", fontsize=9)
    _save(fig, "paperB_characteristics.png")

    manifest = pd.read_csv(ROOT / "data/interim/national_pings/ingestion_manifest.csv")
    daily = manifest.loc[manifest.status.eq("ok")].drop_duplicates("date", keep="last").copy()
    daily["date"] = pd.to_datetime(daily.date, format="%Y-%m-%d")
    daily = daily.sort_values("date")
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.plot(daily.date, daily.retained_pings, color=BLUE, alpha=.22, lw=.6, label="Daily retained reports")
    ax.plot(daily.date, daily.retained_pings.rolling(31, center=True, min_periods=15).median(),
            color=ORANGE, lw=1.8, label="31-day rolling median")
    ax.set(xlabel="UTC source date", ylabel="Retained reports", title="Daily corpus volume and reception variation")
    ax.grid(alpha=.18); ax.legend(frameon=False)
    _save(fig, "paperB_daily_volume.png")

    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    years = panel.year_month.str[:4].astype(int)
    scatter = ax.scatter(panel.freight_port_calls, panel.ship_days, c=years, cmap="viridis",
                         s=13, alpha=.55, linewidths=0)
    ax.set(xlabel="24-hour gap-defined freight call starts", ylabel="Integrated ship-days",
           title="Related activity products remain non-interchangeable")
    ax.grid(alpha=.18)
    fig.colorbar(scatter, ax=ax, label="Year")
    _save(fig, "paperB_activity_relationship.png")


def paperC() -> None:
    _paperC_graphical_abstract()
    g1 = json.loads((ROOT / "results/development/G1_ais_fullcensus/gate_decision_ves_wgt_mo.json").read_text())
    spb = pd.read_csv(ROOT / "results/development/spb_queue_boundary_reanalysis/date_placebos.csv")
    b2 = json.loads((ROOT / "results/confirmatory/baltimore_shock/b_g2.json").read_text())
    audit = json.loads((ROOT / "results/confirmatory/baltimore_shock/b_g2_audit.json").read_text())
    corr = pd.Series(g1["components"]["activity_correlation"]["per_port_correlations"]).sort_values()
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh([x.replace("_", " ") for x in corr.index], corr, color=np.where(corr >= .8, GREEN, BLUE))
    ax.axvline(.8, color=RED, ls="--", label="registered minimum")
    ax.axvline(corr.median(), color=ORANGE, ls=":", label=f"median {corr.median():.3f}")
    ax.set(xlabel="Pearson correlation", title="AIS freight call starts versus imports-only vessel weight")
    ax.legend()
    _save(fig, "paperC_g1_correlations.png")

    labels = ["Ingestion", "National scope", "Activity construct", "Motion reference"]
    passed = [True, True, False, False]
    notes = ["4,018/4,018 days", "15/15 complexes",
             "median r = 0.320\n0/15 at r >= 0.80", "macro-F1 = 0.729\n60.85% unresolved"]
    fig, ax = plt.subplots(figsize=(7.8, 4.6))
    ax.bar(labels, [1] * 4, color=[GREEN if p else RED for p in passed])
    for i, (ok, note) in enumerate(zip(passed, notes)):
        ax.text(i, .84, "PASS" if ok else "FAIL", ha="center", color="white", weight="bold", fontsize=13)
        ax.text(i, .42, note, ha="center", va="center", color="white", fontsize=8.5)
    ax.set(ylim=(0, 1.02), title="G1 component-separated validity scorecard")
    ax.set_yticks([])
    for side in ("left", "right", "top"):
        ax.spines[side].set_visible(False)
    _save(fig, "paperC_g1_scorecard.png")

    date_col = "event" if "event" in spb.columns else next(c for c in spb.columns if "date" in c.lower())
    effect_col = next((c for c in spb.columns if c.lower() in {"estimate", "effect", "ddd"}), None)
    if effect_col is None:
        effect_col = next(c for c in spb.select_dtypes("number").columns if "p" not in c.lower())
    spb[date_col] = pd.to_datetime(spb[date_col], format="%Y-%m-%d", errors="coerce")
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.plot(spb[date_col], spb[effect_col], marker="o", ms=3, color=BLUE)
    ax.axhline(0, color=GREY, lw=1)
    ax.axvline(pd.Timestamp("2021-11-16"), color=RED, ls="--", label="policy date")
    ax.xaxis.set_major_locator(YearLocator())
    ax.xaxis.set_major_formatter(DateFormatter("%Y"))
    ax.set(ylabel="Boundary estimate", xlabel="Candidate intervention date",
           title="San Pedro Bay temporal-placebo distribution")
    ax.legend()
    _save(fig, "paperC_spb_placebos.png")

    gaps = pd.DataFrame(audit["gap_sensitivity"])
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.plot(gaps.gap_hours, gaps.receiver_ddd, marker="o", color=BLUE, label="Receiver network")
    ax.plot(gaps.gap_hours, gaps.placebo_ddd, marker="s", color=RED, label="Negative-control ports")
    ax.set(xlabel="Episode gap (hours)", ylabel="DDD estimate",
           title=f"Baltimore response is not receiver-specific (registered p={b2['one_sided_randomization_p']:.3f})")
    ax.legend(); ax.grid(alpha=.2)
    _save(fig, "paperC_baltimore_falsification.png")

    official = pd.read_csv(ROOT / "data/processed/official_port_activity_ves_wgt_mo.csv")
    joined = panel = pd.read_csv(ROOT / "data/processed/national_activity_month.csv")
    joined = joined.merge(official, on=["port_complex_id", "year_month"], how="inner")
    comparator = "official_activity"
    joined["year"] = joined.year_month.str[:4].astype(int)
    by_year = joined.groupby(["year", "port_complex_id"]).apply(
        lambda d: d.freight_port_calls.corr(d[comparator]), include_groups=False
    ).rename("r").reset_index().groupby("year").r.median()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.plot(by_year.index, by_year, marker="o", color=BLUE)
    ax.axhline(.8, color=RED, ls="--", label="registered minimum")
    ax.axhline(.32, color=ORANGE, ls=":", label="full-period median")
    ax.set(xlabel="Year", ylabel="Median within-port correlation",
           title="Within-port construct agreement remains below the registered minimum", ylim=(-.2, 1))
    ax.grid(alpha=.2); ax.legend(frameon=False)
    _save(fig, "paperC_g1_year_decomposition.png")

    decision = json.loads((ROOT / "results/development/spb_queue_boundary_reanalysis/decision.json").read_text())
    rows = [{"window": 52, **decision["primary_ddd"]}]
    rows += [{"window": int(x["window_weeks"]), **x} for x in decision["sensitivity_summary"]
             if x["sensitivity"] in {"ddd_26_week", "ddd_78_week"}]
    sens = pd.DataFrame(rows).sort_values("window")
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.errorbar(sens.window, sens.estimate,
                yerr=[sens.estimate - sens.ci_low, sens.ci_high - sens.estimate],
                fmt="o", color=BLUE, ecolor=GREY, capsize=4)
    ax.axhline(0, color=GREY, lw=1)
    ax.set(xlabel="Symmetric window (weeks)", ylabel="West-boundary triple difference",
           title="San Pedro Bay estimate changes materially with the window")
    ax.grid(alpha=.18)
    _save(fig, "paperC_spb_window_sensitivity.png")

    decomposition = audit["registered_24h_decomposition"]
    labels = ["Receiver network", "Negative-control network"]
    linked = [decomposition["receiver_network"]["linked_component"],
              decomposition["placebo_network"]["linked_component"]]
    comparison = [-decomposition["receiver_network"]["comparison_component"],
                  -decomposition["placebo_network"]["comparison_component"]]
    x = np.arange(2); width = .34
    fig, ax = plt.subplots(figsize=(7.8, 4.8))
    ax.bar(x - width / 2, linked, width, color=BLUE, label="Linked-fleet component")
    ax.bar(x + width / 2, comparison, width, color=ORANGE, label="Comparison-fleet decline component")
    ax.axhline(0, color=GREY, lw=1)
    ax.set_xticks(x, labels)
    ax.set(ylabel="Contribution to DDD", title="Baltimore signal is generated by comparison-fleet decline")
    ax.legend(frameon=False); ax.grid(axis="y", alpha=.18)
    _save(fig, "paperC_baltimore_decomposition.png")

    rg1 = json.loads((ROOT / "results/confirmatory/nature_recovery/r_g1_call_measurement.json").read_text())
    comp = rg1["official_2024_comparator"]
    units = ["Port of\nLos Angeles", "Port of\nLong Beach", "Combined\nSan Pedro Bay"]
    ais = [comp["ais_by_terminal_port"]["Los Angeles"],
           comp["ais_by_terminal_port"]["Long Beach"],
           comp["ais_complete_regulatory_visits"]]
    official_counts = [comp["port_totals"]["Port of Los Angeles"],
                       comp["port_totals"]["Port of Long Beach"],
                       comp["spb_total"]]
    errors = [comp["absolute_fractional_error_by_port"]["Los Angeles"] * 100,
              comp["absolute_fractional_error_by_port"]["Long Beach"] * 100,
              comp["absolute_fractional_error_combined"] * 100]
    limits = [25, 25, 15]
    x = np.arange(3); width = .36
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.4))
    axes[0].bar(x - width / 2, ais, width, color=BLUE, label="AIS reconstructed")
    axes[0].bar(x + width / 2, official_counts, width, color=GREY, label="Official 2024 arrivals")
    axes[0].set_xticks(x, units)
    axes[0].set(ylabel="2024 regulatory tanker arrivals",
                title="Counts agree for the complex, not for its ports")
    axes[0].legend(frameon=False); axes[0].grid(axis="y", alpha=.18)
    axes[1].bar(x, errors, .5, color=[RED if e > t else GREEN for e, t in zip(errors, limits)])
    axes[1].axhline(25, color=RED, ls="--", lw=1, label="25% per-port limit")
    axes[1].axhline(15, color=ORANGE, ls=":", lw=1, label="15% combined limit")
    axes[1].set_xticks(x, units)
    axes[1].set(ylabel="Absolute fractional error (%)",
                title="Only the registered port unit breaches tolerance")
    axes[1].legend(frameon=False); axes[1].grid(axis="y", alpha=.18)
    fig.tight_layout()
    _save(fig, "paperC_rg1_unit_attribution.png")


def paperD() -> None:
    _paperD_graphical_abstract()
    h1 = pd.read_csv(ROOT / "results/deep_case_SPB/H1_cargo_massbalance.csv")
    inv = pd.read_csv(ROOT / "results/development/spb_freight_boundary/spb_sector_pollutant_2018_2024.csv")
    aq = pd.read_csv(ROOT / "results/deep_case_SPB/aq_wind_oriented.csv")
    equity = pd.read_csv(ROOT / "results/deep_case_SPB/H5_equity_baseline.csv").set_index("group")
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    colors = [RED if x < 0 else BLUE for x in h1.abs_change]
    ring_labels = {"0-50nm": "0–50 nm", "50-150nm": "50–150 nm", "150-300nm": "150–300 nm",
                   "total_0_300": "Total\n0–300 nm"}
    ax.bar([ring_labels.get(r, str(r)) for r in h1.ring], h1.abs_change, color=colors)
    ax.axhline(0, color=GREY, lw=1)
    ax.set(ylabel="Change in vessel-hours per month", title="Cargo-presence accounting around San Pedro Bay")
    for i, v in enumerate(h1.abs_change): ax.text(i, v + (250 if v >= 0 else -650), f"{v:+,.0f}", ha="center")
    _save(fig, "paperD_spatial_accounting.png")

    totals = inv.drop_duplicates(["year", "pollutant"])[["year", "pollutant", "spb_all_sector_total"]]
    fig, axes = plt.subplots(2, 2, figsize=(9, 6.5), sharex=True)
    for ax, pollutant in zip(axes.flat, ["CO2e", "NOx", "DPM", "SOx"]):
        d = totals[totals.pollutant.eq(pollutant)]
        ax.plot(d.year, d.spb_all_sector_total, marker="o", color=BLUE)
        ax.set_title(pollutant); ax.grid(alpha=.2)
    fig.suptitle("Official five-sector San Pedro Bay inventory totals, 2018–2024")
    fig.supxlabel("Inventory year")
    _save(fig, "paperD_inventory_trends.png")

    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.bar(aq.site.astype(str), aq.downwind_excess, color=RED)
    ax.axhline(0, color=GREY, lw=1)
    ax.set(xlabel="AQS site", ylabel="Downwind − upwind NO₂ (ppb)",
           title="Naïve wind-oriented contrast reverses the port-source expectation")
    _save(fig, "paperD_aq_null.png")

    categories = ["Median income\n($000)", "Black share\n(%)", "CES burden\n(percentile)", "PM2.5\n(µg m$^{-3}$)"]
    columns = ["population_weighted_tract_median_income_usd", "black_share_pct",
               "mean_ces_score_percentile", "mean_pm25_ug_m3"]
    port = equity.loc["port_adjacent", columns].to_numpy(dtype=float); port[0] /= 1000
    county = equity.loc["los_angeles_county", columns].to_numpy(dtype=float); county[0] /= 1000
    fig, axes = plt.subplots(2, 2, figsize=(8.5, 6.2), layout="constrained")
    for ax, label, p_value, c_value in zip(axes.flat, categories, port, county):
        ax.bar([0, 1], [p_value, c_value], color=[BLUE, GREY])
        ax.set_xticks([0, 1], ["Port-adjacent", "LA County"], fontsize=8)
        ax.set_title(label)
        for i, value in enumerate((p_value, c_value)):
            ax.text(i, value, f"{value:.1f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle("Descriptive environmental-justice baseline")
    _save(fig, "paperD_equity_baseline.png")

    sectors = ["ocean_going_vessels", "harbor_craft", "cargo_handling_equipment",
               "locomotives", "heavy_duty_vehicles"]
    sector_labels = ["OGV", "Harbor craft", "Cargo handling", "Rail", "Trucks"]
    colors = [BLUE, "#4c956c", ORANGE, "#8e6c8a", GREY]
    fig, axes = plt.subplots(2, 2, figsize=(10, 7.2), sharex=True, layout="constrained")
    for ax, pollutant in zip(axes.flat, ["CO2e", "NOx", "DPM", "SOx"]):
        d = inv[inv.pollutant.eq(pollutant)].pivot(index="year", columns="source_category",
                                                   values="reported_quantity").loc[[2018, 2024], sectors]
        bottom = np.zeros(2)
        for sector, label, color in zip(sectors, sector_labels, colors):
            values = d[sector].to_numpy()
            ax.bar([2018, 2024], values, bottom=bottom, color=color, label=label)
            bottom += values
        ax.set_title(pollutant); ax.set_xticks([2018, 2024]); ax.grid(axis="y", alpha=.16)
    axes[0, 0].set_ylabel("Metric tonnes")
    axes[1, 0].set_ylabel("Short tons")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=5, loc="outside lower center", frameon=False)
    fig.suptitle("Sector composition differs by pollutant and year")
    _save(fig, "paperD_inventory_composition.png")


def paperA() -> None:
    """Paper A's display items are produced by the analysis code that verifies them, so they are
    rebuilt by invoking those modules rather than duplicating the estimation here. Two of them
    (`state_lp`, `reform_event_study`) are assert-guarded, so a figure that builds is also a result
    that still reproduces."""
    import subprocess
    import sys
    for module in ("src/emissions/paper_a_figures.py", "src/process_ais/port_map.py",
                   "src/models/state_lp.py", "src/emissions/reform_event_study.py"):
        subprocess.run([sys.executable, module], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build manuscript figures for one paper or all four.")
    parser.add_argument("--paper", choices=["A", "B", "C", "D", "all"], default="all")
    args = parser.parse_args()
    for key, function in (("A", paperA), ("B", paperB), ("C", paperC), ("D", paperD)):
        if args.paper in {key, "all"}: function()


if __name__ == "__main__":
    main()
