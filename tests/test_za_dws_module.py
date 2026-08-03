from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.providers.za_dws import module as za_dws_module


def test_za_dws_in_providers_list() -> None:
    assert "za_dws" in rr.providers()


def test_za_dws_stations_offline() -> None:
    result = rr.provider("za_dws").stations()
    assert result.data.height > 0
    assert result.data["crs"].unique().to_list() == ["unknown"]


def test_za_dws_station_count_reasonable() -> None:
    result = rr.provider("za_dws").stations()
    assert result.data.height == 2905


def test_za_dws_products_offline() -> None:
    result = rr.provider("za_dws").products()
    assert result.data.height == 3
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
    assert result.data.height == 8715
    assert result.data.height == stations.data.height * products.data.height


def test_za_dws_info() -> None:
    info = rr.provider("za_dws").info()
    assert info.provider_id == "za_dws"
    assert "South Africa" in info.name or "DWS" in info.name or "Water" in info.name


@pytest.mark.parametrize("method", ["row_annotation_schema", "series_annotation_schema"])
def test_za_dws_observation_schemas_unavailable(method: str) -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider za_dws has no observation module registered",
    ):
        getattr(rr.provider("za_dws"), method)()


def test_za_dws_observations_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider za_dws has no observation module registered",
    ):
        rr.provider("za_dws").observations(
            stations=["X3H001"],
            products=["discharge_daily_mean"],
            start="2020-01-01",
            end="2020-01-02",
        )


def test_za_dws_module_has_no_observations() -> None:
    assert not hasattr(za_dws_module, "observations")


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
    assert result.data["latitude"].null_count() == 0
    assert result.data["longitude"].null_count() == 0
    lats = result.data["latitude"].to_list()
    lons = result.data["longitude"].to_list()
    assert all(-35.0 <= lat <= -22.0 for lat in lats), "All latitudes should be in South Africa range"
    assert all(16.0 <= lon <= 34.0 for lon in lons), "All longitudes should be in South Africa range"
