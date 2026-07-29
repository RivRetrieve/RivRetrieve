"""Engine stage seams ≔ WindowEndpoint × RequestedWindow × FetchWindow × ObservationRequest × SourceCoordinates × Payload × WithIssues[A] × Rows × CanonicalRows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

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
