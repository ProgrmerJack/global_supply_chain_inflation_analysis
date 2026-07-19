"""
Spatial credibility figure for Paper A: the LA/LB port box, NOAA charted anchorage areas, data-driven
berth zones, and where cargo/tanker vessels actually anchored during the Oct-2021 peak. Also states the
terrestrial-AIS limitation: the post-Nov-2021 offshore queue (>150 nm) lies outside the frame.

Run: python src/process_ais/port_map.py   ->  outputs/figures/paperA_fig_map.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import geopandas as gpd
import pyarrow.dataset as ds
import pyarrow.compute as pc

BOX = {"lat_min": 33.65, "lat_max": 33.85, "lon_min": -118.30, "lon_max": -118.10}
PINGS = "data/processed/ais_dwell_census_mode/port_pings"


def main():
    zones = gpd.read_file("config/port_mode_zones_v2.geojson")
    zones = zones[zones.Port == "LA_Long_Beach"]
    anch = gpd.read_file("config/noaa_anchorages.geojson")
    anch = anch[anch.Port == "LA_Long_Beach"]

    # actual anchored cargo/tanker pings at the Oct-2021 peak
    dset = ds.dataset(PINGS, format="parquet", partitioning="hive")
    t = dset.to_table(columns=["LAT", "LON"],
                      filter=(pc.field("Port") == "LA_Long_Beach") & (pc.field("year") == 2021)
                      & (pc.field("month") == 10) & (pc.field("mode") == "anchor")).to_pandas()
    if len(t) > 8000:
        t = t.sample(8000, random_state=0)

    fig, ax = plt.subplots(figsize=(8.4, 7.2))
    ax.add_patch(Rectangle((BOX["lon_min"], BOX["lat_min"]), BOX["lon_max"] - BOX["lon_min"],
                           BOX["lat_max"] - BOX["lat_min"], fill=False, ec="k", lw=1.6, ls="--",
                           label="terrestrial-AIS port box"))
    if len(anch):
        anch.boundary.plot(ax=ax, color="#1f77b4", lw=1.3)
        anch.plot(ax=ax, color="#1f77b4", alpha=0.10)
    for zt, col in [("anchor", "#d62728"), ("berth", "#2ca02c")]:
        z = zones[zones.zone_type.str.lower() == zt]
        if len(z):
            z.boundary.plot(ax=ax, color=col, lw=1.4)
            z.plot(ax=ax, color=col, alpha=0.12)
    ax.scatter(t.LON, t.LAT, s=2, c="k", alpha=0.25, label="anchored cargo/tanker pings, Oct 2021")

    # legend proxies
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [
        Line2D([0], [0], color="k", ls="--", lw=1.6, label="terrestrial-AIS port box"),
        Patch(fc="#1f77b4", alpha=0.3, ec="#1f77b4", label="NOAA charted anchorage areas"),
        Patch(fc="#d62728", alpha=0.3, ec="#d62728", label="data-driven anchor zone"),
        Patch(fc="#2ca02c", alpha=0.3, ec="#2ca02c", label="data-driven berth zone"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="k", markersize=4, alpha=0.5,
               label="anchored pings, Oct 2021"),
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.9)
    ax.set_xlim(BOX["lon_min"] - 0.02, BOX["lon_max"] + 0.02)
    ax.set_ylim(BOX["lat_min"] - 0.02, BOX["lat_max"] + 0.02)
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_title("Los Angeles/Long Beach: charted anchorages, berth zones, and the Oct-2021 anchor cluster")
    ax.annotate("Post-Nov-2021 queuing moved waiting vessels to loiter >150 nm offshore,\n"
                "outside this terrestrial-AIS box (near-port decline is a lower bound on avoided emissions).",
                xy=(0.5, -0.13), xycoords="axes fraction", ha="center", fontsize=8, style="italic")
    fig.tight_layout()
    fig.savefig("outputs/figures/paperA_fig_map.png", dpi=150, bbox_inches="tight")
    print(f"wrote outputs/figures/paperA_fig_map.png ({len(t)} anchor pings plotted)")


if __name__ == "__main__":
    main()
