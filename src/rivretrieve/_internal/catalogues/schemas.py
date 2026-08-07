"""catalogue validation : DataFrame × CatalogueSchema × OnIssue → list[Issue]."""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue, apply_on_issue
from rivretrieve._internal.primitives import OnIssue

AVAILABILITY_VALUES = ("available", "unavailable", "unknown")
AvailabilityDtype = pl.Enum(AVAILABILITY_VALUES)
type CatalogueDtype = pl.DataType | type[pl.DataType]


@dataclass(frozen=True)
class CatalogueColumn:
    name: str
    dtype: CatalogueDtype
    nullable: bool = False


@dataclass(frozen=True)
class CatalogueSchema:
    name: str
    columns: tuple[CatalogueColumn, ...]
    unique_keys: tuple[tuple[str, ...], ...] = ()
    enum_values: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def polars_schema(self) -> pl.Schema:
        return pl.Schema({column.name: column.dtype for column in self.columns})


STATION_CATALOG_SCHEMA = CatalogueSchema(
    name="StationCatalog",
    columns=(
        CatalogueColumn("provider_id", pl.Utf8),
        CatalogueColumn("station_id", pl.Utf8),
        CatalogueColumn("latitude", pl.Float64),
        CatalogueColumn("longitude", pl.Float64),
        CatalogueColumn("crs", pl.Utf8),
    ),
    unique_keys=(("provider_id", "station_id"),),
)

PRODUCT_CATALOG_SCHEMA = CatalogueSchema(
    name="ProductCatalog",
    columns=(
        CatalogueColumn("provider_id", pl.Utf8),
        CatalogueColumn("product_id", pl.Utf8),
        CatalogueColumn("observed_property", pl.Utf8),
        CatalogueColumn("frequency", pl.Utf8),
        CatalogueColumn("statistic", pl.Utf8),
        CatalogueColumn("period_type", pl.Utf8),
        CatalogueColumn("period_anchor", pl.Utf8),
        CatalogueColumn("unit", pl.Utf8),
        CatalogueColumn("native_id", pl.Utf8, nullable=True),
        CatalogueColumn("derived", pl.Boolean),
        CatalogueColumn("derivation_method", pl.Utf8, nullable=True),
    ),
    unique_keys=(("provider_id", "product_id"),),
)

STATION_PRODUCT_CATALOG_SCHEMA = CatalogueSchema(
    name="StationProductCatalog",
    columns=(
        CatalogueColumn("provider_id", pl.Utf8),
        CatalogueColumn("station_id", pl.Utf8),
        CatalogueColumn("product_id", pl.Utf8),
        CatalogueColumn("availability", AvailabilityDtype),
        CatalogueColumn("availability_reason", pl.Utf8, nullable=True),
        CatalogueColumn("start_date", pl.Date, nullable=True),
        CatalogueColumn("end_date", pl.Date, nullable=True),
        CatalogueColumn("last_catalogue_check", pl.Date),
    ),
    unique_keys=(("provider_id", "station_id", "product_id"),),
    enum_values={"availability": frozenset(AVAILABILITY_VALUES)},
)

PROVIDER_INFO_CATALOG_SCHEMA = CatalogueSchema(
    name="ProviderInfoCatalog",
    columns=(
        CatalogueColumn("provider_id", pl.Utf8),
        CatalogueColumn("name", pl.Utf8),
        CatalogueColumn("live_stations", pl.Boolean),
        CatalogueColumn("live_products", pl.Boolean),
        CatalogueColumn("live_station_products", pl.Boolean),
        CatalogueColumn("bulk_observations", pl.Utf8),
        CatalogueColumn("catalogue_version", pl.Utf8, nullable=True),
        CatalogueColumn("license", pl.Utf8, nullable=True),
        CatalogueColumn("citation", pl.Utf8, nullable=True),
    ),
    unique_keys=(("provider_id",),),
)

type StationCatalog = pl.DataFrame
type ProductCatalog = pl.DataFrame
type StationProductCatalog = pl.DataFrame
type ProviderInfoCatalog = pl.DataFrame


def validate_catalogue(
    df: pl.DataFrame,
    schema: CatalogueSchema,
    *,
    on_issue: OnIssue = "warn",
) -> list[Issue]:
    expected_columns = tuple(column.name for column in schema.columns)
    missing_columns = [name for name in expected_columns if name not in df.columns]
    if missing_columns:
        raise FatalContractError(f"{schema.name} is missing required columns: {', '.join(missing_columns)}")

    issues = _extra_column_issues(df, schema)
    apply_on_issue(issues, on_issue)

    for column in schema.columns:
        actual_dtype = df.schema[column.name]
        if actual_dtype != column.dtype:
            raise FatalContractError(f"{schema.name}.{column.name} has dtype {actual_dtype}, expected {column.dtype}")

        if not column.nullable and df[column.name].null_count() > 0:
            raise FatalContractError(f"{schema.name}.{column.name} contains null values")

    _validate_enum_values(df, schema)
    _validate_unique_keys(df, schema)

    return issues


def _extra_column_issues(df: pl.DataFrame, schema: CatalogueSchema) -> list[Issue]:
    expected_columns = {column.name for column in schema.columns}
    extra_columns = [name for name in df.columns if name not in expected_columns]
    if not extra_columns:
        return []

    return [
        Issue(
            severity="warning",
            code="catalogue.extra_columns",
            message=f"{schema.name} has extra columns: {', '.join(extra_columns)}",
            details={"schema": schema.name, "columns": extra_columns},
        )
    ]


def _validate_enum_values(df: pl.DataFrame, schema: CatalogueSchema) -> None:
    for column_name, allowed_values in schema.enum_values.items():
        values = set(df[column_name].drop_nulls().cast(pl.Utf8).unique().to_list())
        invalid_values = sorted(values - allowed_values)
        if invalid_values:
            raise FatalContractError(
                f"{schema.name}.{column_name} contains invalid enum values: {', '.join(invalid_values)}"
            )


def _validate_unique_keys(df: pl.DataFrame, schema: CatalogueSchema) -> None:
    for key_columns in schema.unique_keys:
        duplicate_count = df.select(pl.struct(key_columns).is_duplicated().sum()).item()
        if duplicate_count:
            joined_columns = ", ".join(key_columns)
            raise FatalContractError(f"{schema.name} contains duplicate key rows: {joined_columns}")
