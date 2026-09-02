from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.registry import _registry
from tests._catalogue import catalogue_path, catalogue_reader, provider_info


def test_ba_fhmzbih_in_providers_list() -> None:
    assert "ba_fhmzbih" in rr.providers()


def test_ba_fhmzbih_stations_offline() -> None:
    result = catalogue_reader("ba_fhmzbih").read_stations()
    assert result.data.height == 1
    assert result.data["crs"].unique().to_list() == ["unknown"]


def test_ba_fhmzbih_products_offline() -> None:
    result = catalogue_reader("ba_fhmzbih").read_products()
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
    stations = catalogue_reader("ba_fhmzbih").read_stations()
    products = catalogue_reader("ba_fhmzbih").read_products()
    result = catalogue_reader("ba_fhmzbih").read_station_products()
    assert result.data.is_empty()
    assert stations.data.height == 1
    assert products.data.height == 3


def test_ba_fhmzbih_info() -> None:
    info = provider_info("ba_fhmzbih")
    assert info.provider_id == "ba_fhmzbih"
    assert "FHMZBiH" in info.name or "Bosnia" in info.name
    assert info.catalogue_version == "2026-08-02"


def test_ba_fhmzbih_observations_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider ba_fhmzbih has no observations registered",
    ):
        rr.providers()
        _registry.get("ba_fhmzbih").observations(
            stations=["4510"],
            products=["discharge_instantaneous"],
            start="2020-01-01",
            end="2020-01-02",
        )


def test_ba_fhmzbih_catalogue_has_no_observations() -> None:
    rr.providers()
    assert _registry.get("ba_fhmzbih")._stages is None


def test_ba_fhmzbih_catalogue_catalogue_path_exists() -> None:
    assert catalogue_path("ba_fhmzbih").exists()
    assert (catalogue_path("ba_fhmzbih") / "provider.json").exists()
    assert (catalogue_path("ba_fhmzbih") / "stations.parquet").exists()
    assert (catalogue_path("ba_fhmzbih") / "products.parquet").exists()
    assert (catalogue_path("ba_fhmzbih") / "station_products.parquet").exists()


def test_ba_fhmzbih_station_fields() -> None:
    result = catalogue_reader("ba_fhmzbih").read_stations()
    row = result.data.filter(result.data["station_id"] == "4024")
    assert row.height == 1
    assert row["latitude"][0] == 43.96558356471353
    assert row["longitude"][0] == 18.256887847750523
    assert row["crs"][0] == "unknown"
