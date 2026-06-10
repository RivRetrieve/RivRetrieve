from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.br_ana import module as br_ana_module


def test_br_ana_in_providers_list() -> None:
    assert "br_ana" in rr.providers()


def test_br_ana_stations_offline() -> None:
    result = rr.provider("br_ana").stations()
    assert result.data.height == 2
    assert result.data["country"].unique().to_list() == ["Brazil"]


def test_br_ana_products_offline() -> None:
    result = rr.provider("br_ana").products()
    assert result.data.height == 5
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_daily_mean",
        "stage_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    }


def test_br_ana_station_products_offline() -> None:
    result = rr.provider("br_ana").station_products()
    # 2 stations × 5 products = 10
    assert result.data.height == 10


def test_br_ana_info() -> None:
    info = rr.provider("br_ana").info()
    assert info.provider_id == "br_ana"
    assert "ANA" in info.name or "Brazil" in info.name


def test_br_ana_row_annotation_schema_declared() -> None:
    schemas = rr.provider("br_ana").row_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "native_unit" in ids
    assert "converted_unit" in ids
    assert "raw_value" in ids


def test_br_ana_series_annotation_schema_declared() -> None:
    schemas = rr.provider("br_ana").series_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "resolved_timezone" in ids
    assert "date_only_timestamp_flag" in ids
    assert "timezone_source" in ids
    assert "returned_time_range_start" in ids
    assert "returned_time_range_end" in ids


def test_br_ana_module_catalogue_path_exists() -> None:
    assert br_ana_module._CATALOGUE_PATH.exists()
    assert (br_ana_module._CATALOGUE_PATH / "provider.json").exists()
    assert (br_ana_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (br_ana_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (br_ana_module._CATALOGUE_PATH / "station_products.parquet").exists()


def test_br_ana_station_elevation_and_drainage_area() -> None:
    result = rr.provider("br_ana").stations()
    row = result.data.filter(result.data["station_id"] == "12345000")
    assert row.height == 1
    assert row["elevation_m"][0] == 50.0
    assert row["drainage_area_km2"][0] == 146080.0


def test_br_ana_station_no_coord_filtered() -> None:
    result = rr.provider("br_ana").stations()
    station_ids = set(result.data["station_id"].to_list())
    assert "99999999" not in station_ids
