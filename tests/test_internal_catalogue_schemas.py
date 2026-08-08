from __future__ import annotations

import warnings
from datetime import date

import polars as pl
import pytest

from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    AvailabilityDtype,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError


def station_catalog_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "provider_id": ["synthetic"],
        "station_id": ["station-1"],
        "latitude": [46.2],
        "longitude": [7.1],
        "crs": ["unknown"],
    }
    data.update(overrides)
    return pl.DataFrame(
        data,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "crs": pl.Utf8,
        },
    )


def station_product_catalog_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "provider_id": ["synthetic", "synthetic", "synthetic"],
        "station_id": ["station-1", "station-1", "station-1"],
        "product_id": ["level", "flow", "temp"],
        "availability": ["available", "unavailable", "unknown"],
        "availability_reason": [None, "source gap", "unchecked"],
        "published_record_start_date": [date(2020, 1, 1), None, None],
        "published_record_end_date": [None, None, None],
        "last_catalogue_check": [date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1)],
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
            "published_record_start_date": pl.Date,
            "published_record_end_date": pl.Date,
            "last_catalogue_check": pl.Date,
        },
    )


def test_catalogue_schema_objects_define_expected_columns() -> None:
    assert tuple(STATION_CATALOG_SCHEMA.polars_schema.keys()) == (
        "provider_id",
        "station_id",
        "latitude",
        "longitude",
        "crs",
    )
    assert tuple(PRODUCT_CATALOG_SCHEMA.polars_schema.keys()) == (
        "provider_id",
        "product_id",
        "observed_property",
        "frequency",
        "statistic",
        "period_type",
        "period_anchor",
        "unit",
        "native_id",
    )
    assert tuple(STATION_PRODUCT_CATALOG_SCHEMA.polars_schema.keys()) == (
        "provider_id",
        "station_id",
        "product_id",
        "availability",
        "availability_reason",
        "published_record_start_date",
        "published_record_end_date",
        "last_catalogue_check",
    )
    assert "start_date" not in STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert "end_date" not in STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert tuple(PROVIDER_INFO_CATALOG_SCHEMA.polars_schema.keys()) == (
        "provider_id",
        "name",
        "live_stations",
        "live_products",
        "live_station_products",
        "bulk_observations",
        "catalogue_version",
        "license",
        "citation",
    )


def test_catalogue_schema_objects_define_polars_dtypes() -> None:
    assert STATION_CATALOG_SCHEMA.polars_schema == pl.Schema(
        {
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "crs": pl.Utf8,
        }
    )
    assert PRODUCT_CATALOG_SCHEMA.polars_schema["native_id"] == pl.Utf8
    assert STATION_PRODUCT_CATALOG_SCHEMA.polars_schema["availability"] == AvailabilityDtype
    assert STATION_PRODUCT_CATALOG_SCHEMA.polars_schema["published_record_start_date"] == pl.Date
    assert STATION_PRODUCT_CATALOG_SCHEMA.polars_schema["published_record_end_date"] == pl.Date
    assert STATION_PRODUCT_CATALOG_SCHEMA.polars_schema["last_catalogue_check"] == pl.Date
    assert PROVIDER_INFO_CATALOG_SCHEMA.polars_schema["license"] == pl.Utf8
    assert PROVIDER_INFO_CATALOG_SCHEMA.polars_schema["citation"] == pl.Utf8
    assert PROVIDER_INFO_CATALOG_SCHEMA.columns[-2].nullable is True
    assert PROVIDER_INFO_CATALOG_SCHEMA.columns[-1].nullable is True


def test_station_catalog_validates_five_column_row() -> None:
    issues = validate_catalogue(station_catalog_df(), STATION_CATALOG_SCHEMA, on_issue="raise")

    assert not [issue for issue in issues if issue.severity == "error"]


def test_station_catalog_crs_is_non_null() -> None:
    assert next(column for column in STATION_CATALOG_SCHEMA.columns if column.name == "crs").nullable is False


def test_non_nullable_station_column_rejects_null() -> None:
    with pytest.raises(FatalContractError):
        validate_catalogue(station_catalog_df(crs=[None]), STATION_CATALOG_SCHEMA)


def test_missing_required_column_rejected() -> None:
    with pytest.raises(FatalContractError):
        validate_catalogue(station_catalog_df().drop("station_id"), STATION_CATALOG_SCHEMA)


def test_wrong_dtype_rejected() -> None:
    df = station_catalog_df().with_columns(pl.col("latitude").cast(pl.Utf8))

    with pytest.raises(FatalContractError):
        validate_catalogue(df, STATION_CATALOG_SCHEMA)


def test_extra_column_returns_warning_issue() -> None:
    df = station_catalog_df().with_columns(pl.lit("kept").alias("provider_extra"))

    with warnings.catch_warnings(record=True) as warning_records:
        issues = validate_catalogue(df, STATION_CATALOG_SCHEMA, on_issue="ignore")

    assert warning_records == []
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "catalogue.extra_columns"


def test_availability_accepts_allowed_enum_values() -> None:
    issues = validate_catalogue(
        station_product_catalog_df(),
        STATION_PRODUCT_CATALOG_SCHEMA,
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
            "published_record_start_date": [None],
            "published_record_end_date": [None],
            "last_catalogue_check": [date(2026, 1, 1)],
        },
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": invalid_availability_dtype,
            "availability_reason": pl.Utf8,
            "published_record_start_date": pl.Date,
            "published_record_end_date": pl.Date,
            "last_catalogue_check": pl.Date,
        },
    )

    with pytest.raises(FatalContractError):
        validate_catalogue(df, STATION_PRODUCT_CATALOG_SCHEMA)


def test_provider_info_catalog_validates_row_shape() -> None:
    df = pl.DataFrame(
        {
            "provider_id": ["synthetic"],
            "name": ["Synthetic Provider"],
            "live_stations": [False],
            "live_products": [False],
            "live_station_products": [False],
            "bulk_observations": [
                "true: 366-day window decomposition with stitched N x M station-product requests; partial failures "
                "reported as recoverable issues"
            ],
            "catalogue_version": ["2026.01"],
            "license": [None],
            "citation": [None],
        },
        schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema,
    )

    issues = validate_catalogue(df, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")

    assert issues == []
