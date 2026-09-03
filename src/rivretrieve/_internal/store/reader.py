"""read_store : StoreQuery → StoreReadResult ⊎ StoreRefusal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Rows, RowsSchema, WindowEndpoint
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.store.validation import (
    ArtifactChecksum,
    PartitionIdentifier,
    SourceSchemaFingerprint,
    StoreManifest,
    StoreRoot,
    validate_store,
)


@dataclass(frozen=True, slots=True)
class StoreQuery:
    """A source-wall-clock query against one resolved observation store."""

    store: StoreRoot
    provider_id: ProviderId
    stations: tuple[str, ...]
    products: tuple[ProductId, ...]
    start: datetime | WindowEndpoint
    end: datetime | WindowEndpoint

    def __post_init__(self) -> None:
        if not isinstance(self.store, Path):
            raise TypeError("store query root must be a Path")
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise TypeError("store query provider id must be a non-empty string")
        if not isinstance(self.stations, tuple) or not isinstance(self.products, tuple):
            raise TypeError("store query stations and products must be tuples")
        if not self.stations or not self.products:
            raise ValueError("store queries require at least one station and product")
        if any(not isinstance(station, str) or not station for station in self.stations):
            raise ValueError("store query station ids must be non-empty strings")
        if any(not isinstance(product, str) or not product for product in self.products):
            raise ValueError("store query product ids must be non-empty strings")
        start = _as_datetime(self.start)
        end = _as_datetime(self.end)
        if start.tzinfo is not None or end.tzinfo is not None:
            raise ValueError("store query endpoints must be source wall-clock times without a time zone")
        if start > end:
            raise ValueError("store query start must not be after end")

    @property
    def root(self) -> StoreRoot:
        return self.store

    @property
    def station_ids(self) -> tuple[str, ...]:
        return self.stations

    @property
    def product_ids(self) -> tuple[ProductId, ...]:
        return self.products


@dataclass(frozen=True, slots=True)
class ExecutedStoreQuery:
    """The predicates expressed by a store scan."""

    products: tuple[ProductId, ...]
    years: tuple[int, ...]
    stations: tuple[str, ...]
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class StoreReadResult:
    store: StoreRoot
    provider_id: ProviderId
    query: StoreQuery
    manifest: StoreManifest
    executed_query: ExecutedStoreQuery
    rows: Rows
    physical_rows: pl.DataFrame
    optimized_plan: str

    @property
    def root(self) -> StoreRoot:
        return self.store

    @property
    def executed_predicate(self) -> ExecutedStoreQuery:
        return self.executed_query

    @property
    def selected_rows(self) -> pl.DataFrame:
        return self.physical_rows


class StorePresence(StrEnum):
    ABSENT = "absent"
    PRESENT = "present"


@dataclass(frozen=True, slots=True)
class StoreStatus:
    store: StoreRoot
    provider_id: ProviderId
    presence: StorePresence
    manifest: StoreManifest | None = None

    def __post_init__(self) -> None:
        if (self.presence is StorePresence.PRESENT) != (self.manifest is not None):
            raise ValueError("present store status requires exactly one validated manifest")

    @property
    def root(self) -> StoreRoot:
        return self.store

    @property
    def exists(self) -> bool:
        return self.presence is StorePresence.PRESENT

    @property
    def format_version(self) -> int | None:
        return None if self.manifest is None else self.manifest.format_version

    @property
    def compiler_version(self) -> str | None:
        return None if self.manifest is None else self.manifest.compiler_version

    @property
    def built_at(self) -> datetime | None:
        return None if self.manifest is None else self.manifest.built_at

    @property
    def source_vintage(self) -> date | None:
        return None if self.manifest is None else self.manifest.source_vintage

    @property
    def publisher_artifact_url(self) -> str | None:
        return None if self.manifest is None else self.manifest.publisher_artifact.url

    @property
    def publisher_artifact_checksum(self) -> ArtifactChecksum | None:
        return None if self.manifest is None else self.manifest.publisher_artifact.sha256

    @property
    def publisher_artifact_urls(self) -> tuple[str, ...]:
        return () if self.manifest is None else tuple(item.url for item in self.manifest.publisher_artifacts)

    @property
    def publisher_artifact_checksums(self) -> tuple[ArtifactChecksum, ...]:
        return () if self.manifest is None else tuple(item.sha256 for item in self.manifest.publisher_artifacts)

    @property
    def source_schema_fingerprint(self) -> SourceSchemaFingerprint | None:
        return None if self.manifest is None else self.manifest.source_schema.fingerprint

    @property
    def partition_row_counts(self) -> Mapping[PartitionIdentifier, int]:
        if self.manifest is None:
            return MappingProxyType({})
        return self.manifest.partition_row_counts


class StoreReader:
    """The source-neutral reader for revision-2 observation stores."""

    def query(self, query: StoreQuery) -> StoreReadResult:
        # Validation deliberately precedes partition selection and construction of any
        # lazy scan. In particular an unknown revision cannot cause a Parquet open.
        validated = validate_store(query.store, query.provider_id)
        executed = _executed_query(query)
        physical_rows, optimized_plan = _scan(query.store, executed)
        rows = _engine_rows(physical_rows)
        return StoreReadResult(
            store=query.store,
            provider_id=query.provider_id,
            query=query,
            manifest=validated.manifest,
            executed_query=executed,
            rows=rows,
            physical_rows=physical_rows,
            optimized_plan=optimized_plan,
        )

    def read(self, query: StoreQuery) -> StoreReadResult:
        return self.query(query)

    def status(self, store: StoreRoot, provider_id: ProviderId) -> StoreStatus:
        root = Path(store)
        if not root.exists():
            return StoreStatus(store=store, provider_id=provider_id, presence=StorePresence.ABSENT)
        validated = validate_store(store, provider_id)
        return StoreStatus(
            store=store,
            provider_id=provider_id,
            presence=StorePresence.PRESENT,
            manifest=validated.manifest,
        )


def read_store(query: StoreQuery, *, reader: StoreReader | None = None) -> StoreReadResult:
    return (reader or StoreReader()).query(query)


def store_status(store: StoreRoot, provider_id: ProviderId, *, reader: StoreReader | None = None) -> StoreStatus:
    return (reader or StoreReader()).status(store, provider_id)


def _as_datetime(endpoint: datetime | WindowEndpoint) -> datetime:
    if isinstance(endpoint, datetime):
        return endpoint
    return datetime(
        endpoint.year,
        endpoint.month,
        endpoint.day,
        endpoint.hour,
        endpoint.minute,
        endpoint.second,
        endpoint.microsecond,
    )


def _executed_query(query: StoreQuery) -> ExecutedStoreQuery:
    start = _as_datetime(query.start)
    end = _as_datetime(query.end)
    return ExecutedStoreQuery(
        products=tuple(dict.fromkeys(query.products)),
        years=tuple(range(start.year, end.year + 1)),
        stations=tuple(dict.fromkeys(query.stations)),
        start=start,
        end=end,
    )


def _scan(store: StoreRoot, executed: ExecutedStoreQuery) -> tuple[pl.DataFrame, str]:
    scan = pl.scan_parquet(
        str(Path(store) / "product=*" / "year=*" / "*.parquet"),
        hive_partitioning=True,
        missing_columns="raise",
        extra_columns="raise",
    ).filter(
        pl.col("product").is_in(tuple(str(product) for product in executed.products))
        & pl.col("year").is_in(executed.years)
        & pl.col("station_id").is_in(executed.stations)
        & (pl.col("time") >= executed.start)
        & (pl.col("time") <= executed.end)
    )
    optimized_plan = scan.explain(optimized=True)
    return cast(pl.DataFrame, scan.collect()), optimized_plan


def _engine_rows(physical_rows: pl.DataFrame) -> Rows:
    if physical_rows.is_empty():
        return pl.DataFrame(schema=RowsSchema.polars_schema)
    return physical_rows.select("station_id", pl.col("product").alias("product_id"), "time", "value", "time_zone")
