from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.lt_lhmt import module as lt_lhmt_module


def test_lt_lhmt_in_providers_list() -> None:
    assert "lt_lhmt" in rr.providers()


def test_lt_lhmt_stations_offline() -> None:
    result = rr.provider("lt_lhmt").stations()
    assert result.data.height == 97
    assert result.data["country"].unique().to_list() == ["Lithuania"]


def test_lt_lhmt_products_offline() -> None:
    result = rr.provider("lt_lhmt").products()
    assert result.data.height == 2
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {"discharge_daily_mean", "stage_daily_mean"}


def test_lt_lhmt_station_products_offline() -> None:
    result = rr.provider("lt_lhmt").station_products()
    assert result.data.height == 97 * 2


def test_lt_lhmt_info() -> None:
    info = rr.provider("lt_lhmt").info()
    assert info.provider_id == "lt_lhmt"
    assert "Lithuania" in info.name or "LHMT" in info.name


def test_lt_lhmt_row_annotation_schema_declared() -> None:
    schemas = rr.provider("lt_lhmt").row_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "native_field" in ids
    assert "native_unit" in ids
    assert "converted_unit" in ids
    assert "raw_value" in ids


def test_lt_lhmt_series_annotation_schema_declared() -> None:
    schemas = rr.provider("lt_lhmt").series_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "resolved_timezone" in ids
    assert "date_only_timestamp_flag" in ids
    assert "returned_time_range_start" in ids
    assert "returned_time_range_end" in ids


def test_lt_lhmt_module_catalogue_path_exists() -> None:
    assert lt_lhmt_module._CATALOGUE_PATH.exists()
    assert (lt_lhmt_module._CATALOGUE_PATH / "provider.json").exists()
    assert (lt_lhmt_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (lt_lhmt_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (lt_lhmt_module._CATALOGUE_PATH / "station_products.parquet").exists()
