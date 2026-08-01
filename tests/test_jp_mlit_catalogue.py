"""Tests for the jp_mlit catalogue generation and packaged catalogue."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.jp_mlit.generate_catalogue import (
    PROVIDER_ID,
    GeneratedJpMlitCatalogue,
    generate_catalogue_from_fixture,
    validate_generated_catalogue,
)

_FIXTURE_PATH = Path(__file__).parent / "test_data" / "jp_mlit_metadata.json"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _fixture_rows() -> list[dict[str, object]]:
    with _FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def catalogue() -> GeneratedJpMlitCatalogue:
    return generate_catalogue_from_fixture(_FIXTURE_PATH, catalogue_date=date(2026, 6, 3))


# ---------------------------------------------------------------------------
# Product catalogue
# ---------------------------------------------------------------------------


def test_products_count(catalogue: GeneratedJpMlitCatalogue) -> None:
    assert len(catalogue.products) == 4


def test_products_ids(catalogue: GeneratedJpMlitCatalogue) -> None:
    ids = set(catalogue.products["product_id"].to_list())
    assert ids == {"stage_daily_mean", "discharge_daily_mean", "stage_hourly_mean", "discharge_hourly_mean"}


def test_canonical_products_have_correct_units(catalogue: GeneratedJpMlitCatalogue) -> None:
    df = catalogue.products
    stage = df.filter(pl.col("product_id") == "stage_daily_mean")["unit"][0]
    discharge = df.filter(pl.col("product_id") == "discharge_daily_mean")["unit"][0]
    assert stage == "m"
    assert discharge == "m3/s"


def test_provider_specific_products_have_correct_frequency(catalogue: GeneratedJpMlitCatalogue) -> None:
    df = catalogue.products
    stage_h = df.filter(pl.col("product_id") == "stage_hourly_mean")
    assert stage_h["frequency"][0] == "hourly"
    assert stage_h["statistic"][0] == "mean"


def test_product_metadata_contains_kind(catalogue: GeneratedJpMlitCatalogue) -> None:
    df = catalogue.products
    for row in df.iter_rows(named=True):
        meta = json.loads(row["metadata"])
        assert "kind" in meta
        assert isinstance(meta["kind"], int)


# ---------------------------------------------------------------------------
# Station catalogue
# ---------------------------------------------------------------------------


def test_stations_count(catalogue: GeneratedJpMlitCatalogue) -> None:
    # Fixture has 3 stations.
    assert len(catalogue.stations) == 3


def test_stations_have_unknown_crs(catalogue: GeneratedJpMlitCatalogue) -> None:
    assert catalogue.stations["crs"].unique().to_list() == ["unknown"]


def test_stations_have_exact_schema(catalogue: GeneratedJpMlitCatalogue) -> None:
    assert catalogue.stations.columns == ["provider_id", "station_id", "latitude", "longitude", "crs"]


def test_known_station_present(catalogue: GeneratedJpMlitCatalogue) -> None:
    ids = catalogue.stations["station_id"].to_list()
    assert "301011281104010" in ids


def test_stations_have_valid_coordinates(catalogue: GeneratedJpMlitCatalogue) -> None:
    lats = catalogue.stations["latitude"].to_list()
    lons = catalogue.stations["longitude"].to_list()
    for lat, lon in zip(lats, lons, strict=True):
        assert lat is not None
        assert lon is not None
        assert 20.0 <= lat <= 50.0  # Japan latitude range
        assert 120.0 <= lon <= 155.0  # Japan longitude range


# ---------------------------------------------------------------------------
# Station-product catalogue
# ---------------------------------------------------------------------------


def test_station_products_count(catalogue: GeneratedJpMlitCatalogue) -> None:
    # 3 stations × 4 products = 12 station-product rows.
    assert len(catalogue.station_products) == 12


def test_station_products_availability_unknown(catalogue: GeneratedJpMlitCatalogue) -> None:
    avail = catalogue.station_products["availability"].cast(pl.Utf8).unique().to_list()
    assert avail == ["unknown"]


# ---------------------------------------------------------------------------
# Provider info
# ---------------------------------------------------------------------------


def test_provider_info_id(catalogue: GeneratedJpMlitCatalogue) -> None:
    assert catalogue.provider_info["provider_id"] == PROVIDER_ID


def test_provider_info_catalogue_version(catalogue: GeneratedJpMlitCatalogue) -> None:
    assert catalogue.provider_info["catalogue_version"] == "2026-06-03"


def test_provider_info_live_flags_false(catalogue: GeneratedJpMlitCatalogue) -> None:
    assert catalogue.provider_info["live_stations"] is False
    assert catalogue.provider_info["live_products"] is False
    assert catalogue.provider_info["live_station_products"] is False


# ---------------------------------------------------------------------------
# Catalogue validation round-trip
# ---------------------------------------------------------------------------


def test_catalogue_validates_without_error(catalogue: GeneratedJpMlitCatalogue) -> None:
    # validate_generated_catalogue raises on any schema violation.
    validate_generated_catalogue(
        catalogue.provider_info,
        catalogue.products,
        catalogue.stations,
        catalogue.station_products,
    )


# ---------------------------------------------------------------------------
# Packaged catalogue artifact (live round-trip via module)
# ---------------------------------------------------------------------------


def test_packaged_catalogue_loads() -> None:
    from rivretrieve._internal.providers.jp_mlit import module as jp_mlit_module

    artifact = jp_mlit_module._artifact()
    assert artifact is not None


def test_packaged_stations_count() -> None:
    from rivretrieve._internal.providers.jp_mlit import module as jp_mlit_module

    result = jp_mlit_module.stations()
    assert len(result.data) == 1024


def test_packaged_products_count() -> None:
    from rivretrieve._internal.providers.jp_mlit import module as jp_mlit_module

    result = jp_mlit_module.products()
    assert len(result.data) == 4


def test_packaged_station_products_count() -> None:
    from rivretrieve._internal.providers.jp_mlit import module as jp_mlit_module

    result = jp_mlit_module.station_products()
    assert len(result.data) == 4096  # 1024 × 4
