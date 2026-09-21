"""coverage_map : CatalogueStationIdentities × Admin0Boundaries → CountShadedPNG.

Reproduce from the checkout catalogue and Natural Earth 1:50m Admin 0 Countries:

    uv run --with geopandas --with matplotlib python docs/scripts/coverage_map.py \
        --out docs/assets/coverage-map.png

The default boundary URL is public. For offline regeneration, pass --world with a
saved copy of that ZIP. Match ADM0_A3, not sovereign ownership of dependencies.
Counts are unique provider/station identities for observation-capable providers;
they do not assert continuous observations or complete national network coverage.
No station coordinates or station CRS assumptions enter this figure.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

import rivretrieve as rr
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers.registration import CatalogueOnly, load_manifest

BOUNDARIES = "https://naturalearth.s3.amazonaws.com/50m_cultural/ne_50m_admin_0_countries.zip"
PROVIDER_COUNTRY = {
    "ba_fhmzbih": "BIH",
    "br_ana": "BRA",
    "ca_eccc": "CAN",
    "ch_foen": "CHE",
    "cz_chmi": "CZE",
    "fr_hubeau": "FRA",
    "fr_hydroportail": "FRA",
    "jp_mlit": "JPN",
    "lt_lhmt": "LTU",
    "no_nve": "NOR",
    "pl_imgw": "POL",
    "th_thaiwater": "THA",
    "usgs_nwis": "USA",
}
ROBINSON = "ESRI:54030"
BACKGROUND = "#FBFCFD"
LAND = "#E3E8EC"


def country_counts(stations: pl.DataFrame) -> dict[str, int]:
    """Count distinct provider/station identities, combining providers per country."""
    counts: dict[str, int] = {}
    for provider, count in (
        stations.select("provider_id", "station_id").unique().group_by("provider_id").len().iter_rows()
    ):
        country = PROVIDER_COUNTRY[provider]
        counts[country] = counts.get(country, 0) + count
    if not counts:
        raise ValueError("Coverage requires at least one observation-capable station")
    return counts


def draw(world, stations: pl.DataFrame, out: Path) -> None:
    """Render country counts without using station geometry."""
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import LogNorm

    counts = country_counts(stations)
    missing = counts.keys() - set(world["ADM0_A3"])
    if missing:
        raise ValueError(f"Boundary source lacks ADM0_A3 countries: {sorted(missing)}")
    land = world.loc[world["ADM0_A3"] != "ATA"].copy()
    land["gauges"] = land["ADM0_A3"].map(counts)
    land = land.to_crs(ROBINSON)
    lower, upper = min(50, min(counts.values())), max(30000, max(counts.values()))
    norm = LogNorm(vmin=lower, vmax=upper)
    fig, ax = plt.subplots(figsize=(14, 7), facecolor=BACKGROUND)
    ax.set_facecolor(BACKGROUND)
    land.plot(ax=ax, color=LAND, linewidth=0)
    land.loc[land["gauges"].notna()].plot(
        ax=ax,
        column="gauges",
        cmap="GnBu",
        norm=norm,
        edgecolor=BACKGROUND,
        linewidth=0.25,
    )
    ax.set_axis_off()
    ax.margins(0.01)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0.12)
    legend = fig.add_axes((0.32, 0.065, 0.36, 0.018))
    ticks = sorted({lower, 100, 500, 1000, 5000, upper})
    bar = fig.colorbar(ScalarMappable(norm=norm, cmap="GnBu"), cax=legend, orientation="horizontal", ticks=ticks)
    bar.ax.set_xticklabels([f"{tick:,}" for tick in ticks])
    bar.ax.minorticks_off()
    bar.ax.tick_params(labelsize=8, length=2)
    bar.set_label("Provider-station records · logarithmic scale", fontsize=9)
    bar.outline.set_visible(False)
    fig.savefig(out, dpi=200, facecolor=BACKGROUND)
    plt.close(fig)


def main() -> None:
    import geopandas as gpd

    parser = argparse.ArgumentParser(description="Draw country coverage by unique gauging station count")
    parser.add_argument("--world", default=BOUNDARIES, help="Natural Earth Admin 0 Countries ZIP or shapefile")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    supported = [
        item.provider_id
        for item in load_manifest(BUILTIN_PROVIDER_IDS)
        if not isinstance(item.declaration.observations, CatalogueOnly)
    ]
    stations = (
        rr.as_frame(rr.find())
        .filter(pl.col("provider_id").is_in(supported))
        .select("provider_id", "station_id")
        .unique()
    )
    counts = country_counts(stations)
    print(stations.group_by("provider_id").len().sort("provider_id"))
    print(
        f"{sum(counts.values()):,} unique provider-station records; {len(supported)} providers; {len(counts)} countries"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    draw(gpd.read_file(args.world), stations, args.out)


if __name__ == "__main__":
    main()
