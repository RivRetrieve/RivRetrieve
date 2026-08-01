from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import (
    PRODUCT_DEFINITIONS,
    generate_catalogue,
    generate_catalogue_from_fixture,
)

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_sites.json")


def test_generate_catalogue_from_fixture_station_count() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    assert catalogue.stations.height == 5  # fixture has 5 representative stations


def test_generate_catalogue_station_07374000() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    row = catalogue.stations.filter(catalogue.stations["station_id"] == "07374000")
    assert row.height == 1
    assert abs(row["latitude"][0] - 30.44) < 0.1
    assert abs(row["longitude"][0] - (-91.19)) < 0.1
    assert row["crs"][0] == "unknown"


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
    assert catalogue.station_products.height == catalogue.stations.height * len(PRODUCT_DEFINITIONS)


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


def test_live_mode_rejects_too_few_stations() -> None:
    """Guard: --live must produce ≥10 000 stations or raise, preventing a test fixture from being committed as the packaged catalogue."""

    tiny_fixture = [
        {"site_no": "07374000", "station_nm": "Mississippi R.", "dec_lat_va": "30.4", "dec_long_va": "-91.2"}
    ]
    with pytest.raises(FatalContractError, match="live catalogue has only"):
        generate_catalogue(tiny_fixture, generator_input="live")
