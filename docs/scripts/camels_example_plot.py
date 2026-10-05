"""Draw the figure shown on docs/examples/camels-us.md (live USGS request)."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import polars as pl

import rivretrieve as rr

NAMES = {
    "01013500": "Fish River near Fort Kent",
    "01022500": "Narraguagus River at Cherryfield",
    "01030500": "Mattawamkeag River near Mattawamkeag",
}

gauges = rr.find(provider="usgs_nwis", quantity="discharge", frequency="daily", statistic="mean")
camels = rr.pick(gauges, station=list(NAMES))
result = rr.fetch(camels, start="2015-01-01", end="2026-09-30")

BLUE = "#3f86d6"
GREY = "#8a9099"  # readable on both the light and the dark docs theme
fig, axes = plt.subplots(3, 1, figsize=(10, 6.4), sharex=True)
for ax, (station, name) in zip(axes, NAMES.items(), strict=True):
    rows = result.data.filter(pl.col("station_id") == station).sort("time")
    ax.plot(rows["time"], rows["value"], color=BLUE, lw=0.9)
    ax.set_title(f"{name}, Maine", loc="left", fontsize=10, color=GREY)
    ax.set_ylim(bottom=0)
    ax.margins(x=0.005)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GREY)
    ax.tick_params(colors=GREY, labelsize=9)
    ax.grid(axis="y", color=GREY, alpha=0.25, lw=0.6)
    ax.set_axisbelow(True)
fig.supylabel("Discharge (m³/s)", fontsize=10, color=GREY)
fig.tight_layout()
fig.savefig("docs/assets/camels-us-daily.png", dpi=150, transparent=True)
