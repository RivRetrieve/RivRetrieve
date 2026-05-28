from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Self, cast

import polars as pl
from pydantic import BaseModel, ConfigDict, model_validator

from rivretrieve._internal.catalogues.schemas import CatalogueColumn, CatalogueSchema, validate_catalogue
from rivretrieve._internal.issues import (
    AnnotationSchemaViolationError,
    FatalContractError,
    InvalidObservationRequestError,
    Issue,
    ObservationDataSchemaError,
)
from rivretrieve._internal.primitives import ProviderId

_ANNOTATION_VALUE_TYPES = frozenset({"string", "integer", "float", "boolean", "datetime", "json"})


ObservationDataSchema = CatalogueSchema(
    name="ObservationData",
    columns=(
        CatalogueColumn("time", pl.Datetime()),
        CatalogueColumn("station_id", pl.Utf8),
        CatalogueColumn("product_id", pl.Utf8),
        CatalogueColumn("value", pl.Float64, nullable=True),
    ),
)

AnnotationSchemaDeclaration = CatalogueSchema(
    name="AnnotationSchemaDeclaration",
    columns=(
        CatalogueColumn("annotation_id", pl.Utf8),
        CatalogueColumn("description", pl.Utf8),
        CatalogueColumn("value_type", pl.Utf8),
        CatalogueColumn("allowed_values", pl.Utf8, nullable=True),
        CatalogueColumn("source_field", pl.Utf8, nullable=True),
    ),
)

RowAnnotationTableSchema = CatalogueSchema(
    name="RowAnnotationTable",
    columns=(
        CatalogueColumn("time", pl.Datetime()),
        CatalogueColumn("station_id", pl.Utf8),
        CatalogueColumn("product_id", pl.Utf8),
        CatalogueColumn("annotation", pl.Utf8),
        CatalogueColumn("value", pl.Utf8, nullable=True),
    ),
)

SeriesAnnotationTableSchema = CatalogueSchema(
    name="SeriesAnnotationTable",
    columns=(
        CatalogueColumn("station_id", pl.Utf8),
        CatalogueColumn("product_id", pl.Utf8),
        CatalogueColumn("annotation", pl.Utf8),
        CatalogueColumn("value", pl.Utf8, nullable=True),
    ),
)


@dataclass(frozen=True)
class ObservationRequest:
    provider_id: ProviderId
    stations: tuple[str, ...]
    products: tuple[str, ...]
    start: datetime
    end: datetime

    @classmethod
    def from_inputs(
        cls,
        *,
        provider_id: ProviderId | str,
        stations: object,
        products: object,
        start: object,
        end: object,
    ) -> Self:
        return cls(
            provider_id=_coerce_provider_id(provider_id),
            stations=_coerce_id_sequence(stations, name="stations"),
            products=_coerce_id_sequence(products, name="products"),
            start=_coerce_datetime(start, name="start"),
            end=_coerce_datetime(end, name="end"),
        )


class ObservationProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    provider_id: ProviderId
    rivretrieve_version: str | None = None
    catalogue_version: str | None = None
    requested_at: datetime | None = None
    retrieved_at: datetime | None = None
    request: dict[str, object] | None = None
    calls_made: tuple[dict[str, object], ...] = ()
    time_windows: tuple[dict[str, object], ...] = ()
    decomposition: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()
    query: dict[str, object] | None = None
    response_version: str | None = None
    metadata: str | None = None


