from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.providers.ba_fhmzbih import module as ba_fhmzbih_module


def test_ba_fhmzbih_in_providers_list() -> None:
    assert "ba_fhmzbih" in rr.providers()


def test_ba_fhmzbih_stations_offline() -> None:
    result = rr.provider("ba_fhmzbih").stations()
    assert result.data.height == 60
    assert result.data["crs"].unique().to_list() == ["unknown"]


def test_ba_fhmzbih_products_offline() -> None:
    result = rr.provider("ba_fhmzbih").products()
    assert result.data.height == 3
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    }
    assert product_ids.isdisjoint(
        {
            "discharge_daily_mean",
            "stage_daily_mean",
            "water_temperature_daily_mean",
        }
    )


def test_ba_fhmzbih_station_products_offline() -> None:
    stations = rr.provider("ba_fhmzbih").stations()
    products = rr.provider("ba_fhmzbih").products()
    result = rr.provider("ba_fhmzbih").station_products()
    assert result.data.height == 180 == stations.data.height * products.data.height


def test_ba_fhmzbih_info() -> None:
    info = rr.provider("ba_fhmzbih").info()
    assert info.provider_id == "ba_fhmzbih"
    assert "FHMZBiH" in info.name or "Bosnia" in info.name
    assert info.catalogue_version == "2026-08-02"


@pytest.mark.parametrize("method", ["row_annotation_schema", "series_annotation_schema"])
def test_ba_fhmzbih_observation_schemas_unavailable(method: str) -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider ba_fhmzbih has no observation module registered",
    ):
        getattr(rr.provider("ba_fhmzbih"), method)()


def test_ba_fhmzbih_observations_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider ba_fhmzbih has no observation module registered",
    ):
        rr.provider("ba_fhmzbih").observations(
            stations=["4510"],
            products=["discharge_instantaneous"],
            start="2020-01-01",
            end="2020-01-02",
        )


def test_ba_fhmzbih_module_has_no_observations() -> None:
    assert not hasattr(ba_fhmzbih_module, "observations")


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
    assert row["latitude"][0] == 44.64680728070949
    assert row["longitude"][0] == 17.90406242892678
    assert row["crs"][0] == "unknown"
