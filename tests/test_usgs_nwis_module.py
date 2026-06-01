from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.usgs_nwis import module as usgs_nwis_module


def test_usgs_nwis_in_providers_list() -> None:
    assert "usgs_nwis" in rr.providers()


def test_usgs_nwis_stations_offline() -> None:
    result = rr.provider("usgs_nwis").stations()
    assert result.data.height > 1000
    assert result.data["country"].unique().to_list() == ["United States"]


def test_usgs_nwis_products_offline() -> None:
    result = rr.provider("usgs_nwis").products()
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
    result = rr.provider("usgs_nwis").station_products()
    n_stations = rr.provider("usgs_nwis").stations().data.height
    assert result.data.height == n_stations * 6


def test_usgs_nwis_info() -> None:
    info = rr.provider("usgs_nwis").info()
    assert info.provider_id == "usgs_nwis"
    assert "USGS" in info.name or "Geological Survey" in info.name


def test_usgs_nwis_row_annotation_schema_declared() -> None:
    schemas = rr.provider("usgs_nwis").row_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "native_field" in ids
    assert "native_unit" in ids
    assert "converted_unit" in ids
    assert "raw_value" in ids
    assert "qualifier" in ids


def test_usgs_nwis_series_annotation_schema_declared() -> None:
    schemas = rr.provider("usgs_nwis").series_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "resolved_timezone" in ids
    assert "timezone_source" in ids
    assert "returned_time_range_start" in ids
    assert "returned_time_range_end" in ids
    assert "endpoint_type" in ids


def test_usgs_nwis_module_catalogue_path_exists() -> None:
    assert usgs_nwis_module._CATALOGUE_PATH.exists()
    assert (usgs_nwis_module._CATALOGUE_PATH / "provider.json").exists()
    assert (usgs_nwis_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (usgs_nwis_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (usgs_nwis_module._CATALOGUE_PATH / "station_products.parquet").exists()


def test_usgs_nwis_station_fields() -> None:
    result = rr.provider("usgs_nwis").stations()
    df = result.data
    assert "station_id" in df.columns
    assert "latitude" in df.columns
    assert "longitude" in df.columns
    assert "country" in df.columns
    row = df.filter(df["station_id"] == "07374000")
    assert row.height == 1
    assert abs(row["latitude"][0] - 30.44) < 0.1
