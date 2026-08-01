from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.ba_fhmzbih import module as ba_fhmzbih_module


def test_ba_fhmzbih_in_providers_list() -> None:
    assert "ba_fhmzbih" in rr.providers()


def test_ba_fhmzbih_stations_offline() -> None:
    result = rr.provider("ba_fhmzbih").stations()
    assert result.data.height > 0
    assert result.data["country"].unique().to_list() == ["Bosnia and Herzegovina"]


def test_ba_fhmzbih_products_offline() -> None:
    result = rr.provider("ba_fhmzbih").products()
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_instantaneous",
        "discharge_daily_mean",
        "stage_instantaneous",
        "stage_daily_mean",
        "water_temperature_instantaneous",
        "water_temperature_daily_mean",
    }


def test_ba_fhmzbih_station_products_offline() -> None:
    stations = rr.provider("ba_fhmzbih").stations()
    products = rr.provider("ba_fhmzbih").products()
    result = rr.provider("ba_fhmzbih").station_products()
    assert result.data.height == stations.data.height * products.data.height


def test_ba_fhmzbih_info() -> None:
    info = rr.provider("ba_fhmzbih").info()
    assert info.provider_id == "ba_fhmzbih"
    assert "FHMZBiH" in info.name or "Bosnia" in info.name


def test_ba_fhmzbih_row_annotation_schema_declared() -> None:
    schemas = rr.provider("ba_fhmzbih").row_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "native_unit" in ids
    assert "converted_unit" in ids
    assert "raw_value" in ids


def test_ba_fhmzbih_series_annotation_schema_declared() -> None:
    schemas = rr.provider("ba_fhmzbih").series_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "resolved_timezone" in ids
    assert "timezone_source" in ids
    assert "source_timezone" in ids
    assert "returned_time_range_start" in ids
    assert "returned_time_range_end" in ids
    assert "aggregation" in ids
    assert "station_group" in ids


def test_ba_fhmzbih_module_catalogue_path_exists() -> None:
    assert ba_fhmzbih_module._CATALOGUE_PATH.exists()
    assert (ba_fhmzbih_module._CATALOGUE_PATH / "provider.json").exists()
    assert (ba_fhmzbih_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (ba_fhmzbih_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (ba_fhmzbih_module._CATALOGUE_PATH / "station_products.parquet").exists()


def test_ba_fhmzbih_station_fields() -> None:
    result = rr.provider("ba_fhmzbih").stations()
    row = result.data.filter(result.data["station_id"] == "4510")
    assert row.height == 1
    assert row["name"][0] == "HS Kaloševići"
