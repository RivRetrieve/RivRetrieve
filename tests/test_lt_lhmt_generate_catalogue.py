from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from rivretrieve._internal.providers.lt_lhmt import generate_catalogue

FIXTURE_PATH = Path("tests/test_data/lithuania_metadata_stations.json")
CATALOGUE_DATE = date(2026, 5, 31)


def test_lt_lhmt_generator_uses_committed_fixture_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_live_json(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_live_json)

    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.stations.height == 97


def test_lt_lhmt_generator_station_count_matches_fixture() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    assert catalogue.stations.height == 97


def test_lt_lhmt_generator_products_are_two() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    assert catalogue.products.height == 2
    product_ids = set(catalogue.products["product_id"].to_list())
    assert product_ids == {"discharge_daily_mean", "stage_daily_mean"}


def test_lt_lhmt_generator_station_products_count() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    assert catalogue.station_products.height == 97 * 2


def test_lt_lhmt_generator_station_products_availability_unknown() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    availability_values = set(catalogue.station_products["availability"].cast(str).to_list())
    assert availability_values == {"unknown"}


def test_lt_lhmt_generator_first_station_sorted() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    station_ids = catalogue.stations["station_id"].to_list()
    assert station_ids == sorted(station_ids)


def test_lt_lhmt_generator_station_has_required_common_fields() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    cols = set(catalogue.stations.columns)
    for col in {"provider_id", "station_id", "name", "latitude", "longitude", "country"}:
        assert col in cols


def test_lt_lhmt_generator_elevation_and_area_are_null() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    assert catalogue.stations["elevation_m"].is_null().all()
    assert catalogue.stations["drainage_area_km2"].is_null().all()


def test_lt_lhmt_generator_provider_info_fields() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    info = catalogue.provider_info
    assert info["provider_id"] == "lt_lhmt"
    assert info["catalogue_version"] == "2026-05-31"
    assert info["live_stations"] is False
    assert info["live_products"] is False
    assert info["live_station_products"] is False
