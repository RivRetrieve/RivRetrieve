"""Catalogue-generation tests retained after archiving BR ANA observations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.br_ana.generate_catalogue import generate_catalogue_from_fixture

_METADATA_FIXTURE = Path(__file__).parent / "test_data" / "br_ana_metadata.json"


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 2


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # discharge_daily_mean, stage_daily_mean, discharge_instantaneous,
    # stage_instantaneous, water_temperature_instantaneous
    assert cat.products.height == 5


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # 2 stations × 5 products = 10
    assert cat.station_products.height == 10


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "12345000")
    assert row.height == 1
    assert row["name"][0] == "RIO XINGU EM ALTAMIRA"
    assert row["country"][0] == "Brazil"
    assert row["elevation_m"][0] == pytest.approx(50.0)
    assert row["drainage_area_km2"][0] == pytest.approx(146080.0)


def test_generate_catalogue_start_end_date_uses_earliest_sub_period() -> None:
    # start_date = min across all sub-period starts (telemetric, discharge, stage, qual_agua)
    # end_date = None if ANY sub-period end is null (station still active for at least one variable)
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)

    # 12345000: discharge/stage both start 1970-01-01, telemetric 2005 — min is 1970.
    # All Fim are null → end_date is None.
    row_12345 = cat.stations.filter(pl.col("station_id") == "12345000")
    assert row_12345["start_date"][0] == datetime(1970, 1, 1).date()
    assert row_12345["end_date"][0] is None

    # 60435000: stage starts 1955-06-01, telemetric 2010 — min is 1955.
    # Stage Fim is null → end_date is None (station still active for stage).
    row_60435 = cat.stations.filter(pl.col("station_id") == "60435000")
    assert row_60435["start_date"][0] == datetime(1955, 6, 1).date()
    assert row_60435["end_date"][0] is None


def test_generate_catalogue_river_name_in_metadata() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "12345000")
    meta = json.loads(row["metadata"][0])
    assert meta["river_name"] == "RIO XINGU"
    assert meta["basin_name"] == "BACIA AMAZONICA"


def test_generate_catalogue_filters_no_coord_station() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    assert "99999999" not in ids


def test_generate_catalogue_filters_pure_pluviometric_station() -> None:
    """Stations with no discharge/level/water-quality flag set are out of scope."""
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    assert "77777000" not in ids


def test_generate_catalogue_keeps_stations_with_any_relevant_type_flag() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    # 12345000: discharge + level; 60435000: level only — both relevant to our products.
    assert {"12345000", "60435000"} <= ids
