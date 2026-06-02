from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.th_thaiwater import module as th_thaiwater_module


def test_th_thaiwater_in_providers_list() -> None:
    assert "th_thaiwater" in rr.providers()


def test_th_thaiwater_stations_offline() -> None:
    result = rr.provider("th_thaiwater").stations()
    assert result.data.height == 754
    assert result.data["country"].unique().to_list() == ["Thailand"]


def test_th_thaiwater_products_offline() -> None:
    result = rr.provider("th_thaiwater").products()
    assert result.data.height == 4
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "stage_daily_mean",
        "stage_instantaneous",
        "discharge_daily_mean",
        "discharge_instantaneous",
    }


def test_th_thaiwater_station_products_offline() -> None:
    result = rr.provider("th_thaiwater").station_products()
    assert result.data.height == 754 * 4


def test_th_thaiwater_info() -> None:
    info = rr.provider("th_thaiwater").info()
    assert info.provider_id == "th_thaiwater"
    assert "ThaiWater" in info.name or "HII" in info.name or "Thailand" in info.name


def test_th_thaiwater_row_annotation_schema_declared() -> None:
    schemas = rr.provider("th_thaiwater").row_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "native_field" in ids
    assert "native_unit" in ids
    assert "converted_unit" in ids


def test_th_thaiwater_series_annotation_schema_declared() -> None:
    schemas = rr.provider("th_thaiwater").series_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "resolved_timezone" in ids
    assert "timezone_source" in ids
    assert "local_timezone" in ids
    assert "returned_time_range_start" in ids
    assert "returned_time_range_end" in ids


def test_th_thaiwater_module_catalogue_path_exists() -> None:
    assert th_thaiwater_module._CATALOGUE_PATH.exists()
    assert (th_thaiwater_module._CATALOGUE_PATH / "provider.json").exists()
    assert (th_thaiwater_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (th_thaiwater_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (th_thaiwater_module._CATALOGUE_PATH / "station_products.parquet").exists()
