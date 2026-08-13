"""certify_compile : Artifact × SourceDecoder × StoreCompileRequest → ValidatedStore.

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
from uuid import uuid4

import polars as pl
from polars.testing import assert_frame_equal

from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.store.compiler import NativeStoreRows, StoreCompileRequest, compile_store
from rivretrieve._internal.store.reader import StoreQuery, StoreReader
from rivretrieve._internal.store.validation import SourceColumn, StoreRoot, ValidatedStore, validate_store


@dataclass(frozen=True, slots=True)
class SourceUnitCount:
    """Accepted publisher records and rows emitted for one complete source unit."""

    source_unit: str
    accepted_rows: int
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


CertificationError = StoreCertificationError


SourceDecoder = Callable[[Path], NativeStoreMaterialization]
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
    source fields and every independently complete source member. Any failure leaves
    the previous store and publisher artifact untouched.
    """
    artifact = Path(publisher_artifact)
    destination = Path(request.destination)
    _check_artifact(artifact, destination, request)
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

    _safe_remove_tree(backup)
    return validated


# Spellings matching the writer keep provider bulk ports concise.
certify_compile = certify_store
certified_compile = certify_store


def _check_artifact(artifact: Path, destination: Path, request: StoreCompileRequest) -> None:
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
    if actual != request.publisher_artifact.sha256:
        raise CertificationError(
            f"publisher artifact checksum mismatch: expected {request.publisher_artifact.sha256}; actual {actual}"
        )


def _check_source(decoded: NativeStoreMaterialization, request: StoreCompileRequest) -> None:
    if not decoded.source_units:
        raise StoreCertificationError("materialization must reconcile at least one complete source unit")
    names = [unit.source_unit for unit in decoded.source_units]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise StoreCertificationError("source-unit counts require unique non-empty names")
    if any(unit.accepted_rows < 0 or unit.emitted_rows < 0 for unit in decoded.source_units):
        raise StoreCertificationError("source-unit counts must be non-negative")
    mismatched = [unit.source_unit for unit in decoded.source_units if unit.accepted_rows != unit.emitted_rows]
    if mismatched:
        raise StoreCertificationError(f"source units did not compile completely: {mismatched!r}")
    emitted = sum(unit.emitted_rows for unit in decoded.source_units)
    if emitted != pl.DataFrame(decoded.rows).height:
        raise StoreCertificationError(
            f"source-unit emitted row count differs from materialized rows: expected={emitted}; "
            f"actual={pl.DataFrame(decoded.rows).height}"
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
