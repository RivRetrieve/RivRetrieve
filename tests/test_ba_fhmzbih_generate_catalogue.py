from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue import (
    generate_catalogue_from_fixture,
)

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "ba_fhmzbih_metadata.json"


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 2


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 6


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # 2 stations x 6 products = 12
    assert cat.station_products.height == 12


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "4510")
    assert row.height == 1
    assert row["name"][0] == "HS Kaloševići"
    assert row["country"][0] == "Bosnia and Herzegovina"
    assert row["elevation_m"][0] == pytest.approx(233.0)


def test_generate_catalogue_drainage_area_parsed_from_catchment_size() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "4121")
    assert row.height == 1
    assert row["drainage_area_km2"][0] == pytest.approx(123.4)
