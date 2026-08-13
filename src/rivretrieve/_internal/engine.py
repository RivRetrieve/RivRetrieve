"""Engine stage seams ≔ wall-clock WindowEndpoint × RequestedWindow × FetchWindow × WindowGranularity × WindowRenderingVocabulary × StopConvention × WindowDeclaration × ProductWindowDeclarations × RenderedWindow × ObservationRequest × SourceCoordinates × SourceCallParameter × UnknownOriginFact × SourceQuery × SourceCallOrigin × Payload × WithIssues[A] × Rows × CanonicalRows × Unit × Instant × Daily × DayDefinition × ZoneValue × CacheConfig × ProductConfig × ProviderConfig.

Payload ≔ SourceCoordinates × station-product tags × FetchWindow × bytes × SourceCallOrigin.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import NewType, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import polars as pl

from rivretrieve._internal.catalogues.schemas import CatalogueColumn, CatalogueSchema
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProductId, ProviderId


@dataclass(frozen=True, slots=True, order=True)
class WindowEndpoint:
    """An immutable wall-clock endpoint exposing rendering fields only."""

    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    microsecond: int

    def __post_init__(self) -> None:
        """Require integer fields and a valid calendar value."""
        values = (
            self.year,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
        )
        if any(type(value) is not int for value in values):
            raise TypeError("wall-clock endpoint fields must be integers")
        datetime(*values)

    @classmethod
    def from_datetime(cls, value: datetime) -> Self:
        """Create an endpoint from a naive standard-library datetime.

        Parameters
        ----------
        value
            Naive wall-clock datetime.
        """
        if not isinstance(value, datetime):
            raise TypeError("wall-clock endpoint requires a datetime")
        if value.tzinfo is not None:
            raise TypeError("wall-clock endpoint must not carry a time zone")
        return cls(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
        )

    @property
    def date(self) -> str:
        """Return the calendar date in ISO form."""
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    def isoformat(self) -> str:
        """Return the wall-clock endpoint in standard datetime ISO form."""
        return datetime(
            self.year,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
        ).isoformat()


@dataclass(frozen=True, slots=True)
class RequestedWindow:
    """A requested interval closed at both ends."""

    start: WindowEndpoint
    end: WindowEndpoint

    def __post_init__(self) -> None:
        if not isinstance(self.start, WindowEndpoint) or not isinstance(self.end, WindowEndpoint):
            raise TypeError("requested window endpoints must be WindowEndpoint values")
        if self.start > self.end:
            raise ValueError("requested window start must not be after end")


@dataclass(frozen=True, slots=True, init=False)
class FetchWindow:
    """A fetch interval closed at both ends."""

    start: WindowEndpoint
    end: WindowEndpoint

    def __init__(self, *, start: WindowEndpoint, end: WindowEndpoint) -> None:
        raise TypeError("FetchWindow is engine-owned and cannot be constructed by providers")


def _make_fetch_window(start: WindowEndpoint, end: WindowEndpoint) -> FetchWindow:
    if not isinstance(start, WindowEndpoint) or not isinstance(end, WindowEndpoint):
        raise TypeError("fetch window endpoints must be WindowEndpoint values")
    if start > end:
        raise ValueError("fetch window start must not be after end")
    window = object.__new__(FetchWindow)
    object.__setattr__(window, "start", start)
    object.__setattr__(window, "end", end)
    return window


WindowGranularity = NewType("WindowGranularity", str)


class WindowRenderingVocabulary(StrEnum):
    ISO_INSTANT = "iso-instant"
    DATE = "date"
    YEAR = "year"
    YEAR_MONTH = "year-month"
    NONE = "none"


class StopConvention(StrEnum):
    INCLUSIVE = "inclusive"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True, slots=True)
class WindowDeclaration:
    granularity: WindowGranularity
    rendering: WindowRenderingVocabulary
    stop_convention: StopConvention
    size: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.granularity, str) or not self.granularity:
            raise TypeError("window granularity must be a non-empty string")
        if not isinstance(self.rendering, WindowRenderingVocabulary):
            raise TypeError("window rendering must be WindowRenderingVocabulary")
        if not isinstance(self.stop_convention, StopConvention):
            raise TypeError("window stop convention must be StopConvention")
        if self.size is not None and (type(self.size) is not int or self.size <= 0):
            raise TypeError("window granularity size must be a positive integer or None")


@dataclass(frozen=True, slots=True)
class ProductWindowDeclarations:
    products: Mapping[ProductId, WindowDeclaration]

    def __post_init__(self) -> None:
        if not isinstance(self.products, Mapping):
            raise TypeError("product window declarations must be a mapping")
        for product_id, declaration in self.products.items():
            if not isinstance(product_id, str) or not product_id:
                raise TypeError("product window declaration keys must be non-empty ProductId values")
            if not isinstance(declaration, WindowDeclaration):
                raise TypeError("product window declaration values must be WindowDeclaration values")
        object.__setattr__(self, "products", MappingProxyType(dict(self.products)))


@dataclass(frozen=True, slots=True)
class RenderedWindow:
    start: str
    stop: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.start, str) or not self.start:
            raise TypeError("rendered window start must be a non-empty string")
        if self.stop is not None and (not isinstance(self.stop, str) or not self.stop):
            raise TypeError("rendered window stop must be a non-empty string or None")


@dataclass(frozen=True, slots=True)
class ObservationRequest:
    provider_id: ProviderId
    stations: tuple[str, ...]
    products: tuple[ProductId, ...]
    window: RequestedWindow


@dataclass(frozen=True, slots=True)
class SourceCoordinates:
    value: object


type SourceCallParameter = str | int | float | bytes | None


@dataclass(frozen=True, slots=True)
class UnknownOriginFact:
    pass


def _is_source_call_parameter(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bytes)


@dataclass(frozen=True, slots=True)
class SourceQuery:
    statement: str
    parameters: tuple[SourceCallParameter, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.statement, str) or not self.statement:
            raise TypeError("source query statement must be a non-empty string")
        if not isinstance(self.parameters, tuple):
            raise TypeError("source query parameters must be a tuple")
        if any(not _is_source_call_parameter(value) for value in self.parameters):
            raise TypeError("source query parameters contain an unsupported value")


@dataclass(frozen=True, slots=True)
class SourceCallOrigin:
    url: str | UnknownOriginFact
    request_parameters: Mapping[str, SourceCallParameter] | UnknownOriginFact
    status_code: int | UnknownOriginFact
    retrieved_at: datetime | UnknownOriginFact
    content_type: str | UnknownOriginFact
    source_path: str | UnknownOriginFact
    query: SourceQuery | UnknownOriginFact

    def __post_init__(self) -> None:
        for name in ("url", "content_type", "source_path"):
            value = getattr(self, name)
            if not isinstance(value, UnknownOriginFact) and (not isinstance(value, str) or not value):
                raise TypeError(f"known source-call {name} must be a non-empty string")

        parameters = self.request_parameters
        if isinstance(parameters, UnknownOriginFact):
            pass
        elif isinstance(parameters, Mapping):
            if any(not isinstance(key, str) for key in parameters):
                raise TypeError("source-call request parameter names must be strings")
            if any(not _is_source_call_parameter(value) for value in parameters.values()):
                raise TypeError("source-call request parameters contain an unsupported value")
            object.__setattr__(self, "request_parameters", MappingProxyType(dict(parameters)))
        else:
            raise TypeError("source-call request parameters must be a mapping or UnknownOriginFact")

        if not isinstance(self.status_code, UnknownOriginFact) and (type(self.status_code) is not int):
            raise TypeError("known source-call status code must be an integer")

        retrieved_at = self.retrieved_at
        if not isinstance(retrieved_at, UnknownOriginFact):
            if not isinstance(retrieved_at, datetime):
                raise TypeError("source-call retrieval instant must be a datetime or UnknownOriginFact")
            if retrieved_at.tzinfo is None or retrieved_at.utcoffset() != timedelta(0):
                raise ValueError("known source-call retrieval instant must be timezone-aware UTC")

        if not isinstance(self.query, SourceQuery | UnknownOriginFact):
            raise TypeError("source-call query must be SourceQuery or UnknownOriginFact")


@dataclass(frozen=True, slots=True)
class Payload:
    source_coordinates: SourceCoordinates
    station_products: tuple[tuple[str, ProductId], ...]
    fetch_window: FetchWindow
    content: bytes
    origin: SourceCallOrigin

    def __post_init__(self) -> None:
        if type(self.content) is not bytes:
            raise TypeError("payload content must be bytes")
        if not isinstance(self.origin, SourceCallOrigin):
            raise TypeError("payload origin must be SourceCallOrigin")


@dataclass(frozen=True, slots=True)
class WithIssues[A]:
    value: A
    issues: tuple[Issue, ...] = ()


type Rows = pl.DataFrame
type CanonicalRows = pl.DataFrame

RowsSchema = CatalogueSchema(
    name="Rows",
    columns=(
        CatalogueColumn("station_id", pl.Utf8),
        CatalogueColumn("product_id", pl.Utf8),
        CatalogueColumn("time", pl.Datetime()),
        CatalogueColumn("value", pl.Float64, nullable=True),
        CatalogueColumn("time_zone", pl.Utf8),
    ),
)

CanonicalRowsSchema = CatalogueSchema(
    name="CanonicalRows",
    columns=(
        CatalogueColumn("time", pl.Datetime()),
        CatalogueColumn("time_zone", pl.Utf8),
        CatalogueColumn("station_id", pl.Utf8),
        CatalogueColumn("product_id", pl.Utf8),
        CatalogueColumn("value", pl.Float64, nullable=True),
    ),
)


class Unit(StrEnum):
    M3_S = "m3/s"
    M = "m"
    CM = "cm"
    FT3_S = "ft3/s"
    FT = "ft"
    L_S = "l/s"
    MM = "mm"
    DEG_C = "degC"


@dataclass(frozen=True, slots=True)
class Instant:
    pass


@dataclass(frozen=True, slots=True)
class DayDefinition:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("day definition must be a string")
        if self.value == "unknown":
            return
        if re.fullmatch(r"[0-9]{2}:[0-9]{2}", self.value) is None:
            raise ValueError("day definition must be 'unknown' or a strict HH:MM clock value")
        hours, minutes = (int(part) for part in self.value.split(":"))
        if hours > 23 or minutes > 59:
            raise ValueError("day definition clock value is out of range")


@dataclass(frozen=True, slots=True)
class Daily:
    day_definition: DayDefinition

    def __post_init__(self) -> None:
        if not isinstance(self.day_definition, DayDefinition):
            raise TypeError("daily semantics require a DayDefinition")


@dataclass(frozen=True, slots=True)
class ZoneValue:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("zone value must be a string")
        if self.value == "unknown":
            return
        if self.value.startswith(("+", "-")):
            if re.fullmatch(r"[+-][0-9]{2}:[0-9]{2}", self.value) is None:
                raise ValueError("zone offset must have the strict shape ±HH:MM")
            hours, minutes = (int(part) for part in self.value[1:].split(":"))
            if hours > 23 or minutes > 59:
                raise ValueError("zone offset is out of range")
            return
        if "/" in self.value:
            try:
                ZoneInfo(self.value)
            except ZoneInfoNotFoundError as error:
                raise ValueError(f"unknown IANA zone: {self.value}") from error
            return
        raise ValueError("zone value must be an IANA identifier, a strict ±HH:MM offset, or 'unknown'")


@dataclass(frozen=True, slots=True)
class ObservationStoreConfig:
    """The on-disk observation-store revision a bulk provider compiles."""

    format_version: int

    def __post_init__(self) -> None:
        if type(self.format_version) is not int or self.format_version < 1:
            raise ValueError("observation store format version must be a positive integer")


@dataclass(frozen=True, slots=True)
class CacheConfig:
    """A provider declaration that observations live in a compiled store."""

    store: ObservationStoreConfig | None = None


@dataclass(frozen=True, slots=True)
class ProductConfig:
    coordinates: SourceCoordinates
    unit: Unit
    semantics: Instant | Daily

    def __post_init__(self) -> None:
        if not isinstance(self.coordinates, SourceCoordinates):
            raise TypeError("product coordinates must be SourceCoordinates")
        if not isinstance(self.unit, Unit):
            raise TypeError("product unit must be Unit")
        if not isinstance(self.semantics, (Instant, Daily)):
            raise TypeError("product semantics must be Instant or Daily")


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    zone: ZoneValue
    products: Mapping[ProductId, ProductConfig]
    cache: CacheConfig | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.zone, ZoneValue):
            raise TypeError("provider zone must be ZoneValue")
        if not isinstance(self.products, Mapping):
            raise TypeError("provider products must be a mapping")
        for product_id, product in self.products.items():
            if not isinstance(product_id, str) or not product_id:
                raise TypeError("product keys must be non-empty strings")
            if not isinstance(product, ProductConfig):
                raise TypeError("product values must be ProductConfig")
        if self.cache is not None and not isinstance(self.cache, CacheConfig):
            raise TypeError("provider cache must be CacheConfig or None")
        object.__setattr__(self, "products", MappingProxyType(dict(self.products)))