@dataclass(frozen=True)
class AnnotationSchema:
    annotation_id: str
    description: str
    value_type: str
    allowed_values: tuple[str, ...] | None = None
    source_field: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.annotation_id, "annotation_id", AnnotationSchemaViolationError)
        if not isinstance(self.description, str):
            raise AnnotationSchemaViolationError("description must be a string")
        _require_non_empty_string(self.value_type, "value_type", AnnotationSchemaViolationError)
        if self.value_type not in _ANNOTATION_VALUE_TYPES:
            raise AnnotationSchemaViolationError(f"unsupported annotation value_type: {self.value_type!r}")
        if self.allowed_values is not None and (
            not isinstance(self.allowed_values, tuple)
            or not all(isinstance(value, str) for value in self.allowed_values)
        ):
            raise AnnotationSchemaViolationError("allowed_values must be a tuple of strings when present")
        if self.source_field is not None:
            _require_non_empty_string(self.source_field, "source_field", AnnotationSchemaViolationError)

    def to_row(self) -> dict[str, object]:
        return {
            "annotation_id": self.annotation_id,
            "description": self.description,
            "value_type": self.value_type,
            "allowed_values": None if self.allowed_values is None else json.dumps(list(self.allowed_values)),
            "source_field": self.source_field,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> Self:
        allowed_values = row.get("allowed_values")
        parsed_allowed_values: tuple[str, ...] | None
        if allowed_values is None:
            parsed_allowed_values = None
        elif isinstance(allowed_values, str):
            try:
                parsed = json.loads(allowed_values)
            except json.JSONDecodeError as exc:
                raise AnnotationSchemaViolationError("allowed_values must be a JSON array string") from exc
            if not isinstance(parsed, list) or not all(isinstance(value, str) for value in parsed):
                raise AnnotationSchemaViolationError("allowed_values must be a JSON array string of strings")
            parsed_allowed_values = tuple(parsed)
        else:
            raise AnnotationSchemaViolationError("allowed_values must be a JSON array string or None")

        return cls(
            annotation_id=_row_string(row, "annotation_id"),
            description=_row_string(row, "description", allow_empty=True),
            value_type=_row_string(row, "value_type"),
            allowed_values=parsed_allowed_values,
            source_field=_row_optional_string(row, "source_field"),
        )


@dataclass(frozen=True)
class AnnotationTable:
    data: pl.DataFrame
    schema: CatalogueSchema

    def __post_init__(self) -> None:
        if not isinstance(self.data, pl.DataFrame):
            raise AnnotationSchemaViolationError("annotation table data must be a Polars DataFrame")
        expected = {column.name for column in self.schema.columns}
        extra = set(self.data.columns) - expected
        if extra:
            raise AnnotationSchemaViolationError(f"{self.schema.name} has extra columns: {sorted(extra)}")
        try:
            validate_catalogue(self.data, self.schema, on_issue="raise")
        except FatalContractError as exc:
            raise AnnotationSchemaViolationError(str(exc)) from exc


@dataclass(frozen=True)
class RawPayload:
    provider_id: ProviderId
    content_type: str | None = None
    content: bytes | str | None = None
    metadata: str | None = None


class ObservationResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    data: pl.DataFrame
    row_annotations: AnnotationTable
    series_annotations: AnnotationTable
    provenance: ObservationProvenance
    issues: tuple[Issue, ...] = ()
    raw: RawPayload | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_data_before_model(cls, values: object) -> object:
        if isinstance(values, Mapping):
            data = cast("Mapping[str, object]", values).get("data")
            validate_observation_data(data)
        return values

    def to_polars(self) -> pl.DataFrame:
        return self.data

    def to_pandas(self) -> Any:
        return self.data.to_pandas()


def validate_annotation_names(table: AnnotationTable, schemas: Sequence[AnnotationSchema]) -> None:
    declared = {schema.annotation_id for schema in schemas}
    emitted = set(table.data["annotation"].unique().to_list())
    undeclared = sorted(value for value in emitted if value not in declared)
    if undeclared:
        raise AnnotationSchemaViolationError(f"undeclared annotation names: {undeclared}")


def validate_observation_data(data: object) -> None:
    if not isinstance(data, pl.DataFrame):
        raise ObservationDataSchemaError("observation data must be a Polars DataFrame")

    expected = {column.name for column in ObservationDataSchema.columns}
    actual = set(data.columns)
    extra = actual - expected
    if extra:
        raise ObservationDataSchemaError(f"{ObservationDataSchema.name} has extra columns: {sorted(extra)}")

    validation_schema = ObservationDataSchema
    if "time" in data.columns:
        actual_time_dtype = data.schema["time"]
        if _is_polars_datetime_dtype(actual_time_dtype):
            validation_schema = CatalogueSchema(
                name=ObservationDataSchema.name,
                columns=tuple(
                    CatalogueColumn(column.name, actual_time_dtype, nullable=column.nullable)
                    if column.name == "time"
                    else column
                    for column in ObservationDataSchema.columns
                ),
            )

    try:
        validate_catalogue(data, validation_schema, on_issue="raise")
    except FatalContractError as exc:
        raise ObservationDataSchemaError(str(exc)) from exc


def _coerce_provider_id(provider_id: object) -> ProviderId:
    if provider_id is None:
        raise InvalidObservationRequestError("provider_id is required")
    if not isinstance(provider_id, str):
        raise InvalidObservationRequestError("provider_id must be string-like")
    if not provider_id.strip():
        raise InvalidObservationRequestError("provider_id must be non-empty")
    return ProviderId(str(provider_id))


def _coerce_id_sequence(value: object, *, name: str) -> tuple[str, ...]:
    if value is None:
        raise InvalidObservationRequestError(f"{name} is required")
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Sequence):
        values = tuple(value)
    else:
        raise InvalidObservationRequestError(f"{name} must be a string or sequence of strings")

    if not values:
        raise InvalidObservationRequestError(f"{name} must not be empty")
    normalized: list[str] = []
    for item in values:
        _require_non_empty_string(item, name, InvalidObservationRequestError)
        normalized.append(cast("str", item))
    return tuple(normalized)


def _coerce_datetime(value: object, *, name: str) -> datetime:
    if value is None:
        raise InvalidObservationRequestError(f"{name} is required")
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise InvalidObservationRequestError(f"{name} must be an ISO-like datetime string") from exc
    raise InvalidObservationRequestError(f"{name} must be a datetime, date, or ISO-like string")


def _require_non_empty_string(value: object, name: str, error_type: type[FatalContractError]) -> None:
    if not isinstance(value, str):
        raise error_type(f"{name} must be a string")
    if not value.strip():
        raise error_type(f"{name} must be non-empty")


def _row_string(row: Mapping[str, object], key: str, *, allow_empty: bool = False) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise AnnotationSchemaViolationError(f"{key} must be a string")
    if not allow_empty and not value.strip():
        raise AnnotationSchemaViolationError(f"{key} must be non-empty")
    return value


def _row_optional_string(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AnnotationSchemaViolationError(f"{key} must be a non-empty string when present")
    return value


def _is_polars_datetime_dtype(dtype: pl.DataType) -> bool:
    return dtype == pl.Datetime() or isinstance(dtype, pl.Datetime)
