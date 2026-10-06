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

from rivretrieve._internal.coverage import CoverageInterval
from rivretrieve._internal.engine import Rows, RowsSchema, WindowEndpoint
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_series import SeriesWindow
from rivretrieve._internal.store.authority import CurrentEvidence
from rivretrieve._internal.store.integrity import SealedStore
from rivretrieve._internal.store.lifecycle import Ownership, StoreLifecycleError, inspect_lifecycle
from rivretrieve._internal.store.validation import (
    AccumulatedStoreManifest,
    ArtifactChecksum,
    Disposition,
    PartitionIdentifier,
    SourceSchemaFingerprint,
    StoreManifest,
    StoreRefusalKind,
    StoreRoot,
    _refuse,
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
    series_ids: tuple[str, ...] = ()
    series_windows: tuple[tuple[str, SeriesWindow], ...] = ()
    facts_ids: tuple[str, ...] = ()

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
    series_ids: tuple[str, ...] = ()
    series_windows: tuple[tuple[str, SeriesWindow], ...] = ()
    facts_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StoreReadResult:
    store: StoreRoot
    provider_id: ProviderId
    query: StoreQuery
    manifest: StoreManifest | AccumulatedStoreManifest
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
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class StoreStatus:
    """Metadata-checked local state without reading observation bytes.

    Attributes
    ----------
    store : StoreRoot
        Resolved local store path, also exposed as root.
    provider_id : ProviderId
        Provider whose store was inspected.
    presence : StorePresence
        ``present`` identifies committed data. ``interrupted`` identifies
        unfinished work without committed data. ``absent`` means neither exists.
        The exists property reports committed data, not unfinished staging.
    manifest : StoreManifest, AccumulatedStoreManifest or None
        Manifest checked against its publication identity and metadata rules.
        Presence does not claim all observation bytes have been checked.
    bytes_on_disk : int
        Logical bytes in committed metadata, partitions and seal, zero without
        committed data. Cleanup residue is listed separately. This is not
        allocated disk space or the bytes a clear operation will reclaim.
    coverage : tuple[CoverageInterval, ...]
        Current successful accumulated-store coverage, otherwise empty.
    partition_row_counts : Mapping[PartitionIdentifier, int]
        Property exposing physical row counts, empty when absent.
    format_version, compiler_version, built_at, source_vintage
        Properties exposing applicable manifest fields, otherwise None.
    publisher_artifact_url, publisher_artifact_checksum, source_schema_fingerprint
        Compiled-store identity properties, otherwise None.
    publisher_artifact_urls, publisher_artifact_checksums : tuple
        Ordered identities for all compiled artifacts, otherwise empty.
    generation_id : str or None
        Identity of the committed publication whose metadata was checked.
    committed_path : pathlib.Path or None
        Selected committed data, including recoverable prior data during an
        interrupted replacement. It can differ from the canonical store path.
    interrupted_paths : tuple[pathlib.Path, ...]
        Recognized work requiring recovery before reads or another acquisition.
    cleanup_paths : tuple[pathlib.Path, ...]
        Residue remaining after commit. Its presence does not invalidate the
        selected new generation.
    ownership : Ownership
        Local ownership state: idle, active, abandoned or ambiguous. Active or
        ambiguous ownership prevents recovery and clear.
    """

    store: StoreRoot
    provider_id: ProviderId
    presence: StorePresence
    manifest: StoreManifest | AccumulatedStoreManifest | None = None
    bytes_on_disk: int = 0
    generation_id: str | None = None
    committed_path: Path | None = None
    interrupted_paths: tuple[Path, ...] = ()
    cleanup_paths: tuple[Path, ...] = ()
    ownership: Ownership = Ownership.IDLE

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
        return self.manifest.compiler_version if isinstance(self.manifest, StoreManifest) else None

    @property
    def built_at(self) -> datetime | None:
        return None if self.manifest is None else self.manifest.built_at

    @property
    def source_vintage(self) -> date | None:
        return self.manifest.source_vintage if isinstance(self.manifest, StoreManifest) else None

    @property
    def publisher_artifact_url(self) -> str | None:
        return self.manifest.publisher_artifact.url if isinstance(self.manifest, StoreManifest) else None

    @property
    def publisher_artifact_checksum(self) -> ArtifactChecksum | None:
        return self.manifest.publisher_artifact.sha256 if isinstance(self.manifest, StoreManifest) else None

    @property
    def publisher_artifact_urls(self) -> tuple[str, ...]:
        return (
            tuple(item.url for item in self.manifest.publisher_artifacts)
            if isinstance(self.manifest, StoreManifest)
            else ()
        )

    @property
    def publisher_artifact_checksums(self) -> tuple[ArtifactChecksum, ...]:
        return (
            tuple(item.sha256 for item in self.manifest.publisher_artifacts)
            if isinstance(self.manifest, StoreManifest)
            else ()
        )

    @property
    def source_schema_fingerprint(self) -> SourceSchemaFingerprint | None:
        return self.manifest.source_schema.fingerprint if isinstance(self.manifest, StoreManifest) else None

    @property
    def partition_row_counts(self) -> Mapping[PartitionIdentifier, int]:
        if self.manifest is None:
            return MappingProxyType({})
        return self.manifest.partition_row_counts

    @property
    def coverage(self) -> tuple[CoverageInterval, ...]:
        return self.manifest.coverage if isinstance(self.manifest, AccumulatedStoreManifest) else ()


@dataclass(frozen=True, slots=True)
class CacheRecoveryResult:
    """The resulting local state and actions taken by explicit recovery.

    Attributes
    ----------
    provider_id : ProviderId
        Provider whose local storage was inspected and recovered.
    path : pathlib.Path
        Resolved canonical observation-store path.
    status : StoreStatus
        Resulting metadata-checked state. Recovery validates any committed
        generation it preserves or restores before discarding recovery inputs.
    actions : tuple[str, ...]
        Stable readable descriptions of preserved, restored or removed paths.
    """

    provider_id: ProviderId
    path: Path
    status: StoreStatus
    actions: tuple[str, ...]


class StoreReader:
    """Read stores with shared preparation for one retrieval request.

    Metadata and selected byte checks can be reused only while the closed file
    inventory and filesystem witnesses remain unchanged. A reader is created at
    request composition and discarded afterwards. Publication during a request
    requires explicit invalidation before any further read.
    """

    def __init__(self) -> None:
        self._sealed: dict[tuple[StoreRoot, ProviderId], SealedStore] = {}
        self._witnesses: dict[tuple[StoreRoot, ProviderId], tuple[tuple[object, ...], ...]] = {}
        self._verified: dict[tuple[StoreRoot, ProviderId], set[PartitionIdentifier]] = {}

    def invalidate(self) -> None:
        """Discard preparation after an owned store publication."""
        self._sealed.clear()
        self._witnesses.clear()
        self._verified.clear()

    def _prepare(self, store: StoreRoot, provider_id: ProviderId, *, allow_pending: bool = False) -> SealedStore:
        from rivretrieve._internal.store import integrity

        key = (store, provider_id)
        witness = _inventory_witness(store)
        previous = self._sealed.get(key)
        if previous is not None and witness == self._witnesses[key]:
            return previous
        sealed = integrity.inspect_integrity(store, provider_id, allow_pending=allow_pending)
        if previous is not None and previous.generation_id != sealed.generation_id:
            integrity._fail(store, provider_id, "generation_changed")
        self._sealed[key] = sealed
        self._witnesses[key] = _inventory_witness(store)
        self._verified[key] = set()
        return sealed

    def evidence(self, store: StoreRoot, provider_id: ProviderId) -> CurrentEvidence:
        """Return the current evidence relations, keeping inventory support separate."""
        require_readable_store(store)
        sealed = self._prepare(store, provider_id)
        manifest = sealed.store.manifest
        return CurrentEvidence(
            manifest.outcomes, manifest.inventories, manifest.issues, manifest.source_calls, sealed.supporting_outcomes
        )

    def query(self, query: StoreQuery) -> StoreReadResult:
        from rivretrieve._internal.store.integrity import verify_inspected_files

        require_readable_store(query.store)
        sealed = self._prepare(query.store, query.provider_id)
        validated = sealed.store
        executed = _executed_query(query)
        candidates = {
            key: path
            for key, path in validated.partition_files.items()
            if str(key).split("/")[0].removeprefix("product=") in executed.products
            and int(str(key).split("/")[1].removeprefix("year=")) in executed.years
        }
        verified = self._verified[(query.store, query.provider_id)]
        verify_inspected_files(sealed, candidates.keys() - verified)
        verified.update(candidates)
        if candidates:
            physical_rows, optimized_plan = _scan(tuple(candidates.values()), executed)
        else:
            physical_rows = _empty_physical_rows(query.store, validated.manifest)
            optimized_plan = "EMPTY SCAN: no candidate partitions"
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
        state = inspect_lifecycle(Path(store))
        if state.committed_path is None:
            return StoreStatus(
                store=store,
                provider_id=provider_id,
                presence=StorePresence.INTERRUPTED
                if state.interrupted_paths or state.ownership is not Ownership.IDLE
                else StorePresence.ABSENT,
                interrupted_paths=state.interrupted_paths,
                cleanup_paths=state.cleanup_paths,
                ownership=state.ownership,
            )
        pending_seal = state.committed_path / ".integrity.pending"
        sealed = self._prepare(
            StoreRoot(state.committed_path),
            provider_id,
            allow_pending=pending_seal in (*state.interrupted_paths, *state.cleanup_paths),
        )
        return StoreStatus(
            store=store,
            provider_id=provider_id,
            presence=StorePresence.PRESENT,
            manifest=sealed.store.manifest,
            bytes_on_disk=sum(item.size for item in sealed.files.values())
            + (state.committed_path / "integrity.json").stat().st_size,
            generation_id=sealed.generation_id,
            committed_path=state.committed_path,
            interrupted_paths=state.interrupted_paths,
            cleanup_paths=state.cleanup_paths,
            ownership=state.ownership,
        )


def _empty_physical_rows(store: StoreRoot, manifest: StoreManifest | AccumulatedStoreManifest) -> pl.DataFrame:
    schema = pl.Schema(
        {
            "station_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "value": pl.Float64,
            "value_state": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
        }
    )
    if isinstance(manifest, StoreManifest):
        # These are the retained primitive representations admitted by the store
        # contract. The published metadata supplies them without opening a file
        # from an unrelated product/year merely to recover an empty schema.
        types = {
            "text": pl.String,
            "string": pl.String,
            "integer": pl.Int64,
            "double": pl.Float64,
            "float64": pl.Float64,
            "timestamp[us]": pl.Datetime("us"),
        }
        declarations = {column.name: column.type.lower() for column in manifest.source_schema.columns}
        for item in manifest.source_column_dispositions:
            if item.disposition is not Disposition.RETAINED or item.source_column in schema:
                continue
            native_type = types.get(declarations.get(item.source_column, ""))
            if native_type is None:
                _refuse(
                    StoreRefusalKind.MALFORMED,
                    store,
                    manifest.provider_id,
                    f"source_schema.native_type:{item.source_column}",
                )
            schema[item.source_column] = native_type
    schema["product"] = pl.String
    schema["year"] = pl.Int64
    return pl.DataFrame(schema=schema)


def _inventory_witness(store: StoreRoot) -> tuple[tuple[object, ...], ...]:
    # Include directories to detect added/deleted entries, and ctime to detect
    # edits whose mtime was restored. Never follow a newly introduced symlink.
    try:
        paths = (Path(store), *sorted(Path(store).rglob("*")))
        return tuple(
            (str(path), item.st_mode, item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            for path in paths
            for item in (path.lstat(),)
        )
    except OSError:
        # Inspection supplies the established malformed-store refusal.
        return ()


def require_readable_store(store: StoreRoot) -> None:
    """Refuse an unresolved transaction before a read or source acquisition."""
    state = inspect_lifecycle(Path(store))
    if state.interrupted_paths or state.ownership in (Ownership.ACTIVE, Ownership.AMBIGUOUS):
        raise StoreLifecycleError(
            f'Observation store "{store}" has interrupted or active work; inspect cache_status and use recover_cache'
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
        series_ids=query.series_ids,
        series_windows=query.series_windows,
        facts_ids=query.facts_ids,
    )


def _scan(paths: tuple[Path, ...], executed: ExecutedStoreQuery) -> tuple[pl.DataFrame, str]:
    scan = pl.scan_parquet(
        list(paths),
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
    if executed.series_ids:
        scan = scan.filter(pl.col("series_id").is_in(executed.series_ids))
    if executed.facts_ids:
        scan = scan.filter(pl.col("facts_id").is_in(executed.facts_ids))
    if executed.series_windows:
        scan = scan.filter(
            pl.any_horizontal(
                [
                    (pl.col("series_id") == series_id) & pl.col("time").is_between(window.start, window.end)
                    for series_id, window in executed.series_windows
                ]
            )
        )
    optimized_plan = scan.explain(optimized=True)
    return cast(pl.DataFrame, scan.collect()), optimized_plan


def _engine_rows(physical_rows: pl.DataFrame) -> Rows:
    if physical_rows.is_empty():
        return pl.DataFrame(schema=RowsSchema.polars_schema)
    return physical_rows.select(
        "station_id",
        pl.col("product").alias("product_id"),
        "time",
        "value",
        "time_zone",
        "series_id",
        "facts_id",
        "source_unit",
    )
