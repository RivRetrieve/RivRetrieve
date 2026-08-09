from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.providers.usgs_nwis import module as usgs_nwis_module
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.providers.usgs_nwis.fetch import fetch
from rivretrieve._internal.providers.usgs_nwis.parse import parse


def test_usgs_nwis_in_providers_list() -> None:
    assert "usgs_nwis" in rr.providers()


def test_usgs_nwis_exposes_only_the_engine_stage_contract() -> None:
    assert usgs_nwis_module.config is config()
    assert usgs_nwis_module.fetch is fetch
    assert usgs_nwis_module.parse is parse
    assert usgs_nwis_module.observation_source == "live"
    assert not hasattr(usgs_nwis_module, "observations")
    assert isinstance(usgs_nwis_module, ProviderModule)


def test_usgs_nwis_stations_offline() -> None:
    result = usgs_nwis_module.stations()
    assert result.data.height == 26_258
    assert result.data["crs"].unique().to_list() == ["EPSG:4269"]


def test_usgs_nwis_products_offline() -> None:
    result = usgs_nwis_module.products()
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
    result = usgs_nwis_module.station_products()
    assert result.data.height == 157_548
    assert "unknown" not in set(result.data["availability"].cast(str))


def test_usgs_nwis_info() -> None:
    info = usgs_nwis_module.info()
    assert info.provider_id == "usgs_nwis"
    assert "USGS" in info.name or "Geological Survey" in info.name
    assert info.catalogue_version == "2026-08-02"


def test_usgs_nwis_module_catalogue_path_exists() -> None:
    assert usgs_nwis_module._CATALOGUE_PATH.exists()
    assert (usgs_nwis_module._CATALOGUE_PATH / "provider.json").exists()
    assert (usgs_nwis_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (usgs_nwis_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (usgs_nwis_module._CATALOGUE_PATH / "station_products.parquet").exists()


def test_usgs_nwis_station_fields() -> None:
    result = usgs_nwis_module.stations()
    df = result.data
    assert "station_id" in df.columns
    assert "latitude" in df.columns
    assert "longitude" in df.columns
    assert "crs" in df.columns
    row = df.filter(df["station_id"] == "07374000")
    assert row.height == 1
    assert row["crs"][0] == "EPSG:4269"
    assert abs(row["latitude"][0] - 30.44) < 0.1
