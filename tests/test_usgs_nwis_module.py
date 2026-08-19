from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.usgs_nwis.config import config, window_declarations
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.providers.usgs_nwis.fetch import fetch
from rivretrieve._internal.providers.usgs_nwis.parse import parse
from tests._catalogue import catalogue_path, catalogue_reader, provider_info

assert isinstance(declaration.observations, LiveStages)
stages = declaration.observations.stages


def test_usgs_nwis_in_providers_list() -> None:
    assert "usgs_nwis" in rr.providers()


def test_usgs_nwis_declares_the_engine_stage_contract() -> None:
    assert stages.config is config()
    assert stages.window_declarations is window_declarations()
    assert stages.fetch is fetch
    assert stages.parse is parse
    assert stages.observation_source == "live"


def test_usgs_nwis_stations_offline() -> None:
    result = catalogue_reader("usgs_nwis").read_stations()
    assert result.data.height == 26_258
    assert result.data["crs"].unique().to_list() == ["EPSG:4269"]


def test_usgs_nwis_products_offline() -> None:
    result = catalogue_reader("usgs_nwis").read_products()
    assert result.data.height == 6
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_mean",
        "stage_daily_max",
        "stage_daily_min",
        "stage_instantaneous",
    }


def test_usgs_nwis_station_products_offline() -> None:
    result = catalogue_reader("usgs_nwis").read_station_products()
    assert result.data.height == 157_548
    assert "unknown" not in set(result.data["availability"].cast(str))


def test_usgs_nwis_info() -> None:
    info = provider_info("usgs_nwis")
    assert info.provider_id == "usgs_nwis"
    assert "USGS" in info.name or "Geological Survey" in info.name
    assert info.catalogue_version == "2026-08-02"


def test_usgs_nwis_declared_catalogue_path_exists() -> None:
    assert catalogue_path("usgs_nwis").exists()
    assert (catalogue_path("usgs_nwis") / "provider.json").exists()
    assert (catalogue_path("usgs_nwis") / "stations.parquet").exists()
    assert (catalogue_path("usgs_nwis") / "products.parquet").exists()
    assert (catalogue_path("usgs_nwis") / "station_products.parquet").exists()


def test_usgs_nwis_station_fields() -> None:
    result = catalogue_reader("usgs_nwis").read_stations()
    df = result.data
    assert "station_id" in df.columns
    assert "latitude" in df.columns
    assert "longitude" in df.columns
    assert "crs" in df.columns
    row = df.filter(df["station_id"] == "07374000")
    assert row.height == 1
    assert row["crs"][0] == "EPSG:4269"
    assert abs(row["latitude"][0] - 30.44) < 0.1
