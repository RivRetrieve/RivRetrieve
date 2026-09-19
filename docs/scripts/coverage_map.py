"""coverage_map : PackagedCatalogue × WorldPolygons → PNG   (documentation figure)

Draws every retrievable catalogue station on a borderless world land mass and prints per-continent
station counts underneath. Catalogue-only providers are excluded.

Run from the repository root (geopandas and matplotlib are not project dependencies):

    uv run --with geopandas --with matplotlib python docs/scripts/coverage_map.py \
        --world /path/to/world.shp --out docs/assets/coverage-map.png

The figure reflects the catalogue of the checkout it runs in; generate it from main, not from a feature
branch with an older catalogue.

Station coordinates are plotted as longitude/latitude degrees. Several providers declare their
coordinate reference system as unknown; at world scale the figure does not depend on the datum.
"""

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import polars as pl

import rivretrieve as rr

# Providers whose stations are listed but whose observations cannot be retrieved yet.
CATALOGUE_ONLY = {"za_dws"}

# Provider → continent, following the README coverage table.
PROVIDER_CONTINENT = {
    "ba_fhmzbih": "Europe",
    "br_ana": "Americas",
    "ca_eccc": "Americas",
    "ch_foen": "Europe",
    "cz_chmi": "Europe",
    "fr_hubeau": "Europe",
    "jp_mlit": "Asia",
    "lt_lhmt": "Europe",
    "no_nve": "Europe",
    "pl_imgw": "Europe",
    "th_thaiwater": "Asia",
    "usgs_nwis": "Americas",
    "za_dws": "Africa",
}

ROBINSON = "ESRI:54030"
BACKGROUND = "#FBFCFD"
LAND = "#E4E8ED"
STATION = "#0E7C86"
TEXT = "#23404A"
MUTED = "#6B7F88"


def station_points(stations: pl.DataFrame) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(stations["longitude"].to_list(), stations["latitude"].to_list()),
        crs="EPSG:4326",
    ).to_crs(ROBINSON)


def continent_counts(stations: pl.DataFrame) -> dict[str, int]:
    continents = pl.DataFrame({"provider_id": list(PROVIDER_CONTINENT), "continent": list(PROVIDER_CONTINENT.values())})
    counts = stations.join(continents, on="provider_id").group_by("continent").len()
    return dict(zip(counts["continent"], counts["len"], strict=True))


def draw(world: gpd.GeoDataFrame, stations: pl.DataFrame, out: Path) -> None:
    land = gpd.GeoSeries([world[world.geometry.bounds["maxy"] > -60].union_all()], crs=world.crs).to_crs(ROBINSON)

    fig, ax = plt.subplots(figsize=(14, 7.6), facecolor=BACKGROUND)
    ax.set_facecolor(BACKGROUND)
    land.plot(ax=ax, color=LAND, linewidth=0)
    station_points(stations).plot(ax=ax, color=STATION, markersize=0.8, alpha=0.6, linewidth=0, rasterized=True)
    ax.set_axis_off()
    ax.margins(0.01)

    counts = continent_counts(stations)
    n_providers = stations["provider_id"].n_unique()
    fig.text(
        0.02,
        0.12,
        f"{stations.height:,} stations from {n_providers} national agencies",
        color=TEXT,
        fontsize=15,
        fontweight="bold",
    )
    for i, continent in enumerate(c for c in ("Americas", "Europe", "Africa", "Asia") if counts.get(c)):
        x = 0.02 + i * 0.13
        fig.text(x, 0.065, f"{counts.get(continent, 0):,}", color=STATION, fontsize=14, fontweight="bold")
        fig.text(x, 0.04, continent, color=MUTED, fontsize=10)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0.14)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, facecolor=BACKGROUND)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--world", type=Path, required=True, help="world land or country polygons")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    frame = rr.as_frame(rr.find()).filter(~pl.col("provider_id").is_in(CATALOGUE_ONLY))
    stations = frame.select("provider_id", "station_id", "latitude", "longitude").unique(["provider_id", "station_id"])
    draw(gpd.read_file(args.world), stations, args.out)


if __name__ == "__main__":
    main()
