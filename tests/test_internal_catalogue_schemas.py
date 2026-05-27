from __future__ import annotations

import warnings
from datetime import date

import polars as pl
import pytest

from rivretrieve._internal.catalogues.schemas import (
    AvailabilityDtype,
    ProductCatalog,
    ProviderInfoCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError


def station_catalog_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "provider_id": ["synthetic"],
        "station_id": ["station-1"],
        "name": ["Station 1"],
        "latitude": [46.2],
        "longitude": [7.1],
        "country": ["CH"],
        "elevation_m": [123.4],
        "drainage_area_km2": [56.7],
        "start_date": [date(2020, 1, 1)],
        "end_date": [None],
        "metadata": ['{"nested": {"provider": true}}'],
    }
    data.update(overrides)
    return pl.DataFrame(
        data,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "name": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "country": pl.Utf8,
            "elevation_m": pl.Float64,
            "drainage_area_km2": pl.Float64,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "metadata": pl.Utf8,
        },
    )


def station_product_catalog_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "provider_id": ["synthetic", "synthetic", "synthetic"],
        "station_id": ["station-1", "station-1", "station-1"],
        "product_id": ["level", "flow", "temp"],
        "availability": ["available", "unavailable", "unknown"],
        "availability_reason": [None, "source gap", "unchecked"],
        "start_date": [date(2020, 1, 1), None, None],
        "end_date": [None, None, None],
        "last_catalogue_check": [date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1)],
        "metadata": ["{}", "{}", "{}"],
    }
    data.update(overrides)
    return pl.DataFrame(
        data,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": AvailabilityDtype,
            "availability_reason": pl.Utf8,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "last_catalogue_check": pl.Date,
            "metadata": pl.Utf8,
        },
    )


def test_catalogue_schema_objects_define_expected_columns() -> None:
    assert tuple(StationCatalog.polars_schema.keys()) == (
        "provider_id",
        "station_id",
        "name",
        "latitude",
        "longitude",
        "country",
        "elevation_m",
        "drainage_area_km2",
        "start_date",
        "end_date",
        "metadata",
    )
    assert tuple(ProductCatalog.polars_schema.keys()) == (
        "provider_id",
        "product_id",
        "observed_property",
        "frequency",
        "statistic",
        "period_type",
        "period_anchor",
        "unit",
        "native_id",
        "derived",
        "derivation_method",
        "metadata",
    )
    assert tuple(StationProductCatalog.polars_schema.keys()) == (
        "provider_id",
        "station_id",
        "product_id",
        "availability",
        "availability_reason",
        "start_date",
        "end_date",
        "last_catalogue_check",
        "metadata",
    )
    assert tuple(ProviderInfoCatalog.polars_schema.keys()) == (
        "provider_id",
        "name",
        "live_stations",
        "live_products",
        "live_station_products",
        "bulk_observations",
        "catalogue_version",
        "metadata",
    )


def test_catalogue_schema_objects_define_polars_dtypes() -> None:
    assert StationCatalog.polars_schema == pl.Schema(
        {
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "name": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "country": pl.Utf8,
            "elevation_m": pl.Float64,
            "drainage_area_km2": pl.Float64,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "metadata": pl.Utf8,
        }
    )
    assert ProductCatalog.polars_schema["metadata"] == pl.Utf8
    assert ProductCatalog.polars_schema["derived"] == pl.Boolean
    assert ProductCatalog.polars_schema["native_id"] == pl.Utf8
    assert StationProductCatalog.polars_schema["availability"] == AvailabilityDtype
    assert StationProductCatalog.polars_schema["start_date"] == pl.Date
    assert StationProductCatalog.polars_schema["end_date"] == pl.Date
    assert StationProductCatalog.polars_schema["last_catalogue_check"] == pl.Date
    assert ProviderInfoCatalog.polars_schema["metadata"] == pl.Utf8


def test_station_catalog_nullable_fields_accept_non_null_values() -> None:
    issues = validate_catalogue(station_catalog_df(), StationCatalog, on_issue="raise")

    assert not [issue for issue in issues if issue.severity == "error"]


