from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.providers.za_dws import module as za_dws_module


def test_za_dws_in_providers_list() -> None:
    assert "za_dws" in rr.providers()


def test_za_dws_stations_offline() -> None:
    result = rr.provider("za_dws").stations()
    assert result.data.height > 0
    assert result.data["country"].unique().to_list() == ["South Africa"]


def test_za_dws_station_count_reasonable() -> None:
    result = rr.provider("za_dws").stations()
    assert result.data.height >= 2000


def test_za_dws_products_offline() -> None:
    result = rr.provider("za_dws").products()
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
    }


def test_za_dws_station_products_offline() -> None:
    stations = rr.provider("za_dws").stations()
    products = rr.provider("za_dws").products()
    result = rr.provider("za_dws").station_products()
    assert result.data.height == stations.data.height * products.data.height


def test_za_dws_info() -> None:
    info = rr.provider("za_dws").info()
    assert info.provider_id == "za_dws"
    assert "South Africa" in info.name or "DWS" in info.name or "Water" in info.name


def test_za_dws_row_annotation_schema_declared() -> None:
    schemas = rr.provider("za_dws").row_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "native_unit" in ids
    assert "converted_unit" in ids


def test_za_dws_series_annotation_schema_declared() -> None:
    schemas = rr.provider("za_dws").series_annotation_schema()
    ids = {s.annotation_id for s in schemas}
    assert "resolved_timezone" in ids
    assert "timezone_source" in ids
    assert "source_timezone" in ids
    assert "returned_time_range_start" in ids
    assert "returned_time_range_end" in ids
    assert "provider_endpoint" in ids


def test_za_dws_module_catalogue_path_exists() -> None:
    assert za_dws_module._CATALOGUE_PATH.exists()
    assert (za_dws_module._CATALOGUE_PATH / "provider.json").exists()
    assert (za_dws_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (za_dws_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (za_dws_module._CATALOGUE_PATH / "station_products.parquet").exists()


def test_za_dws_station_x3h001_present() -> None:
    result = rr.provider("za_dws").stations()
    row = result.data.filter(result.data["station_id"] == "X3H001")
    assert row.height == 1
    lat = row["latitude"][0]
    lon = row["longitude"][0]
    assert lat is not None and lat < 0  # Southern Hemisphere
    assert lon is not None and lon > 0  # Eastern Hemisphere


def test_za_dws_station_coordinates_in_south_africa_range() -> None:
    result = rr.provider("za_dws").stations()
    lats = result.data["latitude"].drop_nulls().to_list()
    lons = result.data["longitude"].drop_nulls().to_list()
    assert all(-35.0 <= lat <= -22.0 for lat in lats), "All latitudes should be in South Africa range"
    assert all(16.0 <= lon <= 34.0 for lon in lons), "All longitudes should be in South Africa range"
