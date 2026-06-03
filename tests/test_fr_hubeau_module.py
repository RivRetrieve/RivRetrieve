from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.fr_hubeau import module as fr_hubeau_module


def test_fr_hubeau_in_providers_list() -> None:
    assert "fr_hubeau" in rr.providers()


def test_fr_hubeau_stations_offline() -> None:
    result = rr.provider("fr_hubeau").stations()
    # 6420 hydrometric + 869 temperature stations (2026-06-03 live catalogue).
    assert result.data.height == 7289
    assert result.data["country"].unique().to_list() == ["France"]


def test_fr_hubeau_products_offline() -> None:
    result = rr.provider("fr_hubeau").products()
    assert result.data.height == 6
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_instantaneous",
        "discharge_daily_mean",
        "discharge_daily_max",
        "stage_instantaneous",
        "stage_daily_max",
        "water_temperature_instantaneous",
    }


def test_fr_hubeau_station_products_offline() -> None:
    result = rr.provider("fr_hubeau").station_products()
    # 6420 hydro × 5 products + 869 temp × 1 product = 32969
    assert result.data.height == 32969


def test_fr_hubeau_info() -> None:
    info = rr.provider("fr_hubeau").info()
    assert info.provider_id == "fr_hubeau"
    assert "Hubeau" in info.name or "France" in info.name or "SCHAPI" in info.name


def test_fr_hubeau_row_annotation_schema_declared() -> None:
    schemas = rr.provider("fr_hubeau").row_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "grandeur_code" in ids
    assert "native_unit" in ids
    assert "converted_unit" in ids
    assert "raw_value" in ids


def test_fr_hubeau_series_annotation_schema_declared() -> None:
    schemas = rr.provider("fr_hubeau").series_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "resolved_timezone" in ids
    assert "date_only_timestamp_flag" in ids
    assert "timezone_source" in ids
    assert "returned_time_range_start" in ids
    assert "returned_time_range_end" in ids


def test_fr_hubeau_module_catalogue_path_exists() -> None:
    assert fr_hubeau_module._CATALOGUE_PATH.exists()
    assert (fr_hubeau_module._CATALOGUE_PATH / "provider.json").exists()
    assert (fr_hubeau_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (fr_hubeau_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (fr_hubeau_module._CATALOGUE_PATH / "station_products.parquet").exists()


def test_fr_hubeau_station_types_in_metadata() -> None:
    import json

    result = rr.provider("fr_hubeau").stations()
    types = {json.loads(m).get("station_type") for m in result.data["metadata"].to_list()}
    assert types == {"hydrometric", "temperature"}
