from __future__ import annotations

from pathlib import Path

import polars as pl

from rivretrieve._internal.providers.cz_chmi.generate_catalogue import generate_catalogue_from_fixture

_METADATA_FIXTURE = Path(__file__).parent / "test_data" / "cz_chmi_metadata.json"


def test_generate_catalogue_from_fixture_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 3


def test_generate_catalogue_from_fixture_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 5


def test_generate_catalogue_from_fixture_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 3 * 5


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "0-203-1-016000")
    assert station.height == 1
    assert station["crs"][0] == "unknown"
