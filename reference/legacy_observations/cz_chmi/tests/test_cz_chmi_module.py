from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.cz_chmi import module as cz_chmi_module


def test_cz_chmi_in_providers_list() -> None:
    assert "cz_chmi" in rr.providers()


def test_cz_chmi_stations_offline() -> None:
    result = rr.provider("cz_chmi").stations()
    assert result.data.height == 831
    assert result.data["country"].unique().to_list() == ["Czech Republic"]


def test_cz_chmi_products_offline() -> None:
    result = rr.provider("cz_chmi").products()
    assert result.data.height == 5
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_daily_mean",
        "stage_daily_mean",
        "water_temperature_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
    }


def test_cz_chmi_station_products_offline() -> None:
    result = rr.provider("cz_chmi").station_products()
    assert result.data.height == 831 * 5


def test_cz_chmi_info() -> None:
    info = rr.provider("cz_chmi").info()
    assert info.provider_id == "cz_chmi"
    assert "CHMI" in info.name or "Czech" in info.name


def test_cz_chmi_row_annotation_schema_declared() -> None:
    schemas = rr.provider("cz_chmi").row_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "ts_con_id" in ids
    assert "native_unit" in ids
    assert "converted_unit" in ids
    assert "raw_value" in ids


def test_cz_chmi_series_annotation_schema_declared() -> None:
    schemas = rr.provider("cz_chmi").series_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "resolved_timezone" in ids
    assert "timezone_source" in ids
    assert "returned_time_range_start" in ids
    assert "returned_time_range_end" in ids


def test_cz_chmi_module_catalogue_path_exists() -> None:
    assert cz_chmi_module._CATALOGUE_PATH.exists()
    assert (cz_chmi_module._CATALOGUE_PATH / "provider.json").exists()
    assert (cz_chmi_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (cz_chmi_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (cz_chmi_module._CATALOGUE_PATH / "station_products.parquet").exists()
