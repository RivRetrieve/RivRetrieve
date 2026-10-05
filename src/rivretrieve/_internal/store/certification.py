"""certify_store_batches : Artifact+ × StreamingSourceDecoder × StoreCompileRequest → ValidatedStore.

Certified compilation proves source closure and staged read-back equality before it
replaces the only surviving observation store and deletes the publisher artifact.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import cast

import polars as pl
import pyarrow.parquet as pq
from polars.testing import assert_frame_equal

from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.source_series import SourceSeries
from rivretrieve._internal.store.compiler import (
    NativeStoreRows,
    ObservationBatchStream,
    StoreCompileRequest,
    StreamingCompileEvidence,
    _check_rows,
    _physical_partition,
    compile_store,
    compile_store_batches,
)
from rivretrieve._internal.store.integrity import SealedStore, inspect_integrity, verify_files
from rivretrieve._internal.store.lifecycle import (
    StorePostCommitCleanupError as StorePostCommitCleanupError,
)
from rivretrieve._internal.store.lifecycle import (
    StoreTransaction,
    store_transaction,
)
from rivretrieve._internal.store.reader import StoreQuery, StoreReader
from rivretrieve._internal.store.validation import SourceColumn, StoreRoot, ValidatedStore, validate_store


@dataclass(frozen=True, slots=True)
class SourceUnitCount:
    """Inventory facts for one unique publisher-record range."""

    source_unit: str
    publisher_records: int
    expected_emitted_rows: int


@dataclass(frozen=True, slots=True)
class SourceUnitContribution:
    """Rows actually emitted for one previously declared source unit."""

    source_unit: str
    emitted_rows: int


@dataclass(frozen=True, slots=True)
class NativeStoreMaterialization:
    """Decoded rows plus facts that cannot be recovered after compilation."""

    rows: NativeStoreRows | pl.DataFrame
    observed_source_columns: tuple[SourceColumn, ...]
    source_units: tuple[SourceUnitCount, ...]
    series: tuple[SourceSeries, ...] = ()


class StoreCertificationError(RuntimeError):
    """The publisher artifact or staged store failed certification."""


SourceDecoder = Callable[[Path], NativeStoreMaterialization]
StreamingSourceDecoder = Callable[[Path | tuple[Path, ...]], ObservationBatchStream]
StoreWriter = Callable[[StoreCompileRequest, NativeStoreRows | pl.DataFrame], ValidatedStore]


@contextmanager
def compilation_transaction(
    destination: StoreRoot, transaction: StoreTransaction | None = None
) -> Iterator[StoreTransaction]:
    """Reuse explicit ownership or open one publication transaction."""
    if transaction is not None:
        transaction.lease.check(Path(destination))
        if transaction.committed:
            raise ValueError("Cannot compile into an already committed transaction")
        transaction.workspace.mkdir(exist_ok=True)
        yield transaction
    else:
        with store_transaction(Path(destination)) as acquired:
            acquired.workspace.mkdir(exist_ok=True)
            yield acquired


def _publish_certified(transaction: StoreTransaction, request: StoreCompileRequest) -> ValidatedStore:
    def validate(stage: Path) -> SealedStore:
        sealed = inspect_integrity(StoreRoot(stage), request.provider_id)
        verify_files(sealed, tuple(sealed.store.partition_files))
        return sealed

    staged = cast(SealedStore, transaction.publish(validate)).store
    return replace(
        staged,
        root=StoreRoot(transaction.root),
        partition_files={
            identifier: transaction.root / path.relative_to(transaction.stage)
            for identifier, path in staged.partition_files.items()
        },
    )


def certify_store(
    request: StoreCompileRequest,
    publisher_artifact: Path,
    decode: SourceDecoder,
    *,
    writer: StoreWriter = compile_store,
    reader: StoreReader | None = None,
    transaction: StoreTransaction | None = None,
) -> ValidatedStore:
    """Certify exact source equality, publish, then delete the supplied artifact.

    Pre-commit failures leave the artifact and previous store intact. Artifact
    deletion and old-generation cleanup failures after publication report the new
    authoritative store and remaining paths through StorePostCommitCleanupError.
    """
    with compilation_transaction(request.destination, transaction) as active:
        artifact = Path(publisher_artifact)
        if request.publisher_artifacts:
            raise StoreCertificationError("non-streaming certification accepts exactly one publisher artifact")
        _check_artifact(artifact, active.root, request.publisher_artifact)
        decoded = decode(artifact)
        if decoded.series:
            request = replace(request, series=decoded.series)
        _check_source(decoded, request)
        staged_request = replace(request, destination=StoreRoot(active.stage))
        writer(staged_request, decoded.rows)
        _verify_read_back(active.stage, request, pl.DataFrame(decoded.rows), reader or StoreReader())
        active.register_cleanup((artifact,))
        validated = _publish_certified(active, request)
        artifact.unlink()
        return validated


def _check_artifact(artifact: Path, destination: Path, expected_artifact: object) -> None:
    if not artifact.is_file():
        raise FileNotFoundError(f'publisher artifact does not exist: "{artifact}"')
    resolved_artifact = artifact.resolve()
    resolved_destination = destination.resolve()
    if resolved_artifact == resolved_destination or resolved_destination in resolved_artifact.parents:
        raise ValueError("publisher artifact must be outside the observation store")
    digest = hashlib.sha256()
    with artifact.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = f"sha256:{digest.hexdigest()}"
    expected = expected_artifact
    if not hasattr(expected, "sha256"):
        raise TypeError("expected publisher artifact provenance is malformed")
    if actual != expected.sha256:
        raise StoreCertificationError(
            f"publisher artifact checksum mismatch: expected {expected.sha256}; actual {actual}"
        )


def _check_source(decoded: NativeStoreMaterialization, request: StoreCompileRequest) -> None:
    if not decoded.source_units:
        raise StoreCertificationError("materialization must reconcile at least one complete source unit")
    names = [unit.source_unit for unit in decoded.source_units]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise StoreCertificationError("source-unit counts require unique non-empty names")
    if any(unit.publisher_records < 0 or unit.expected_emitted_rows < 0 for unit in decoded.source_units):
        raise StoreCertificationError("source-unit counts must be non-negative")
    emitted = sum(unit.expected_emitted_rows for unit in decoded.source_units)
    if emitted != pl.DataFrame(decoded.rows).height:
        raise StoreCertificationError(
            f"source-unit emitted rows differ from materialization: expected={emitted}; actual={pl.DataFrame(decoded.rows).height}"
        )
    declared = request.source_columns
    observed = decoded.observed_source_columns
    if observed != declared:
        declared_by_name = {column.name: column.type for column in declared}
        observed_by_name = {column.name: column.type for column in observed}
        undeclared = [name for name in observed_by_name if name not in declared_by_name]
        absent = [name for name in declared_by_name if name not in observed_by_name]
        retyped = [
            name
            for name in observed_by_name.keys() & declared_by_name.keys()
            if observed_by_name[name] != declared_by_name[name]
        ]
        raise StoreCertificationError(
            "observed source schema is not declaration-closed: "
            f"undeclared={undeclared!r}; absent={absent!r}; retyped={retyped!r}; "
            f"declared_order={[column.name for column in declared]!r}; "
            f"observed_order={[column.name for column in observed]!r}"
        )


def _verify_read_back(
    stage: Path,
    request: StoreCompileRequest,
    expected: pl.DataFrame,
    reader: StoreReader,
) -> None:
    validated = validate_store(StoreRoot(stage), request.provider_id)
    actual_counts = dict(validated.manifest.partition_row_counts)
    expected_counts: dict[str, int] = {}
    with_year = expected.with_columns(pl.col("time").dt.year().alias("__year"))
    for key, partition in with_year.partition_by(["product", "__year"], as_dict=True).items():
        product, year = key
        expected_counts[f"product={product}/year={year:04d}"] = partition.height
    if actual_counts != expected_counts:
        raise StoreCertificationError(
            f"staged partition counts differ from decoded rows: expected={expected_counts!r}; actual={actual_counts!r}"
        )

    products = tuple(ProductId(value) for value in expected.get_column("product").unique().to_list())
    stations = tuple(expected.get_column("station_id").unique().to_list())
    start = expected.get_column("time").min()
    end = expected.get_column("time").max()
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise StoreCertificationError("materialized time bounds are not datetimes")
    query = StoreQuery(
        store=StoreRoot(stage),
        provider_id=request.provider_id,
        stations=stations,
        products=products,
        start=start,
        end=end,
    )
    actual = reader.query(query).physical_rows.select(expected.columns)
    try:
        assert_frame_equal(
            actual,
            expected,
            check_row_order=False,
            check_column_order=True,
            check_exact=True,
        )
    except AssertionError as error:
        raise StoreCertificationError(f"staged store read-back differs from decoded rows: {error}") from error


def certify_store_batches(
    request: StoreCompileRequest,
    publisher_artifact: Path | tuple[Path, ...],
    decode: StreamingSourceDecoder,
    *,
    transaction: StoreTransaction | None = None,
) -> ValidatedStore:
    """Certify a complete streamed source snapshot through the shared lifecycle."""
    with compilation_transaction(request.destination, transaction) as active:
        artifacts = (
            tuple(Path(item) for item in publisher_artifact)
            if isinstance(publisher_artifact, tuple)
            else (Path(publisher_artifact),)
        )
        expected_artifacts = request.all_publisher_artifacts
        if len(artifacts) != len(expected_artifacts):
            raise StoreCertificationError("publisher artifact path and provenance counts differ")
        for artifact, expected in zip(artifacts, expected_artifacts, strict=True):
            _check_artifact(artifact, active.root, expected)
        source_paths = artifacts if len(artifacts) > 1 else artifacts[0]
        decoded = decode(source_paths)
        if decoded.observed_source_columns != request.source_columns:
            raise StoreCertificationError("observed source schema is not declaration-closed")
        staged_request = replace(request, destination=StoreRoot(active.stage))
        evidence = compile_store_batches(staged_request, decoded)
        _verify_streamed_read_back(active.stage, request, evidence, decode(source_paths))
        active.register_cleanup(artifacts)
        validated = _publish_certified(active, request)
        for artifact in artifacts:
            artifact.unlink()
        return validated


def _verify_streamed_read_back(
    stage: Path,
    request: StoreCompileRequest,
    evidence: StreamingCompileEvidence,
    expected_stream: ObservationBatchStream,
) -> None:
    """Compare every staged physical row with a second bounded source decode."""
    validated = validate_store(StoreRoot(stage), request.provider_id)
    actual_counts = {str(key): value for key, value in validated.manifest.partition_row_counts.items()}
    if actual_counts != dict(evidence.partition_row_counts):
        raise StoreCertificationError(
            f"staged partition counts differ from streamed rows: expected={dict(evidence.partition_row_counts)!r}; "
            f"actual={actual_counts!r}"
        )
    if expected_stream.observed_source_columns != request.source_columns:
        raise StoreCertificationError("replayed source schema differs from the declared source schema")
    current_identifier: str | None = None
    current_parquet: pq.ParquetFile | None = None
    current_row_group = 0
    expected_counts: dict[str, int] = {}
    try:
        for batch in expected_stream.batches:
            frame = pl.DataFrame(batch.rows)
            native_columns = _check_rows(
                frame,
                request.source_columns,
                request.source_column_dispositions,
            )
            years = frame.get_column("time").dt.year().unique().to_list()
            products = frame.get_column("product").unique().to_list()
            for product in sorted(products, key=lambda value: str(value).encode("utf-8")):
                for year in sorted(years):
                    selected = frame.filter((pl.col("product") == product) & (pl.col("time").dt.year() == year))
                    if selected.is_empty():
                        continue
                    identifier = f"product={product}/year={year:04d}"
                    expected = _physical_partition(selected, native_columns, request.source_columns)
                    if identifier != current_identifier:
                        if (
                            current_identifier is not None
                            and current_parquet is not None
                            and current_row_group != current_parquet.num_row_groups
                        ):
                            raise StoreCertificationError(
                                f"staged store contains unverified row groups: {current_identifier}"
                            )
                        current_identifier = identifier
                        current_parquet = pq.ParquetFile(stage / identifier / "part-0.parquet")
                        current_row_group = 0
                    if current_parquet is None or current_row_group >= current_parquet.num_row_groups:
                        raise StoreCertificationError(f"staged store lacks streamed row group: {identifier}")
                    actual = cast(
                        pl.DataFrame,
                        pl.from_arrow(current_parquet.read_row_group(current_row_group)),
                    )
                    index = current_row_group
                    try:
                        assert_frame_equal(
                            actual, expected, check_row_order=True, check_column_order=True, check_exact=True
                        )
                    except AssertionError as error:
                        raise StoreCertificationError(
                            f"staged store read-back differs from streamed rows: {identifier} row_group={index}: {error}"
                        ) from error
                    current_row_group += 1
                    expected_counts[identifier] = expected_counts.get(identifier, 0) + expected.height
    except StoreCertificationError:
        raise
    except Exception as error:
        raise StoreCertificationError(f"second source decode failed during staged read-back: {error}") from error
    if expected_counts != dict(evidence.partition_row_counts):
        raise StoreCertificationError(
            f"second source decode counts differ: expected={dict(evidence.partition_row_counts)!r}; actual={expected_counts!r}"
        )
    if (
        current_identifier is not None
        and current_parquet is not None
        and current_row_group != current_parquet.num_row_groups
    ):
        raise StoreCertificationError(f"staged store contains unverified row groups: {current_identifier}")
    if tuple(expected_counts) != tuple(evidence.partition_row_group_rows):
        raise StoreCertificationError("second source decode did not traverse partitions in manifest order")
