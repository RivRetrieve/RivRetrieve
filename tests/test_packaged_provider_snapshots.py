"""Independent expectations for approved packaged provider snapshots."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.registry import _registry
from tests._catalogue import catalogue_reader, provider_info


def test_dws_packaged_snapshot_is_discoverable() -> None:
    provider = "za_dws"
    assert provider in rr.providers()["provider_id"]
    reader = catalogue_reader(provider)
    info = provider_info(provider)
    stations = reader.read_stations().data
    products = reader.read_products().data
    station_products = reader.read_station_products().data
    product_ids = {"discharge_daily_mean", "discharge_instantaneous", "stage_instantaneous"}

    assert info.provider_id == provider
    assert info.name == "Department of Water and Sanitation — Verified Hydrology (DWS, South Africa)"
    assert str(info.catalogue_version) == "2026-08-02"
    assert stations.height == 2905
    assert stations["crs"].unique().to_list() == ["unknown"]
    assert products.height == 3
    assert set(products["product_id"]) == product_ids
    assert set(products["provider_id"]) == {provider}
    assert station_products.height == 8715
    assert station_products.height == stations.height * products.height
    assert set(station_products["availability"].cast(str)) == {"unknown"}
    assert set(rr.products(provider=provider)) == product_ids


def test_dws_catalogue_refuses_observation_retrieval() -> None:
    rr.providers()
    with pytest.raises(ObservationsUnavailableError, match="za_dws"):
        _registry.get("za_dws").observations(stations="unused", products="unused", start=None, end=None)


def test_nve_packaged_snapshot_retains_availability_states() -> None:
    station_products = catalogue_reader("no_nve").read_station_products().data
    assert station_products.height == 44_118
    assert set(station_products["availability"].cast(str)) == {"available", "unavailable"}


def test_jp_mlit_packaged_source_coordinates_are_adopted() -> None:
    stations = catalogue_reader("jp_mlit").read_stations().data
    expected = {
        "302011282228100": (37.415277777777774, 140.48333333333332),
        "302011282218050": (37.81111111111111, 140.4958333333333),
        "308011288805010": (33.78333333333333, 132.8738888888889),
    }
    assert "307051287711040" not in stations["station_id"].to_list()
    assert stations["crs"].unique().to_list() == ["unknown"]
    for station_id, coordinates in expected.items():
        row = stations.filter(pl.col("station_id") == station_id)
        assert row.select("latitude", "longitude").row(0) == coordinates


def test_lithuanian_packaged_snapshot_preserves_declared_scope() -> None:
    catalogue = catalogue_reader("lt_lhmt").artifact
    assert catalogue.stations.height == 97
    assert catalogue.products.height == 2
    assert set(catalogue.products["product_id"]) == {"discharge_daily_mean", "stage_daily_mean"}
    assert catalogue.station_products.height == 194
    assert set(catalogue.station_products["availability"].cast(str)) == {"unknown"}
    station_ids = catalogue.stations["station_id"].to_list()
    assert station_ids == sorted(station_ids)
    assert catalogue.stations.columns == ["provider_id", "station_id", "latitude", "longitude", "crs"]
    assert catalogue.stations["crs"].unique().to_list() == ["EPSG:4326"]
    assert catalogue.provider_info["provider_id"] == "lt_lhmt"
    assert catalogue.provider_info["catalogue_version"] == "2026-08-01"
    assert catalogue.station_products["last_catalogue_check"].unique().to_list() == [date(2026, 8, 1)]
    assert not catalogue.provider_info["live_stations"]
    assert not catalogue.provider_info["live_products"]
    assert not catalogue.provider_info["live_station_products"]
