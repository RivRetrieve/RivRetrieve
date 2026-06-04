"""Tests for no_nve provider registration and module contract."""

from __future__ import annotations

import rivretrieve as rr


def test_no_nve_in_providers_list() -> None:
    assert "no_nve" in rr.providers()


def test_no_nve_provider_handle_returns() -> None:
    handle = rr.provider("no_nve")
    assert handle is not None


def test_no_nve_info_name() -> None:
    info = rr.provider("no_nve").info()
    assert "Norway" in info.name or "NVE" in info.name


def test_no_nve_catalogue_version() -> None:
    info = rr.provider("no_nve").info()
    assert info.catalogue_version is not None


def test_no_nve_live_stations_capability() -> None:
    """no_nve live_stations=False — generate_catalogue_from_live() is a maintainer tool, not a runtime path."""
    info = rr.provider("no_nve").info()
    assert info.live_stations is False


def test_no_nve_stations_returns_catalog_result() -> None:
    result = rr.provider("no_nve").stations()
    assert hasattr(result, "data")
    assert hasattr(result, "provenance")
    assert hasattr(result, "issues")


def test_no_nve_stations_count() -> None:
    result = rr.provider("no_nve").stations()
    assert len(result.data) == 4889


def test_no_nve_products_count() -> None:
    result = rr.provider("no_nve").products()
    assert len(result.data) == 9


def test_no_nve_products_include_canonical_and_provider_specific() -> None:
    result = rr.provider("no_nve").products()
    product_ids = set(result.data["product_id"].to_list())
    # Canonical V1 products.
    assert "discharge_daily_mean" in product_ids
    assert "stage_daily_mean" in product_ids
    assert "water_temperature_daily_mean" in product_ids
    assert "discharge_instantaneous" in product_ids
    assert "stage_instantaneous" in product_ids
    assert "water_temperature_instantaneous" in product_ids
    # Provider-specific hourly (no canonical hourly in V1 dictionary).
    assert "discharge_hourly_mean" in product_ids
    assert "stage_hourly_mean" in product_ids
    assert "water_temperature_hourly_mean" in product_ids


def test_no_nve_station_products_count() -> None:
    result = rr.provider("no_nve").station_products()
    assert len(result.data) == 44001  # 4889 stations × 9 products


def test_no_nve_station_products_availability_from_series_list() -> None:
    """Stations with seriesList should have available/unavailable rows, not unknown."""
    result = rr.provider("no_nve").station_products()
    availabilities = set(result.data["availability"].cast(str).to_list())
    # Our fixture has stations with non-empty and empty seriesList — no unknown expected.
    assert "unknown" not in availabilities


def test_no_nve_station_12_210_0_discharge_daily_available() -> None:
    result = rr.provider("no_nve").station_products()
    import polars as pl

    row = result.data.filter((pl.col("station_id") == "12.210.0") & (pl.col("product_id") == "discharge_daily_mean"))
    assert not row.is_empty()
    assert row["availability"].cast(str).to_list()[0] == "available"


def test_no_nve_station_12_210_0_discharge_instantaneous_available() -> None:
    """Live catalogue has discharge_instantaneous available for 12.210.0."""
    result = rr.provider("no_nve").station_products()
    import polars as pl

    row = result.data.filter((pl.col("station_id") == "12.210.0") & (pl.col("product_id") == "discharge_instantaneous"))
    assert not row.is_empty()
    assert row["availability"].cast(str).to_list()[0] == "available"


def test_no_nve_global_stations_includes_provider() -> None:
    result = rr.stations()
    provider_ids = result.data["provider_id"].unique().to_list()
    assert "no_nve" in provider_ids


def test_no_nve_annotation_schemas_non_empty() -> None:
    from rivretrieve._internal.providers.no_nve import module as no_nve_module

    assert len(no_nve_module.row_annotation_schema()) > 0
    assert len(no_nve_module.series_annotation_schema()) > 0


def test_no_nve_annotation_schema_ids_are_strings() -> None:
    from rivretrieve._internal.providers.no_nve import module as no_nve_module

    for schema in no_nve_module.row_annotation_schema() + no_nve_module.series_annotation_schema():
        assert isinstance(schema.annotation_id, str)
        assert schema.annotation_id


def test_no_nve_live_catalogue_returns_warning_issue() -> None:
    """source='live' for stations returns a warning issue (live_stations=False)."""
    result = rr.provider("no_nve").stations(source="live", on_issue="ignore")
    assert len(result.issues) > 0
