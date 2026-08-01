"""Fixture-backed tests for pl_imgw catalogue generation."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.pl_imgw.generate_catalogue import (
    generate_catalogue_from_fixture,
)

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "pl_imgw_metadata.csv"
_STATION_ID = "151140030"


def test_generate_catalogue_station_count_fixture() -> None:
    """Fixture has 3 stations with valid coordinates."""
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 3


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 3


def test_generate_catalogue_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 3 * 3


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == _STATION_ID)
    assert row.height == 1
    assert row["crs"][0] == "unknown"
    assert row["latitude"][0] == pytest.approx(51.5252, abs=1e-3)
    assert row["longitude"][0] == pytest.approx(14.8218, abs=1e-3)


def test_generate_catalogue_product_ids() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.products["product_id"].to_list())
    assert ids == {"discharge_daily_mean", "stage_daily_mean", "water_temperature_daily_mean"}


def test_generate_catalogue_all_availability_unknown() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products["availability"].cast(pl.Utf8).to_list() == ["unknown"] * 9
