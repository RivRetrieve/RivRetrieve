"""ObservationResult : ObservationData × ObservationProvenance × tuple[Issue, ...] × Receipts → immutable result."""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast

import polars as pl
from pydantic import BaseModel, ConfigDict, model_validator

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogues.schemas import CatalogueColumn, CatalogueSchema, validate_catalogue
from rivretrieve._internal.engine import SourceCallOrigin, WindowEndpoint
from rivretrieve._internal.issues import (
    FatalContractError,
    InvalidObservationRequestError,
    Issue,
    ObservationDataSchemaError,
)
from rivretrieve._internal.primitives import ProviderId

if TYPE_CHECKING:
    from rivretrieve._internal.store.reader import ExecutedStoreQuery
    from rivretrieve._internal.store.validation import StoreRoot

ObservationDataSchema = CatalogueSchema(
    name="ObservationData",
    columns=(
        CatalogueColumn("time", pl.Datetime()),
        CatalogueColumn("time_zone", pl.Utf8),
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
    license: str | None = None
    citation: str | None = None
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
    source_vintage: date | None = None
    publisher_artifact_checksum: str | None = None
    acquisition_provenance: AcquisitionProvenance | None = None


class ReceiptMode(StrEnum):
    OMIT = "omit"
    INCLUDE = "include"


class ReceiptAuthorship(StrEnum):
    PUBLISHER_PAYLOAD = "publisher_payload"
    STORE_EXCERPT = "store_excerpt"


@dataclass(frozen=True, slots=True)
class ReceiptEntry:
    content: bytes
    origin: SourceCallOrigin
    authorship: ReceiptAuthorship

    def __post_init__(self) -> None:
        if type(self.content) is not bytes:
            raise TypeError("content must be bytes")
        if not isinstance(self.origin, SourceCallOrigin):
            raise TypeError("origin must be SourceCallOrigin")
        if not isinstance(self.authorship, ReceiptAuthorship):
            raise TypeError("authorship must be ReceiptAuthorship.PUBLISHER_PAYLOAD or ReceiptAuthorship.STORE_EXCERPT")


@dataclass(frozen=True, slots=True)
class StoreExcerptReceipt(ReceiptEntry):
    """A faithful Parquet re-encoding of rows returned by a store query."""

    store_path: StoreRoot
    executed_query: ExecutedStoreQuery
    format_version: int
    source_vintage: date

    def __post_init__(self) -> None:
        ReceiptEntry.__post_init__(self)
        if self.authorship is not ReceiptAuthorship.STORE_EXCERPT:
            raise TypeError("store excerpt authorship must be ReceiptAuthorship.STORE_EXCERPT")
        if not isinstance(self.store_path, Path):
            raise TypeError("store excerpt path must be a Path")
        if not isinstance(self.executed_query, ExecutedStoreQuery):
            raise TypeError("store excerpt executed query must be ExecutedStoreQuery")
        if type(self.format_version) is not int:
            raise TypeError("store excerpt format version must be an integer")
        if not isinstance(self.source_vintage, date):
            raise TypeError("store excerpt source vintage must be a date")


@dataclass(frozen=True, slots=True)
class Receipts:
    provider_id: ProviderId
    entries: tuple[ReceiptEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple) or not all(isinstance(entry, ReceiptEntry) for entry in self.entries):
            raise TypeError("entries must be a tuple of ReceiptEntry values")


class ObservationResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    data: pl.DataFrame
    provenance: ObservationProvenance
    issues: tuple[Issue, ...] = ()
    receipts: Receipts

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


# Load the runtime names after the receipt classes exist so introspection can resolve
# their domain annotations without cycling through store.receipts.
ExecutedStoreQuery = importlib.import_module("rivretrieve._internal.store.reader").ExecutedStoreQuery
StoreRoot = importlib.import_module("rivretrieve._internal.store.validation").StoreRoot
