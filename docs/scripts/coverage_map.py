"""coverage_map : CatalogueStationIdentities × Admin0Boundaries → CoverageStatusPNG.

Reproduce from the checkout catalogue and Natural Earth 1:50m Admin 0 Countries:

    uv run --with geopandas --with matplotlib python docs/scripts/coverage_map.py \
        --out docs/assets/coverage-map.png

The default boundary URL is public. For offline regeneration, pass --world with a
saved copy of that ZIP. Match ADM0_A3, not sovereign ownership of dependencies.
Counts are unique provider/station identities for observation-capable providers;
they do not assert continuous observations or complete national network coverage.
No station coordinates or station CRS assumptions enter this figure.
Planned countries are fetchers in the legacy kratzert/RivRetrieve-Python repository,
merged or in open pull requests, that have no provider here yet.
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
PLANNED_COUNTRY = {
    "ARG": "Argentina",
    "AUS": "Australia",
    "BEL": "Belgium (Flanders, Wallonia)",
    "CHL": "Chile",
    "DEU": "Germany (Berlin)",
    "DNK": "Denmark",
    "ESP": "Spain",
    "EST": "Estonia",
    "FIN": "Finland",
    "GBR": "United Kingdom (EA, NRFA, SEPA)",
    "GRC": "Greece",
    "IRL": "Ireland (OPW)",
    "ITA": "Italy (Tuscany)",
    "KOR": "South Korea",
    "NLD": "Netherlands",
    "PRT": "Portugal",
    "SVN": "Slovenia",
    "SWE": "Sweden",
    "TWN": "Taiwan",
    "ZAF": "South Africa",
}
ROBINSON = "ESRI:54030"
LAND = "#E3E8EC"
IMPLEMENTED = "#127B8C"
PLANNED = "#F29E38"


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
    """Render implemented and planned countries on a transparent sea, without station geometry."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    counts = country_counts(stations)
    missing = counts.keys() - set(world["ADM0_A3"])
    if missing:
        raise ValueError(f"Boundary source lacks ADM0_A3 countries: {sorted(missing)}")
    land = world.loc[world["ADM0_A3"] != "ATA"].copy()
    land["gauges"] = land["ADM0_A3"].map(counts)
    land = land.to_crs(ROBINSON)
    planned = land.loc[land["ADM0_A3"].isin(PLANNED_COUNTRY.keys() - counts.keys())]
    plt.rcParams["hatch.linewidth"] = 0.9
    fig, ax = plt.subplots(figsize=(14, 7))
    land.plot(ax=ax, color=LAND, edgecolor="white", linewidth=0.25)
    land.loc[land["gauges"].notna()].plot(ax=ax, color=IMPLEMENTED, edgecolor="white", linewidth=0.25)
    if not planned.empty:
        planned.plot(ax=ax, facecolor="none", edgecolor=PLANNED, hatch="////", linewidth=0.5)
    ax.set_axis_off()
    ax.margins(0.01)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0.08)
    handles = [
        Patch(facecolor=IMPLEMENTED, edgecolor="none", label="Implemented"),
        Patch(facecolor="none", edgecolor=PLANNED, hatch="////", label="Coming soon"),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=2,
        fontsize=11,
        handlelength=2.2,
        handleheight=1.2,
        frameon=True,
        facecolor="white",
        edgecolor="none",
        framealpha=1,
        labelcolor="#1F2328",
        borderpad=0.8,
    )
    fig.savefig(out, dpi=200, transparent=True)
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