def test_station_catalog_nullable_fields_accept_null_values() -> None:
    df = pl.DataFrame(
        {
            "provider_id": ["synthetic", "synthetic"],
            "station_id": ["station-1", "station-2"],
            "name": ["Station 1", "Station 2"],
            "latitude": [46.2, 46.3],
            "longitude": [7.1, 7.2],
            "country": ["CH", "CH"],
            "elevation_m": [None, 12.3],
            "drainage_area_km2": [45.6, None],
            "start_date": [date(2020, 1, 1), None],
            "end_date": [None, None],
            "metadata": ["{}", "{}"],
        },
        schema=StationCatalog.polars_schema,
    )

    issues = validate_catalogue(df, StationCatalog, on_issue="raise")

    assert df.schema["elevation_m"] == pl.Float64
    assert df.schema["drainage_area_km2"] == pl.Float64
    assert not [issue for issue in issues if issue.severity == "error"]


def test_non_nullable_station_column_rejects_null() -> None:
    with pytest.raises(FatalContractError):
        validate_catalogue(station_catalog_df(name=[None]), StationCatalog)


def test_missing_required_column_rejected() -> None:
    with pytest.raises(FatalContractError):
        validate_catalogue(station_catalog_df().drop("station_id"), StationCatalog)


def test_wrong_dtype_rejected() -> None:
    df = station_catalog_df().with_columns(pl.col("latitude").cast(pl.Utf8))

    with pytest.raises(FatalContractError):
        validate_catalogue(df, StationCatalog)


def test_extra_column_returns_warning_issue() -> None:
    df = station_catalog_df().with_columns(pl.lit("kept").alias("provider_extra"))

    with warnings.catch_warnings(record=True) as warning_records:
        issues = validate_catalogue(df, StationCatalog, on_issue="ignore")

    assert warning_records == []
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "catalogue.extra_columns"


def test_availability_accepts_allowed_enum_values() -> None:
    issues = validate_catalogue(
        station_product_catalog_df(),
        StationProductCatalog,
        on_issue="raise",
    )

    assert not [issue for issue in issues if issue.severity == "error"]


def test_availability_rejects_invalid_value() -> None:
    invalid_availability_dtype = pl.Enum(["available", "unavailable", "unknown", "retired"])
    df = pl.DataFrame(
        {
            "provider_id": ["synthetic"],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "availability": pl.Series("availability", ["retired"], dtype=invalid_availability_dtype),
            "availability_reason": [None],
            "start_date": [None],
            "end_date": [None],
            "last_catalogue_check": [date(2026, 1, 1)],
            "metadata": ["{}"],
        },
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": invalid_availability_dtype,
            "availability_reason": pl.Utf8,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "last_catalogue_check": pl.Date,
            "metadata": pl.Utf8,
        },
    )

    with pytest.raises(FatalContractError):
        validate_catalogue(df, StationProductCatalog)


def test_metadata_column_is_opaque_json_object_string() -> None:
    df = station_catalog_df(metadata=['{"provider": {"deep": ["kept", 1]}}'])

    issues = validate_catalogue(df, StationCatalog, on_issue="raise")

    assert issues == []


def test_metadata_column_rejects_non_object_json() -> None:
    with pytest.raises(FatalContractError):
        validate_catalogue(station_catalog_df(metadata=["[]"]), StationCatalog)


def test_provider_info_catalog_validates_row_shape() -> None:
    df = pl.DataFrame(
        {
            "provider_id": ["synthetic"],
            "name": ["Synthetic Provider"],
            "live_stations": [False],
            "live_products": [False],
            "live_station_products": [False],
            "bulk_observations": ["none"],
            "catalogue_version": ["2026.01"],
            "metadata": ['{"homepage": "https://example.invalid"}'],
        },
        schema=ProviderInfoCatalog.polars_schema,
    )

    issues = validate_catalogue(df, ProviderInfoCatalog, on_issue="raise")

    assert issues == []
