"""Tests for ca_eccc catalogue generation from fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from rivretrieve._internal.providers.ca_eccc.generate_catalogue import (
    GeneratedCaEcccCatalogue,
    generate_catalogue_from_fixture,
)

FIXTURE = Path(__file__).parent / "test_data" / "ca_eccc_metadata.json"


@pytest.fixture(scope="module")
def catalogue() -> GeneratedCaEcccCatalogue:
    return generate_catalogue_from_fixture(FIXTURE, catalogue_date=None)


def test_catalogue_station_count(catalogue: GeneratedCaEcccCatalogue) -> None:
    # NOLONLAT row has null coords → filtered out. 3 valid stations remain.
    assert len(catalogue.stations) == 3


def test_catalogue_station_ids(catalogue: GeneratedCaEcccCatalogue) -> None:
    ids = set(catalogue.stations["station_id"].to_list())
    assert "02GA010" in ids
    assert "05BB001" in ids
    assert "08MF005" in ids
    assert "NOLONLAT" not in ids


def test_catalogue_station_grand_river_name(catalogue: GeneratedCaEcccCatalogue) -> None:
    import polars as pl

    row = catalogue.stations.filter(pl.col("station_id") == "02GA010")
    assert not row.is_empty()
    assert "GRAND RIVER" in row["name"][0]


def test_catalogue_station_grand_river_coordinates(catalogue: GeneratedCaEcccCatalogue) -> None:
    import polars as pl

    row = catalogue.stations.filter(pl.col("station_id") == "02GA010")
    assert abs(row["latitude"][0] - 43.35) < 0.01
    assert abs(row["longitude"][0] - (-80.32)) < 0.01


def test_catalogue_drainage_area_present(catalogue: GeneratedCaEcccCatalogue) -> None:
    import polars as pl

    row = catalogue.stations.filter(pl.col("station_id") == "02GA010")
    assert row["drainage_area_km2"][0] == pytest.approx(4920.0)


def test_catalogue_elevation_always_null(catalogue: GeneratedCaEcccCatalogue) -> None:
    """ECCC OGC does not provide elevation."""
    assert catalogue.stations["elevation_m"].is_null().all()


def test_catalogue_country_canada(catalogue: GeneratedCaEcccCatalogue) -> None:
    assert all(c == "Canada" for c in catalogue.stations["country"].to_list())


def test_catalogue_products_count(catalogue: GeneratedCaEcccCatalogue) -> None:
    assert len(catalogue.products) == 2


def test_catalogue_product_ids(catalogue: GeneratedCaEcccCatalogue) -> None:
    ids = set(catalogue.products["product_id"].to_list())
    assert ids == {"discharge_daily_mean", "stage_daily_mean"}


def test_catalogue_product_units(catalogue: GeneratedCaEcccCatalogue) -> None:
    import polars as pl

    discharge_row = catalogue.products.filter(pl.col("product_id") == "discharge_daily_mean")
    assert discharge_row["unit"][0] == "m3/s"

    stage_row = catalogue.products.filter(pl.col("product_id") == "stage_daily_mean")
    assert stage_row["unit"][0] == "m"


def test_catalogue_station_products_count(catalogue: GeneratedCaEcccCatalogue) -> None:
    # 3 stations × 2 products = 6
    assert len(catalogue.station_products) == 6


def test_catalogue_station_products_all_unknown(catalogue: GeneratedCaEcccCatalogue) -> None:
    availabilities = set(catalogue.station_products["availability"].cast(str).to_list())
    assert availabilities == {"unknown"}


def test_catalogue_provider_id(catalogue: GeneratedCaEcccCatalogue) -> None:
    assert catalogue.provider_info["provider_id"] == "ca_eccc"


def test_catalogue_provider_name(catalogue: GeneratedCaEcccCatalogue) -> None:
    assert "Canada" in str(catalogue.provider_info["name"])


def test_catalogue_live_flags_false(catalogue: GeneratedCaEcccCatalogue) -> None:
    assert catalogue.provider_info["live_stations"] is False
    assert catalogue.provider_info["live_products"] is False
    assert catalogue.provider_info["live_station_products"] is False


def test_catalogue_metadata_has_ogc_field(catalogue: GeneratedCaEcccCatalogue) -> None:
    import json

    import polars as pl

    discharge_row = catalogue.products.filter(pl.col("product_id") == "discharge_daily_mean")
    meta = json.loads(discharge_row["metadata"][0])
    assert meta["ogc_field"] == "DISCHARGE"

    stage_row = catalogue.products.filter(pl.col("product_id") == "stage_daily_mean")
    meta2 = json.loads(stage_row["metadata"][0])
    assert meta2["ogc_field"] == "LEVEL"
