"""certify_store_batches : Artifact+ × StreamingSourceDecoder × StoreCompileRequest → ValidatedStore.

Certified compilation proves source closure and staged read-back equality before it
replaces the only surviving observation store and deletes the publisher artifact.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import polars as pl
import pyarrow.parquet as pq
from polars.testing import assert_frame_equal

from rivretrieve._internal.primitives import ProductId
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


# Compatibility with the descriptive name used in the layout discussion.
DecodedPublisherArtifact = NativeStoreMaterialization


class StoreCertificationError(RuntimeError):
    """The publisher artifact or staged store failed certification."""


class StorePostCommitCleanupError(StoreCertificationError):
    """The new store is authoritative but named non-secret cleanup residue remains."""


CertificationError = StoreCertificationError


SourceDecoder = Callable[[Path], NativeStoreMaterialization]
StreamingSourceDecoder = Callable[[Path | tuple[Path, ...]], ObservationBatchStream]
StoreWriter = Callable[[StoreCompileRequest, NativeStoreRows | pl.DataFrame], ValidatedStore]


def certify_store(
    request: StoreCompileRequest,
    publisher_artifact: Path,
    decode: SourceDecoder,
    *,
    writer: StoreWriter = compile_store,
    reader: StoreReader | None = None,
) -> ValidatedStore:
    """Compile, verify, atomically publish, then delete the publisher artifact.

    The decoder runs before a staging directory exists. It must report all observed
    source fields and every independently complete source member. Any pre-commit failure
    restores the previous store and publisher artifact. A typed post-commit cleanup
    failure keeps the validated new store authoritative and names remaining residue.
    """
    artifact = Path(publisher_artifact)
    destination = Path(request.destination)
    if request.publisher_artifacts:
        raise CertificationError("non-streaming certification accepts exactly one publisher artifact")
    _check_artifact(artifact, destination, request.publisher_artifact)
    decoded = decode(artifact)
    _check_source(decoded, request)

    stage = destination.with_name(f".{destination.name}.staging-{uuid4().hex}")
    backup = destination.with_name(f".{destination.name}.previous-{uuid4().hex}")
    staged_request = replace(request, destination=StoreRoot(stage))
    published = False
    try:
        writer(staged_request, decoded.rows)
        _verify_read_back(stage, request, pl.DataFrame(decoded.rows), reader or StoreReader())
        _publish(stage, destination, backup)
        published = True
        validated = validate_store(StoreRoot(destination), request.provider_id)
        artifact.unlink()
    except Exception:
        _safe_remove_tree(stage)
        if published:
            _restore_previous(destination, backup)
        raise

    _post_commit_cleanup(backup)
    return validated


# Spellings matching the writer keep provider bulk ports concise.
certify_compile = certify_store
certified_compile = certify_store


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
        raise CertificationError(f"publisher artifact checksum mismatch: expected {expected.sha256}; actual {actual}")


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
        raise CertificationError(
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


def _publish(stage: Path, destination: Path, backup: Path) -> None:
    had_previous = destination.exists()
    if had_previous:
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except Exception:
        if had_previous:
            os.replace(backup, destination)
        raise


def _restore_previous(destination: Path, backup: Path) -> None:
    if destination.exists():
        _remove_tree(destination)
    if backup.exists():
        os.replace(backup, destination)


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _safe_remove_tree(path: Path) -> None:
    # Cleanup must never hide the certification failure that protects the
    # publisher artifact and previous store.
    with suppress(OSError):
        _remove_tree(path)


def certify_store_batches(
    request: StoreCompileRequest,
    publisher_artifact: Path | tuple[Path, ...],
    decode: StreamingSourceDecoder,
) -> ValidatedStore:
    """certify_store_batches : Artifacts × StreamingDecoder × StoreCompileRequest → ValidatedStore."""
    artifacts = (
        tuple(Path(item) for item in publisher_artifact)
        if isinstance(publisher_artifact, tuple)
        else (Path(publisher_artifact),)
    )
    destination = Path(request.destination)
    expected_artifacts = request.all_publisher_artifacts
    if len(artifacts) != len(expected_artifacts):
        raise CertificationError("publisher artifact path and provenance counts differ")
    for artifact, expected in zip(artifacts, expected_artifacts, strict=True):
        _check_artifact(artifact, destination, expected)
    decoded = decode(artifacts if len(artifacts) > 1 else artifacts[0])
    if decoded.observed_source_columns != request.source_columns:
        raise CertificationError("observed source schema is not declaration-closed")

    stage = destination.with_name(f".{destination.name}.staging-{uuid4().hex}")
    backup = destination.with_name(f".{destination.name}.previous-{uuid4().hex}")
    staged_request = replace(request, destination=StoreRoot(stage))
    published = False
    quarantine: Path | None = None
    quarantine_copies: tuple[Path, ...] = ()
    try:
        evidence = compile_store_batches(staged_request, decoded)
        _verify_streamed_read_back(
            stage,
            request,
            evidence,
            decode(artifacts if len(artifacts) > 1 else artifacts[0]),
        )
        quarantine, quarantine_copies = _link_artifact_rollback_copies(destination, artifacts)
        _publish(stage, destination, backup)
        published = True
        validated = validate_store(StoreRoot(destination), request.provider_id)
        for artifact in artifacts:
            artifact.unlink()
    except Exception as original:
        restoration_errors: list[Exception] = []
        cleanup_errors: list[Exception] = []
        if quarantine is not None:
            try:
                _restore_linked_artifacts(artifacts, quarantine_copies)
            except Exception as error:
                restoration_errors.append(error)
        if published:
            try:
                _restore_previous(destination, backup)
            except Exception as error:
                restoration_errors.append(error)
        for residue in (stage, *((quarantine,) if quarantine is not None and not restoration_errors else ())):
            try:
                _remove_tree(residue)
            except OSError as error:
                cleanup_errors.append(error)
        if not restoration_errors and not cleanup_errors:
            raise
        details = [
            *(f"restoration {type(error).__name__}: {error}" for error in restoration_errors),
            *(f"cleanup {type(error).__name__}: {error}" for error in cleanup_errors),
        ]
        state = "incomplete" if restoration_errors else "complete with cleanup residue"
        raise StoreCertificationError(f"pre-commit rollback was {state}: {'; '.join(details)}") from original

    # Commit point: the validated destination is authoritative and every original
    # artifact has been unlinked while its quarantine links are still intact.
    _post_commit_cleanup(*(path for path in (quarantine, backup) if path is not None))
    return validated


def _post_commit_cleanup(*paths: Path) -> None:
    failures: list[str] = []
    for path in paths:
        try:
            _remove_tree(path)
        except OSError as error:
            failures.append(f"{path.name} ({type(error).__name__}: {error})")
    residues = [path.name for path in paths if path.exists()]
    if failures or residues:
        raise StorePostCommitCleanupError(
            "new store is authoritative; post-commit cleanup requires retry: "
            f"failures={failures!r}; residues={residues!r}"
        )


def _link_artifact_rollback_copies(destination: Path, artifacts: tuple[Path, ...]) -> tuple[Path, tuple[Path, ...]]:
    """Create same-filesystem rollback links before any downloaded name is removed."""
    quarantine = destination.parent / f".publisher-artifacts.rollback-{uuid4().hex}"
    quarantine.mkdir()
    copies: list[Path] = []
    try:
        for index, artifact in enumerate(artifacts):
            copy = quarantine / f"{index:06d}-{artifact.name}"
            os.link(artifact, copy)
            copies.append(copy)
    except Exception:
        _safe_remove_tree(quarantine)
        raise
    return quarantine, tuple(copies)


def _restore_linked_artifacts(artifacts: tuple[Path, ...], copies: tuple[Path, ...]) -> None:
    for artifact, copy in zip(artifacts, copies, strict=True):
        if not artifact.exists():
            os.link(copy, artifact)


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
