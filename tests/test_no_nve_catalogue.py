"""Tests for no_nve catalogue generation from fixtures."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.providers.no_nve.generate_catalogue import (
    generate_catalogue_from_fixture,
)

_FIXTURE = Path(__file__).parent / "test_data" / "no_nve_metadata.json"


def test_catalogue_from_fixture_station_count() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    assert len(cat.stations) == 3


def test_catalogue_from_fixture_product_count() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    assert len(cat.products) == 9


def test_catalogue_from_fixture_station_product_count() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    assert len(cat.station_products) == 27  # 3 × 9


def test_catalogue_station_identity_present() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "12.210.0")
    assert not row.is_empty()
    assert row["crs"][0] == "unknown"


def test_catalogue_products_include_all_nine() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    product_ids = set(cat.products["product_id"].to_list())
    expected = {
        "discharge_daily_mean",
        "discharge_hourly_mean",
        "discharge_instantaneous",
        "stage_daily_mean",
        "stage_hourly_mean",
        "stage_instantaneous",
        "water_temperature_daily_mean",
        "water_temperature_hourly_mean",
        "water_temperature_instantaneous",
    }
    assert product_ids == expected


def test_catalogue_product_discharge_daily_canonical_unit() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    row = cat.products.filter(pl.col("product_id") == "discharge_daily_mean")
    assert row["unit"][0] == "m3/s"


def test_catalogue_product_native_id_format() -> None:
    """native_id must be 'parameter_id:resolution_time' string."""
    cat = generate_catalogue_from_fixture(_FIXTURE)
    row = cat.products.filter(pl.col("product_id") == "discharge_daily_mean")
    assert row["native_id"][0] == "1001:1440"


def test_catalogue_station_product_availability_uses_series_list() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    # 12.210.0 has parameter 1001 (discharge), resTime 1440 → discharge_daily_mean available
    row = cat.station_products.filter(
        (pl.col("station_id") == "12.210.0") & (pl.col("product_id") == "discharge_daily_mean")
    )
    assert not row.is_empty()
    assert str(row["availability"][0]) == "available"


def test_catalogue_station_product_unavailable_for_missing_parameter() -> None:
    """water_temperature_daily_mean not in 12.210.0 seriesList → unavailable."""
    cat = generate_catalogue_from_fixture(_FIXTURE)
    row = cat.station_products.filter(
        (pl.col("station_id") == "12.210.0") & (pl.col("product_id") == "water_temperature_daily_mean")
    )
    assert not row.is_empty()
    assert str(row["availability"][0]) == "unavailable"


def test_catalogue_station_151_all_unavailable() -> None:
    """Station 151.10.0 with empty seriesList → all products unavailable."""
    cat = generate_catalogue_from_fixture(_FIXTURE)
    s151 = cat.station_products.filter(pl.col("station_id") == "151.10.0")
    availabilities = set(s151["availability"].cast(str).to_list())
    assert availabilities == {"unavailable"}


def test_catalogue_provider_info_name_contains_nve() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    assert "NVE" in cat.provider_info["name"]


def test_catalogue_provider_info_live_stations_false() -> None:
    """generate_catalogue_from_live() is a maintainer tool, not a runtime live catalogue."""
    cat = generate_catalogue_from_fixture(_FIXTURE)
    assert cat.provider_info["live_stations"] is False


def test_catalogue_provider_info_live_products_false() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    assert cat.provider_info["live_products"] is False


def test_catalogue_provider_id_is_no_nve() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    assert cat.provider_info["provider_id"] == "no_nve"


def test_catalogue_respects_catalogue_date() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE, catalogue_date=date(2024, 1, 15))
    assert cat.provider_info["catalogue_version"] == "2024-01-15"


def test_fixture_build_uses_exact_reduced_carriers() -> None:
    cat = generate_catalogue_from_fixture(_FIXTURE)
    assert cat.products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert cat.station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert tuple(cat.provider_info) == tuple(PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)


def _frame_content_sha256(frame: pl.DataFrame) -> str:
    def normalized(value: object) -> object:
        return value.isoformat() if isinstance(value, date | datetime) else value

    payload = {
        "columns": frame.columns,
        "rows": [[normalized(value) for value in row] for row in frame.iter_rows()],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def test_projected_national_artifacts_have_pinned_complete_content() -> None:
    catalogue = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/no_nve/catalogue"
    assert hashlib.sha256((catalogue / "provider.json").read_bytes()).hexdigest() == (
        "19ea7b5e39b30806bcdd1bbe150b7c0dfad1383bb8af064473b6a2fc21ae05ad"
    )
    assert _frame_content_sha256(pl.read_parquet(catalogue / "products.parquet")) == (
        "16700da08f87c7051742f567c7c080332269fda4b33638ffd62e95dec20e7f7f"
    )
    assert _frame_content_sha256(pl.read_parquet(catalogue / "stations.parquet")) == (
        "04d72696921bab0da6f0fe69f0f8df0059e77120fbd3c6e220a642b8b570f28b"
    )
    assert _frame_content_sha256(pl.read_parquet(catalogue / "station_products.parquet")) == (
        "19bcf56f22282f9a3efc4e89d0df85723951e74a62677d48a6ba1b01fa20c176"
    )
