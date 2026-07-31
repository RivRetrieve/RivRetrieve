from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.za_dws.generate_catalogue import (
    generate_catalogue_from_fixture,
)

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "za_dws_metadata.json"


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 3


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 3


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 9  # 3 stations × 3 products


def test_generate_catalogue_station_fields_x3h001() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "X3H001")
    assert row.height == 1
    assert row["country"][0] == "South Africa"
    assert row["latitude"][0] == pytest.approx(-26.875)
    assert row["longitude"][0] == pytest.approx(28.1111)
    assert row["drainage_area_km2"][0] == pytest.approx(38560.0)


def test_generate_catalogue_null_drainage_area() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "A1H001")
    assert row.height == 1
    assert row["drainage_area_km2"][0] is None
    assert row["elevation_m"][0] is None


def test_generate_catalogue_station_name_split() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "A2H001")
    assert row.height == 1
    # "Krokodil River @ Hartbeespoort" → name=Hartbeespoort
    assert row["name"][0] == "Hartbeespoort"


def test_generate_catalogue_product_ids() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    product_ids = set(cat.products["product_id"].to_list())
    assert product_ids == {"discharge_daily_mean", "discharge_instantaneous", "stage_instantaneous"}
