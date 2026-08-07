"""ObservationResult : ObservationData × ObservationProvenance × tuple[Issue, ...] × (RawPayload | None) → immutable result"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Self, cast

import polars as pl
from pydantic import BaseModel, ConfigDict, model_validator

from rivretrieve._internal.catalogues.schemas import CatalogueColumn, CatalogueSchema, validate_catalogue
from rivretrieve._internal.engine import WindowEndpoint
from rivretrieve._internal.issues import (
    FatalContractError,
    InvalidObservationRequestError,
    Issue,
    ObservationDataSchemaError,
)
from rivretrieve._internal.primitives import ProviderId

ObservationDataSchema = CatalogueSchema(
    name="ObservationData",
    columns=(
        CatalogueColumn("time", pl.Datetime()),
        CatalogueColumn("station_id", pl.Utf8),
        CatalogueColumn("product_id", pl.Utf8),
        CatalogueColumn("value", pl.Float64, nullable=True),
    ),
)


@dataclass(frozen=True)
class ObservationRequest:
    provider_id: ProviderId
    stations: tuple[str, ...]
    products: tuple[str, ...]
    start: WindowEndpoint
    end: WindowEndpoint

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
        normalized_start = _normalize_window_endpoint(start, name="start")
        normalized_end = _normalize_window_endpoint(end, name="end")
        if normalized_start > normalized_end:
            raise InvalidObservationRequestError("requested window start must not be after end")
        return cls(
            provider_id=_coerce_provider_id(provider_id),
            stations=_coerce_id_sequence(stations, name="stations"),
            products=_coerce_id_sequence(products, name="products"),
            start=normalized_start,
            end=normalized_end,
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
class RawPayload:
    provider_id: ProviderId
    content_type: str | None = None
    content: bytes | str | None = None
    metadata: str | None = None


class ObservationResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    data: pl.DataFrame
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


def _normalize_window_endpoint(value: object, *, name: str) -> WindowEndpoint:
    if value is None:
        raise InvalidObservationRequestError(f"{name} is required")
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            raise InvalidObservationRequestError(
                f"{name} must be wall-clock time without a time zone; "
                f"remove it with `{name} = {name}.replace(tzinfo=None)`."
            )
        return WindowEndpoint.from_datetime(value)
    if isinstance(value, date):
        raise InvalidObservationRequestError(f"{name} must be a datetime or ISO-like string")
    if isinstance(value, str):
        try:
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None:
                parsed_date = date.fromisoformat(value)
                parsed = datetime.combine(parsed_date, time.max if name == "end" else time.min)
            else:
                parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise InvalidObservationRequestError(f"{name} must be an ISO-like datetime string") from exc
        if parsed.tzinfo is not None:
            raise InvalidObservationRequestError(
                f"{name} must be wall-clock time without a time zone; remove it with "
                f"`{name} = datetime.fromisoformat({name}).replace(tzinfo=None)`."
            )
        return WindowEndpoint.from_datetime(parsed)
    raise InvalidObservationRequestError(f"{name} must be a datetime or ISO-like string")


def _require_non_empty_string(value: object, name: str, error_type: type[FatalContractError]) -> None:
    if not isinstance(value, str):
        raise error_type(f"{name} must be a string")
    if not value.strip():
        raise error_type(f"{name} must be non-empty")


def _is_polars_datetime_dtype(dtype: pl.DataType) -> bool:
    return dtype == pl.Datetime() or isinstance(dtype, pl.Datetime)
