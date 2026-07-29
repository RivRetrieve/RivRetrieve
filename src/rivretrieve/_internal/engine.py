"""Engine stage seams ≔ WindowEndpoint × RequestedWindow × FetchWindow × ObservationRequest × SourceCoordinates × Payload × WithIssues[A] × Rows × CanonicalRows × Unit × Instant × Daily × DayDefinition × ZoneValue × CacheConfig × ProductConfig × ProviderConfig."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import NewType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import polars as pl

from rivretrieve._internal.catalogues.schemas import CatalogueColumn, CatalogueSchema
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProductId, ProviderId

WindowEndpoint = NewType("WindowEndpoint", object)


@dataclass(frozen=True, slots=True)
class RequestedWindow:
    """A requested interval closed at both ends."""

    start: WindowEndpoint
    end: WindowEndpoint


@dataclass(frozen=True, slots=True)
class FetchWindow:
    """A fetch interval closed at both ends."""

    start: WindowEndpoint
    end: WindowEndpoint


@dataclass(frozen=True, slots=True)
class ObservationRequest:
    provider_id: ProviderId
    stations: tuple[str, ...]
    products: tuple[ProductId, ...]
    window: RequestedWindow


@dataclass(frozen=True, slots=True)
class SourceCoordinates:
    value: object


@dataclass(frozen=True, slots=True)
class Payload:
    source_coordinates: SourceCoordinates
    station_products: tuple[tuple[str, ProductId], ...]
    fetch_window: FetchWindow
    content: object


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
class CacheConfig:
    pass


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
