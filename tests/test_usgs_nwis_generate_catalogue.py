from __future__ import annotations

from datetime import date
from pathlib import Path

from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import (
    PRODUCT_DEFINITIONS,
    generate_catalogue_from_fixture,
)

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_sites.json")


def test_generate_catalogue_from_fixture_station_count() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    assert catalogue.stations.height == 5


def test_generate_catalogue_station_07374000() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    row = catalogue.stations.filter(catalogue.stations["station_id"] == "07374000")
    assert row.height == 1
    assert "Mississippi" in row["name"][0]
    assert row["country"][0] == "United States"
    assert abs(row["latitude"][0] - 30.44) < 0.1
    assert abs(row["longitude"][0] - (-91.19)) < 0.1


def test_generate_catalogue_elevation_converted() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    row = catalogue.stations.filter(catalogue.stations["station_id"] == "07374000")
    elev = row["elevation_m"][0]
    assert elev is not None
    assert abs(elev - 10.20 * 0.3048) < 0.01


def test_generate_catalogue_drainage_area_converted() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    row = catalogue.stations.filter(catalogue.stations["station_id"] == "07374000")
    area = row["drainage_area_km2"][0]
    assert area is not None
    assert area > 1_000_000


def test_generate_catalogue_product_count() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    assert catalogue.products.height == len(PRODUCT_DEFINITIONS)


def test_generate_catalogue_canonical_product_ids() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    product_ids = set(catalogue.products["product_id"].to_list())
    assert "discharge_daily_mean" in product_ids
    assert "discharge_instantaneous" in product_ids
    assert "stage_daily_mean" in product_ids
    assert "stage_daily_max" in product_ids
    assert "stage_daily_min" in product_ids
    assert "stage_instantaneous" in product_ids


def test_generate_catalogue_station_products_count() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    assert catalogue.station_products.height == 5 * len(PRODUCT_DEFINITIONS)


def test_generate_catalogue_station_products_availability_unknown() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    avail_vals = catalogue.station_products["availability"].unique().to_list()
    assert avail_vals == ["unknown"]


def test_generate_catalogue_provider_info_fields() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    pi = catalogue.provider_info
    assert pi["provider_id"] == "usgs_nwis"
    assert pi["catalogue_version"] == "2026-06-01"
    assert pi["live_stations"] is False
    assert pi["live_products"] is False
    assert pi["live_station_products"] is False
