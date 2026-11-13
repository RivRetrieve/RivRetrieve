"""certify_store_batches : Artifact+ × StreamingSourceDecoder × StoreCompileRequest → ValidatedStore.

Certified compilation proves source closure and staged read-back equality before it
replaces the only surviving observation store and deletes the publisher artifact.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import cast

import polars as pl
import pyarrow.parquet as pq
from polars.testing import assert_frame_equal

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    SeriesAnnotationTable,
    advance_partition_key_ordinals,
    encode_observation_table_for_parquet,
    merge_series_tables,
)
from rivretrieve._internal.source_series import SourceSeries
from rivretrieve._internal.store.compiler import (
    NativeStoreRows,
    ObservationBatchStream,
    StoreCompileRequest,
    StreamingCompileEvidence,
    _check_rows,
    _partition_slices,
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
    annotations: AnnotationBundle = field(default_factory=AnnotationBundle.empty)


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
    from rivretrieve._internal.store.lifecycle import StoreLifecycleError
    from rivretrieve._internal.store.remote import RemoteStoreRoot, RemoteStoreTransaction, remote_store_transaction

    if isinstance(destination, RemoteStoreRoot):
        if transaction is not None:
            if not isinstance(transaction, RemoteStoreTransaction) or transaction.root != destination:
                raise StoreLifecycleError(f"Transaction does not own store root: {destination}")
            if transaction.committed:
                raise ValueError("Cannot compile into an already committed transaction")
            transaction.workspace.mkdir(exist_ok=True)
            yield cast(StoreTransaction, transaction)
        else:
            with remote_store_transaction(destination) as acquired:
                acquired.workspace.mkdir(exist_ok=True)
                yield cast(StoreTransaction, acquired)
        return
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
        verify_files(sealed, tuple(sealed.store.all_partition_files))
        return sealed

    staged = cast(SealedStore, transaction.publish(validate)).store
    return replace(
        staged,
        root=StoreRoot(transaction.root),
        partition_files={
            identifier: transaction.root / path.relative_to(transaction.stage)
            for identifier, path in staged.partition_files.items()
        },
        annotation_partition_files={
            identifier: transaction.root / path.relative_to(transaction.stage)
            for identifier, path in staged.annotation_partition_files.items()
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
        if not decoded.annotations.is_empty:
            request = replace(request, annotations=decoded.annotations)
        _check_source(decoded, request)
        staged_request = replace(request, destination=StoreRoot(active.stage))
        writer(staged_request, decoded.rows)
        _verify_read_back(
            active.stage,
            request,
            pl.DataFrame(decoded.rows),
            reader or StoreReader(),
            expected_annotations=request.annotations,
        )
        active.register_cleanup((artifact,))
        validated = _publish_certified(active, request)
        artifact.unlink()
        return validated


def _check_artifact(artifact: Path, destination: Path, expected_artifact: object) -> None:
    from rivretrieve._internal.store.remote import RemoteStoreRoot

    if not artifact.is_file():
        raise FileNotFoundError(f'publisher artifact does not exist: "{artifact}"')
    resolved_artifact = artifact.resolve()
    if not isinstance(destination, RemoteStoreRoot):
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


def _assert_series_tables_equal(
    actual_tables: dict[str, SeriesAnnotationTable],
    expected_tables: dict[str, SeriesAnnotationTable],
    label: str,
) -> None:
    if set(actual_tables) != set(expected_tables):
        raise StoreCertificationError(
            f"{label} series annotation schemas differ: expected={sorted(expected_tables)!r}; actual={sorted(actual_tables)!r}"
        )
    for schema_id, expected_table in expected_tables.items():
        actual_table = actual_tables[schema_id]
        if actual_table.schema != expected_table.schema:
            raise StoreCertificationError(f"{label} series annotation schema differs for {schema_id!r}")
        try:
            assert_frame_equal(
                actual_table.rows,
                expected_table.rows,
                check_row_order=False,
                check_column_order=True,
                check_exact=True,
            )
        except AssertionError as error:
            raise StoreCertificationError(f"{label} series annotations differ for {schema_id!r}: {error}") from error


def _verify_read_back(
    stage: Path,
    request: StoreCompileRequest,
    expected: pl.DataFrame,
    reader: StoreReader,
    *,
    expected_annotations: AnnotationBundle | None = None,
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

    bundle = expected_annotations or AnnotationBundle.empty()
    actual_ann_counts = {str(key): value for key, value in validated.manifest.annotation_partition_row_counts.items()}
    expected_ann_counts: dict[str, int] = {}
    for schema_id, table in bundle.observation_tables.items():
        if table.row_count == 0:
            continue
        ann_with_year = table.rows.with_columns(pl.col("time").dt.year().alias("__year"))
        for key, partition in ann_with_year.partition_by(["product_id", "__year"], as_dict=True).items():
            product, year = key
            expected_ann_counts[f"product={product}/year={year:04d}/annotations={schema_id}"] = partition.height
    if actual_ann_counts != expected_ann_counts:
        raise StoreCertificationError(
            f"staged annotation partition counts differ: expected={expected_ann_counts!r}; actual={actual_ann_counts!r}"
        )

    manifest_series = {table.schema.schema_id: table for table in validated.manifest.series_annotations}
    expected_series = {schema_id: table for schema_id, table in bundle.series_tables.items() if table.row_count > 0}
    _assert_series_tables_equal(manifest_series, expected_series, "staged manifest")

    product_values = list(expected.get_column("product").unique().to_list())
    station_values = list(expected.get_column("station_id").unique().to_list())
    times = [expected.get_column("time").min(), expected.get_column("time").max()]
    for table in bundle.observation_tables.values():
        if table.row_count == 0:
            continue
        product_values.extend(table.rows.get_column("product_id").unique().to_list())
        station_values.extend(table.rows.get_column("station_id").unique().to_list())
        times.append(table.rows.get_column("time").min())
        times.append(table.rows.get_column("time").max())
    products = tuple(ProductId(value) for value in dict.fromkeys(product_values))
    stations = tuple(dict.fromkeys(station_values))
    datetimes = [value for value in times if isinstance(value, datetime)]
    if not datetimes:
        raise StoreCertificationError("materialized time bounds are not datetimes")
    start = min(datetimes)
    end = max(datetimes)
    query = StoreQuery(
        store=StoreRoot(stage),
        provider_id=request.provider_id,
        stations=stations,
        products=products,
        start=start,
        end=end,
    )
    read_result = reader.query(query)
    actual = read_result.physical_rows.select(expected.columns)
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

    expected_obs = {schema_id: table for schema_id, table in bundle.observation_tables.items() if table.row_count > 0}
    actual_obs = {
        schema_id: table
        for schema_id, table in read_result.annotations.observation_tables.items()
        if table.row_count > 0
    }
    if set(actual_obs) != set(expected_obs):
        raise StoreCertificationError(
            f"staged annotation schemas differ from read-back: expected={sorted(expected_obs)!r}; actual={sorted(actual_obs)!r}"
        )
    expected_obs_values = expected.get_column("value").to_list()
    actual_obs_values = read_result.rows.get_column("value").to_list()
    for schema_id, expected_table in expected_obs.items():
        actual_table = actual_obs[schema_id]
        if actual_table.schema != expected_table.schema:
            raise StoreCertificationError(f"staged annotation schema differs on read-back for {schema_id!r}")
        expected_linked = expected_table.rows.with_columns(
            pl.Series(
                "_obs_value",
                [None if idx is None else expected_obs_values[idx] for idx in expected_table.measurement_indices],
                dtype=pl.Float64,
            )
        )
        actual_linked = actual_table.rows.with_columns(
            pl.Series(
                "_obs_value",
                [None if idx is None else actual_obs_values[idx] for idx in actual_table.measurement_indices],
                dtype=pl.Float64,
            )
        )
        try:
            assert_frame_equal(
                actual_linked,
                expected_linked,
                check_row_order=False,
                check_column_order=True,
                check_exact=True,
            )
        except AssertionError as error:
            raise StoreCertificationError(
                f"staged store annotation read-back differs for {schema_id!r}: {error}"
            ) from error
    actual_series = {
        schema_id: table for schema_id, table in read_result.annotations.series_tables.items() if table.row_count > 0
    }
    _assert_series_tables_equal(actual_series, expected_series, "staged read-back")


def certify_store_batches(
    request: StoreCompileRequest,
    publisher_artifact: Path | tuple[Path, ...],
    decode: StreamingSourceDecoder,
    *,
    replay_decode: StreamingSourceDecoder | None = None,
    transaction: StoreTransaction | None = None,
) -> ValidatedStore:
    """Certify a complete streamed source snapshot through the shared lifecycle.

    ``replay_decode`` may bind different resource checks for the second decode.
    It must independently decode the same source paths; by default ``decode`` is
    used again. Candidate output is already on disk during replay.
    """
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
        replay = decode if replay_decode is None else replay_decode
        _verify_streamed_read_back(active.stage, request, evidence, replay(source_paths))
        active.register_cleanup(artifacts)
        validated = _publish_certified(active, request)
        for artifact in artifacts:
            artifact.unlink()
        return validated


def _check_exhausted_ann_row_groups(
    parquets: dict[str, pq.ParquetFile],
    indices: dict[str, int],
) -> None:
    for ann_id, pf in parquets.items():
        if indices.get(ann_id, 0) != pf.num_row_groups:
            raise StoreCertificationError(f"staged store contains unverified annotation row groups: {ann_id}")


def _verify_streamed_read_back(
    stage: Path,
    request: StoreCompileRequest,
    evidence: StreamingCompileEvidence,
    expected_stream: ObservationBatchStream,
) -> None:
    """Compare every staged physical row with a second bounded source decode."""
    # Compilation already validated all semantics. Verify the sealed bytes before
    # replay rather than repeating that full decode. Publication verifies again.
    sealed = inspect_integrity(StoreRoot(stage), request.provider_id)
    verify_files(sealed, tuple(sealed.store.all_partition_files))
    actual_counts = {str(key): value for key, value in sealed.store.manifest.partition_row_counts.items()}
    if actual_counts != dict(evidence.partition_row_counts):
        raise StoreCertificationError(
            f"staged partition counts differ from streamed rows: expected={dict(evidence.partition_row_counts)!r}; "
            f"actual={actual_counts!r}"
        )
    actual_ann_counts = {
        str(key): value for key, value in sealed.store.manifest.annotation_partition_row_counts.items()
    }
    if actual_ann_counts != dict(evidence.annotation_partition_row_counts):
        raise StoreCertificationError(
            "staged annotation partition counts differ from streamed rows: "
            f"expected={dict(evidence.annotation_partition_row_counts)!r}; actual={actual_ann_counts!r}"
        )
    if expected_stream.observed_source_columns != request.source_columns:
        raise StoreCertificationError("replayed source schema differs from the declared source schema")
    current_identifier: str | None = None
    current_parquet: pq.ParquetFile | None = None
    current_row_group = 0
    current_ann_parquets: dict[str, pq.ParquetFile] = {}
    current_ann_row_groups: dict[str, int] = {}
    expected_counts: dict[str, int] = {}
    expected_ann_counts: dict[str, int] = {}
    partition_key_counts: dict[str, dict[tuple[str, str, datetime, str], int]] = {}
    replayed_series_tables: list[SeriesAnnotationTable] = [
        *request.annotations.series_tables.values(),
        *expected_stream.series_annotations,
    ]
    try:
        for batch in expected_stream.batches:
            frame = pl.DataFrame(batch.rows)
            native_columns = _check_rows(
                frame,
                request.source_columns,
                request.source_column_dispositions,
            )
            replayed_series_tables.extend(batch.annotations.series_tables.values())
            for _product, _year, identifier, expected, selected_obs in _partition_slices(
                frame, batch.annotations, native_columns, request.source_columns
            ):
                if identifier != current_identifier:
                    if (
                        current_identifier is not None
                        and current_parquet is not None
                        and current_row_group != current_parquet.num_row_groups
                    ):
                        raise StoreCertificationError(
                            f"staged store contains unverified row groups: {current_identifier}"
                        )
                    _check_exhausted_ann_row_groups(current_ann_parquets, current_ann_row_groups)
                    current_ann_parquets.clear()
                    current_ann_row_groups.clear()
                    current_identifier = identifier
                    part_path = stage / identifier / "part-0.parquet"
                    current_parquet = pq.ParquetFile(part_path) if part_path.exists() else None
                    current_row_group = 0
                if not expected.is_empty():
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
                row_ordinals = (
                    advance_partition_key_ordinals(expected, partition_key_counts.setdefault(identifier, {}))
                    if not expected.is_empty()
                    else []
                )
                for schema_id in sorted(selected_obs):
                    ann_identifier = f"{identifier}/annotations={schema_id}"
                    expected_ann = encode_observation_table_for_parquet(
                        selected_obs[schema_id],
                        expected,
                        row_ordinals=row_ordinals,
                    )
                    ann_pf = current_ann_parquets.get(ann_identifier)
                    if ann_pf is None:
                        ann_pf = pq.ParquetFile(stage / identifier / f"annotations={schema_id}" / "rows.parquet")
                        current_ann_parquets[ann_identifier] = ann_pf
                        current_ann_row_groups[ann_identifier] = 0
                    ann_idx = current_ann_row_groups[ann_identifier]
                    if ann_idx >= ann_pf.num_row_groups:
                        raise StoreCertificationError(
                            f"staged store lacks streamed annotation row group: {ann_identifier}"
                        )
                    actual_ann = cast(pl.DataFrame, pl.from_arrow(ann_pf.read_row_group(ann_idx)))
                    try:
                        assert_frame_equal(
                            actual_ann, expected_ann, check_row_order=True, check_column_order=True, check_exact=True
                        )
                    except AssertionError as error:
                        raise StoreCertificationError(
                            f"staged store annotation read-back differs: {ann_identifier} row_group={ann_idx}: {error}"
                        ) from error
                    current_ann_row_groups[ann_identifier] = ann_idx + 1
                    expected_ann_counts[ann_identifier] = (
                        expected_ann_counts.get(ann_identifier, 0) + expected_ann.height
                    )
    except StoreCertificationError:
        raise
    except Exception as error:
        raise StoreCertificationError(f"second source decode failed during staged read-back: {error}") from error
    if expected_counts != dict(evidence.partition_row_counts):
        raise StoreCertificationError(
            f"second source decode counts differ: expected={dict(evidence.partition_row_counts)!r}; actual={expected_counts!r}"
        )
    if expected_ann_counts != dict(evidence.annotation_partition_row_counts):
        raise StoreCertificationError(
            f"second source decode annotation counts differ: expected={dict(evidence.annotation_partition_row_counts)!r}; actual={expected_ann_counts!r}"
        )
    if (
        current_identifier is not None
        and current_parquet is not None
        and current_row_group != current_parquet.num_row_groups
    ):
        raise StoreCertificationError(f"staged store contains unverified row groups: {current_identifier}")
    _check_exhausted_ann_row_groups(current_ann_parquets, current_ann_row_groups)
    if tuple(expected_counts) != tuple(evidence.partition_row_group_rows):
        raise StoreCertificationError("second source decode did not traverse partitions in manifest order")
    if tuple(expected_ann_counts) != tuple(evidence.annotation_partition_row_group_rows):
        raise StoreCertificationError("second source decode did not traverse annotation partitions in manifest order")
    try:
        merged_series = merge_series_tables(replayed_series_tables, conflict="raise")
    except FatalContractError as error:
        raise StoreCertificationError(f"second source decode series annotations failed: {error}") from error
    manifest_series = {table.schema.schema_id: table for table in sealed.store.manifest.series_annotations}
    _assert_series_tables_equal(manifest_series, merged_series, "second source decode")
