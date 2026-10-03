from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.registry import _registry
from tests._catalogue import catalogue_reader, provider_info


def test_za_dws_in_providers_list() -> None:
    assert "za_dws" in rr.providers().get_column("provider_id").to_list()


def test_za_dws_stations_offline() -> None:
    result = catalogue_reader("za_dws").read_stations()
    assert result.data.height > 0
    assert result.data["crs"].unique().to_list() == ["unknown"]


def test_za_dws_station_count_reasonable() -> None:
    result = catalogue_reader("za_dws").read_stations()
    assert result.data.height == 2905


def test_za_dws_products_offline() -> None:
    result = catalogue_reader("za_dws").read_products()
    assert result.data.height == 3
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
    }


def test_za_dws_station_products_offline() -> None:
    stations = catalogue_reader("za_dws").read_stations()
    products = catalogue_reader("za_dws").read_products()
    result = catalogue_reader("za_dws").read_station_products()
    assert result.data.height == 8715
    assert result.data.height == stations.data.height * products.data.height


def test_za_dws_info() -> None:
    info = provider_info("za_dws")
    assert info.provider_id == "za_dws"
    assert "South Africa" in info.name or "DWS" in info.name or "Water" in info.name


def test_za_dws_observations_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider za_dws has no observations registered",
    ):
        rr.providers()
        _registry.get("za_dws").observations(
            stations=["X3H001"],
            products=["discharge_daily_mean"],
            start="2020-01-01",
            end="2020-01-02",
        )


def test_za_dws_station_x3h001_present() -> None:
    result = catalogue_reader("za_dws").read_stations()
    row = result.data.filter(result.data["station_id"] == "X3H001")
    assert row.height == 1
    lat = row["latitude"][0]
    lon = row["longitude"][0]
    assert lat is not None and lat < 0  # Southern Hemisphere
    assert lon is not None and lon > 0  # Eastern Hemisphere


def test_za_dws_station_coordinates_in_south_africa_range() -> None:
    result = catalogue_reader("za_dws").read_stations()
    assert result.data["latitude"].null_count() == 0
    assert result.data["longitude"].null_count() == 0
    lats = result.data["latitude"].to_list()
    lons = result.data["longitude"].to_list()
    assert all(-35.0 <= lat <= -22.0 for lat in lats), "All latitudes should be in South Africa range"
    assert all(16.0 <= lon <= 34.0 for lon in lons), "All longitudes should be in South Africa range"
