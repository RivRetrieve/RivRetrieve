from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import generate_catalogue_from_fixture

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_HYDRO_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_metadata.json"
_TEMP_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_temp_stations.json"


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    # 2 hydro (with valid coords) + 1 temp (with valid coords) = 3
    assert cat.stations.height == 3


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    assert cat.products.height == 6


def test_generate_catalogue_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    # 2 hydro × 5 products + 1 temp × 1 product = 11
    assert cat.station_products.height == 11


def test_generate_catalogue_hydro_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "O0050010")
    assert station.height == 1
    assert station["name"][0] == "LA BIDOUZE A SAINT-PALAIS"
    assert station["country"][0] == "France"
    assert station["elevation_m"][0] == pytest.approx(42.5)
    assert station["drainage_area_km2"][0] == pytest.approx(830.0)


def test_generate_catalogue_temp_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "T123456001")
    assert station.height == 1
    assert station["name"][0] == "LA DORDOGNE A ARGENTAT"
    assert station["elevation_m"][0] == pytest.approx(148.0)
    assert station["drainage_area_km2"][0] == pytest.approx(6940.0)
    meta = json.loads(station["metadata"][0])
    assert meta["station_type"] == "temperature"


def test_generate_catalogue_filters_no_coord_stations() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station_ids = set(cat.stations["station_id"].to_list())
    assert "K123456001" not in station_ids  # hydro no-coord
    assert "T999999001" not in station_ids  # temp no-coord


def test_generate_catalogue_hydro_station_products() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    hydro_sp = cat.station_products.filter(pl.col("station_id") == "O0050010")
    hydro_products = set(hydro_sp["product_id"].to_list())
    assert hydro_products == {
        "discharge_instantaneous",
        "discharge_daily_mean",
        "discharge_daily_max",
        "stage_instantaneous",
        "stage_daily_max",
    }


def test_generate_catalogue_temp_station_products() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    temp_sp = cat.station_products.filter(pl.col("station_id") == "T123456001")
    assert temp_sp["product_id"].to_list() == ["water_temperature_instantaneous"]
