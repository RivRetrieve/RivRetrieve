"""Catalogue-generation tests retained after archiving ThaiWater observations."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from rivretrieve._internal.providers.th_thaiwater.generate_catalogue import generate_catalogue_from_fixture

_METADATA_FIXTURE = Path(__file__).parent / "test_data" / "th_thaiwater_metadata.json"


def test_generate_catalogue_from_fixture_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # fixture has 4 entries but only 3 are tele_waterlevel
    assert cat.stations.height == 3


def test_generate_catalogue_from_fixture_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 4


def test_generate_catalogue_from_fixture_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 3 * 4


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "S13A")
    assert station.height == 1
    assert station["crs"][0] == "unknown"


def test_generate_catalogue_filters_non_waterlevel_stations() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station_ids = set(cat.stations["station_id"].to_list())
    assert "RAIN01" not in station_ids
