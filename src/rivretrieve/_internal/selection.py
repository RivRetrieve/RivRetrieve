"""selection discovery : PackagedCatalogue × Query → Selection[Series]; Selection[Series] → StationCatalog."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal, Protocol

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA, StationCatalog
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.registry import UnknownProviderError

_IDENTITY_COLUMNS = ("provider_id", "station_id", "product_id")

SELECTION_FRAME_SCHEMA = pl.Schema(
    {
        "provider_id": pl.Utf8,
        "station_id": pl.Utf8,
        "product_id": pl.Utf8,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "crs": pl.Utf8,
        "observed_property": pl.Utf8,
        "frequency": pl.Utf8,
        "statistic": pl.Utf8,
        "period_type": pl.Utf8,
        "period_anchor": pl.Utf8,
        "unit": pl.Utf8,
        "native_id": pl.Utf8,
        "availability": pl.Enum(["available", "unknown"]),
        "availability_reason": pl.Utf8,
        "published_record_start_date": pl.Date,
        "published_record_end_date": pl.Date,
        "last_catalogue_check": pl.Date,
    }
)


class _CatalogueRecord(Protocol):
    provider_id: ProviderId
    artifact: PackagedCatalogArtifact


class UnknownProductError(FatalContractError):
    def __init__(self, product_id: str) -> None:
        self.product_id = product_id
        super().__init__(f"Canonical product is not registered: {product_id!r}")


class UnknownStationError(FatalContractError):
    def __init__(self, station_id: str, provider_ids: tuple[str, ...]) -> None:
        self.station_id = station_id
        self.provider_ids = provider_ids
        if len(provider_ids) == 1:
            message = f"Station is not registered for provider {provider_ids[0]!r}: {station_id!r}"
        elif provider_ids:
            message = f"Station is not registered for providers {provider_ids!r}: {station_id!r}"
        else:
            message = f"Station is not registered: {station_id!r}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _EmptyReason:
    code: Literal["no_catalogue_edge", "not_in_selection", "empty_frame"]
    provider_ids: tuple[str, ...]
    station_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    published_products: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Series:
    provider_id: str
    station_id: str
    product_id: str
    latitude: float
    longitude: float
    crs: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    unit: str
    native_id: str | None
    availability: Literal["available", "unknown"]
    availability_reason: str | None
    published_record_start_date: date | None
    published_record_end_date: date | None
    last_catalogue_check: date


@dataclass(frozen=True, slots=True)
class _Selection:
    series: tuple[_Series, ...]
    empty_reason: _EmptyReason | None = None
    acquisition_provenance: tuple[CatalogueEvidence, ...] = ()

    def __post_init__(self) -> None:
        keys = tuple(_series_key(row) for row in self.series)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise FatalContractError("Selection series must have sorted unique keys")
        if bool(self.series) == (self.empty_reason is not None):
            raise FatalContractError("Selection must carry an empty reason if and only if it has no series")

    def __str__(self) -> str:
        lines = ["provider_id | station_id | product_id"]
        lines.extend(" | ".join(_series_key(row)) for row in self.series)
        if self.empty_reason is not None:
            reason = self.empty_reason
            lines.extend(
                (
                    "<empty>",
                    f"empty_reason.code={reason.code}",
                    f"empty_reason.provider_ids={','.join(reason.provider_ids)}",
                    f"empty_reason.station_ids={','.join(reason.station_ids)}",
                    f"empty_reason.product_ids={','.join(reason.product_ids)}",
                    f"empty_reason.published_products={','.join(reason.published_products)}",
                )
            )
        return "\n".join(lines)

    def __repr__(self) -> str:
        return str(self)


@dataclass(frozen=True, slots=True)
class _Vocabulary:
    provider_ids: frozenset[str]
    product_ids: frozenset[str]
    station_keys: frozenset[tuple[str, str]]


def _find(
    records: Sequence[_CatalogueRecord],
    *,
    provider: str | None = None,
    station: str | None = None,
    product: str | None = None,
) -> _Selection:
    edges, vocabulary = _materialize(records)
    provider_ids = (provider,) if provider is not None else ()
    product_ids = (product,) if product is not None else ()
    station_ids = (station,) if station is not None else ()
    _validate_vocabulary(vocabulary, provider_ids, product_ids, station_ids)

    filtered = edges
    for column, value in (("provider_id", provider), ("station_id", station), ("product_id", product)):
        if value is not None:
            filtered = filtered.filter(pl.col(column) == value)
    if filtered.height:
        selected_provider_ids = tuple(filtered.get_column("provider_id").unique(maintain_order=True).to_list())
        return _selection_from_edge_frame(
            filtered,
            acquisition_provenance=_acquisition_provenance(records, selected_provider_ids),
        )

    published_products: tuple[str, ...] = ()
    if provider is not None and station is not None:
        published_products = tuple(
            edges.filter((pl.col("provider_id") == provider) & (pl.col("station_id") == station))
            .get_column("product_id")
            .sort()
            .to_list()
        )
    return _Selection(
        series=(),
        empty_reason=_EmptyReason(
            code="no_catalogue_edge",
            provider_ids=provider_ids,
            station_ids=station_ids,
            product_ids=product_ids,
            published_products=published_products,
        ),
        acquisition_provenance=_acquisition_provenance(records, provider_ids),
    )


def _pick(
    records: Sequence[_CatalogueRecord],
    selection: _Selection,
    *,
    provider: str | Sequence[str] | None = None,
    station: str | Sequence[str] | None = None,
    product: str | Sequence[str] | None = None,
) -> _Selection:
    _require_selection(selection)
    _, vocabulary = _materialize(records)
    provider_ids = _normalize(provider)
    product_ids = _normalize(product)
    station_ids = _normalize(station)
    _validate_vocabulary(vocabulary, provider_ids, product_ids, station_ids)

    if not selection.series:
        return _Selection(
            series=(),
            empty_reason=selection.empty_reason,
            acquisition_provenance=selection.acquisition_provenance,
        )

    provider_set = set(provider_ids)
    station_set = set(station_ids)
    product_set = set(product_ids)
    rows = tuple(
        row
        for row in selection.series
        if (not provider_set or row.provider_id in provider_set)
        and (not station_set or row.station_id in station_set)
        and (not product_set or row.product_id in product_set)
    )
    if rows:
        retained_provider_ids = tuple(dict.fromkeys(row.provider_id for row in rows))
        return _Selection(
            series=rows,
            acquisition_provenance=_acquisition_provenance(records, retained_provider_ids),
        )
    return _Selection(
        series=(),
        empty_reason=_EmptyReason(
            code="not_in_selection",
            provider_ids=tuple(sorted(provider_ids)),
            station_ids=tuple(sorted(station_ids)),
            product_ids=tuple(sorted(product_ids)),
            published_products=(),
        ),
        acquisition_provenance=selection.acquisition_provenance,
    )


def _as_frame(selection: _Selection) -> pl.DataFrame:
    _require_selection(selection)
    if not selection.series:
        return pl.DataFrame(schema=SELECTION_FRAME_SCHEMA)
    return pl.DataFrame([asdict(row) for row in selection.series], schema=SELECTION_FRAME_SCHEMA)


def _station_frame(selection: _Selection) -> StationCatalog:
    _require_selection(selection)
    return (
        _as_frame(selection)
        .select(STATION_CATALOG_SCHEMA.polars_schema.names())
        .unique(
            subset=["provider_id", "station_id"],
            keep="first",
            maintain_order=True,
        )
    )


def _from_frame(records: Sequence[_CatalogueRecord], frame: pl.DataFrame) -> _Selection:
    if not isinstance(frame, pl.DataFrame):
        raise TypeError("frame must be a polars.DataFrame")
    missing = [name for name in _IDENTITY_COLUMNS if name not in frame.columns]
    if missing:
        raise FatalContractError(f"Selection frame is missing required columns: {', '.join(missing)}")
    identity_positions = tuple(frame.columns.index(name) for name in _IDENTITY_COLUMNS)
    if identity_positions != tuple(sorted(identity_positions)):
        raise FatalContractError("Selection frame identity columns are not in canonical order")
    for name in _IDENTITY_COLUMNS:
        if frame.schema[name] != pl.Utf8:
            raise FatalContractError(f"Selection frame identity column {name} must have dtype String")

    identities = frame.select(_IDENTITY_COLUMNS)
    if identities.null_count().sum_horizontal().item() > 0:
        raise FatalContractError("Selection frame contains null identity values")
    if identities.is_duplicated().any():
        raise FatalContractError("Selection frame contains duplicate series keys: provider_id, station_id, product_id")
    if not identities.height:
        return _Selection(
            series=(),
            empty_reason=_EmptyReason(
                code="empty_frame",
                provider_ids=(),
                station_ids=(),
                product_ids=(),
                published_products=(),
            ),
        )

    edges, vocabulary = _materialize(records)
    identity_rows = identities.iter_rows()
    rows = tuple((str(provider), str(station), str(product)) for provider, station, product in identity_rows)
    _validate_frame_vocabulary(vocabulary, rows)
    edge_by_key = {_frame_row_key(row): row for row in edges.iter_rows(named=True)}
    for key in rows:
        if key not in edge_by_key:
            raise FatalContractError(f"Selection frame contains no catalogue edge: {key!r}")
    selected = pl.DataFrame([edge_by_key[key] for key in rows], schema=SELECTION_FRAME_SCHEMA)
    selected_provider_ids = tuple(dict.fromkeys(row[0] for row in rows))
    return _selection_from_edge_frame(
        selected,
        acquisition_provenance=_acquisition_provenance(records, selected_provider_ids),
    )


def _materialize(records: Sequence[_CatalogueRecord]) -> tuple[pl.DataFrame, _Vocabulary]:
    frames: list[pl.DataFrame] = []
    product_ids: set[str] = set()
    station_keys: set[tuple[str, str]] = set()
    for record in records:
        artifact = record.artifact
        product_ids.update(artifact.products.get_column("product_id").to_list())
        station_keys.update(
            (str(provider_id), str(station_id))
            for provider_id, station_id in artifact.stations.select("provider_id", "station_id").iter_rows()
        )
        frames.append(
            artifact.station_products.filter(pl.col("availability") != "unavailable")
            .join(artifact.stations, on=["provider_id", "station_id"], how="inner")
            .join(artifact.products, on=["provider_id", "product_id"], how="inner")
            .select(SELECTION_FRAME_SCHEMA.names())
            .cast(SELECTION_FRAME_SCHEMA)
        )
    edges = pl.concat(frames).sort(*_IDENTITY_COLUMNS) if frames else pl.DataFrame(schema=SELECTION_FRAME_SCHEMA)
    return edges, _Vocabulary(
        provider_ids=frozenset(record.provider_id for record in records),
        product_ids=frozenset(product_ids),
        station_keys=frozenset(station_keys),
    )


def _validate_vocabulary(
    vocabulary: _Vocabulary,
    provider_ids: tuple[str, ...],
    product_ids: tuple[str, ...],
    station_ids: tuple[str, ...],
) -> None:
    for provider_id in provider_ids:
        if provider_id not in vocabulary.provider_ids:
            raise UnknownProviderError(provider_id)
    for product_id in product_ids:
        if product_id not in vocabulary.product_ids:
            raise UnknownProductError(product_id)
    scoped_providers = tuple(sorted(provider_ids))
    for station_id in station_ids:
        candidates = scoped_providers or tuple(sorted(vocabulary.provider_ids))
        if not any((provider_id, station_id) in vocabulary.station_keys for provider_id in candidates):
            raise UnknownStationError(station_id, scoped_providers)


def _validate_frame_vocabulary(
    vocabulary: _Vocabulary,
    rows: tuple[tuple[str, str, str], ...],
) -> None:
    for provider_id in _ordered_unique(row[0] for row in rows):
        if provider_id not in vocabulary.provider_ids:
            raise UnknownProviderError(provider_id)
    for product_id in _ordered_unique(row[2] for row in rows):
        if product_id not in vocabulary.product_ids:
            raise UnknownProductError(product_id)
    for provider_id, station_id, _ in rows:
        if (provider_id, station_id) not in vocabulary.station_keys:
            raise UnknownStationError(station_id, (provider_id,))


def _normalize(value: str | Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    values = (value,) if isinstance(value, str) else tuple(value)
    return _ordered_unique(values)


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _acquisition_provenance(
    records: Sequence[_CatalogueRecord],
    provider_ids: Sequence[str],
) -> tuple[CatalogueEvidence, ...]:
    selected = set(provider_ids)
    return tuple(
        provenance
        for record in records
        if record.provider_id in selected
        if (provenance := record.artifact.acquisition_provenance) is not None
    )


def _selection_from_edge_frame(
    frame: pl.DataFrame,
    *,
    acquisition_provenance: tuple[CatalogueEvidence, ...] = (),
) -> _Selection:
    sorted_frame = frame.sort(*_IDENTITY_COLUMNS)
    return _Selection(
        series=tuple(_Series(**row) for row in sorted_frame.iter_rows(named=True)),  # type: ignore[arg-type]
        acquisition_provenance=acquisition_provenance,
    )


def _series_key(row: _Series) -> tuple[str, str, str]:
    return row.provider_id, row.station_id, row.product_id


def _frame_row_key(row: dict[str, object]) -> tuple[str, str, str]:
    return str(row["provider_id"]), str(row["station_id"]), str(row["product_id"])


def _require_selection(selection: object) -> None:
    if not isinstance(selection, _Selection):
        raise TypeError("selection must be a RivRetrieve selection")
