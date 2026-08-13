"""compile_store : StoreCompileRequest × NativeStoreRows → ValidatedStore."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import NewType

import polars as pl

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store.validation import (
    Disposition,
    PublisherArtifact,
    SourceColumn,
    SourceColumnDisposition,
    SourceSchemaFingerprint,
    StoreRoot,
    ValidatedStore,
    validate_store,
)

NativeStoreRows = NewType("NativeStoreRows", pl.DataFrame)
_PRODUCT_ID = re.compile(r"[^/=]+")
_ENGINE_INPUT_COLUMNS = ("product", "station_id", "time", "time_zone", "value", "value_state")
_ENGINE_PHYSICAL_COLUMNS = _ENGINE_INPUT_COLUMNS[1:]


class ValueState(StrEnum):
    PUBLISHED_NULL = "published_null"
    PUBLISHED_BLANK = "published_blank"
    PUBLISHED_VALUE = "published_value"


@dataclass(frozen=True, slots=True)
class StoreCompileRequest:
    destination: StoreRoot
    provider_id: ProviderId
    compiler_version: str
    built_at: datetime
    source_vintage: date
    publisher_artifact: PublisherArtifact
    source_columns: tuple[SourceColumn, ...]
    source_column_dispositions: tuple[SourceColumnDisposition, ...]

    @property
    def store(self) -> StoreRoot:
        return self.destination


# A second, descriptive name keeps call sites readable without creating another contract.
CompileStoreRequest = StoreCompileRequest


def source_schema_fingerprint(columns: tuple[SourceColumn, ...]) -> SourceSchemaFingerprint:
    """Return the revision-1 fingerprint of an ordered publisher schema."""
    encoded_columns = [{"name": column.name, "type": column.type} for column in columns]
    canonical = json.dumps(encoded_columns, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return SourceSchemaFingerprint(f"sha256:{hashlib.sha256(canonical).hexdigest()}")


def compile_store(request: StoreCompileRequest, rows: NativeStoreRows | pl.DataFrame) -> ValidatedStore:
    """Materialize already-decoded native observations without interpreting them.

    This is deliberately only the network-free layout writer. Atomic replacement,
    artifact lifetime, source parsing, and certification belong to the caller.
    """
    frame = pl.DataFrame(rows)
    root = Path(request.destination)
    _check_request(request, root)
    native_columns = _check_rows(frame, request.source_columns, request.source_column_dispositions)

    root.mkdir(parents=False)
    counts: dict[str, int] = {}
    try:
        products = frame.get_column("product").unique(maintain_order=True).to_list()
        years = frame.get_column("time").dt.year().unique(maintain_order=True).to_list()
        for product in sorted(products, key=lambda item: str(item).encode("utf-8")):
            for year in sorted(years):
                partition = frame.filter((pl.col("product") == product) & (pl.col("time").dt.year() == year))
                if partition.is_empty():
                    continue
                identifier = f"product={product}/year={year:04d}"
                directory = root / identifier
                directory.mkdir(parents=True)
                physical = _physical_partition(partition, native_columns)
                _write_partition(physical, directory / "part-0.parquet")
                counts[identifier] = physical.height
        _write_manifest(root, request, counts)
        return validate_store(request.destination, request.provider_id)
    except BaseException:
        # RR2 never publishes a plausible partial writer result. Removing this newly
        # created destination is local cleanup, not RR3's atomic replacement policy.
        _remove_new_store(root)
        raise


def _check_request(request: StoreCompileRequest, root: Path) -> None:
    if root.exists():
        raise FileExistsError(f'observation store destination already exists: "{root}"')
    if root.parent != Path("") and not root.parent.exists():
        raise FileNotFoundError(f'observation store parent does not exist: "{root.parent}"')
    offset = request.built_at.utcoffset()
    if request.built_at.tzinfo is None or offset is None:
        raise ValueError("store build time must be timezone-aware")
    if offset.total_seconds() != 0:
        raise ValueError("store build time must be UTC")
    if not request.source_columns:
        raise ValueError("source schema must contain at least one column")


def _check_rows(
    frame: pl.DataFrame,
    source_columns: tuple[SourceColumn, ...],
    dispositions: tuple[SourceColumnDisposition, ...],
) -> tuple[str, ...]:
    missing_engine = [name for name in _ENGINE_INPUT_COLUMNS if name not in frame.columns]
    if missing_engine:
        raise ValueError(f"store rows lack engine fields: {missing_engine!r}")
    if frame.is_empty():
        raise ValueError("revision-1 stores cannot contain zero rows")
    if frame.columns[: len(_ENGINE_INPUT_COLUMNS)] != list(_ENGINE_INPUT_COLUMNS):
        raise ValueError(f"store row engine fields must be first and ordered as {_ENGINE_INPUT_COLUMNS!r}")

    expected_schema_names = [column.name for column in source_columns]
    disposition_by_name = {item.source_column: item for item in dispositions}
    if len(disposition_by_name) != len(dispositions) or set(disposition_by_name) != set(expected_schema_names):
        raise ValueError("source-column dispositions must cover the declared source schema exactly once")
    retained = tuple(
        name
        for name in expected_schema_names
        if disposition_by_name[name].disposition is Disposition.RETAINED and name not in _ENGINE_PHYSICAL_COLUMNS
    )
    native_columns = tuple(frame.columns[len(_ENGINE_INPUT_COLUMNS) :])
    if native_columns != retained:
        raise ValueError(
            f"native row columns do not equal retained source columns: expected={retained!r}; actual={native_columns!r}"
        )

    schema = frame.schema
    expected_types = {
        "product": pl.String,
        "station_id": pl.String,
        "time": pl.Datetime("us"),
        "time_zone": pl.String,
        "value": pl.Float64,
        "value_state": pl.String,
    }
    wrong_types = {
        name: (schema[name], expected) for name, expected in expected_types.items() if schema[name] != expected
    }
    if wrong_types:
        raise TypeError(f"store row engine field types are not revision-1 types: {wrong_types!r}")

    required_non_null = ("product", "station_id", "time", "time_zone", "value_state")
    for name in required_non_null:
        if frame.get_column(name).null_count():
            raise ValueError(f"store rows contain null {name!r}")
    if frame.get_column("station_id").str.len_bytes().min() == 0:
        raise ValueError("store station identifiers must be non-empty")
    for product in frame.get_column("product").unique().to_list():
        if not _PRODUCT_ID.fullmatch(product):
            raise ValueError(f"product id cannot form a revision-1 partition: {product!r}")
    valid_states = {state.value for state in ValueState}
    states = set(frame.get_column("value_state").unique().to_list())
    if not states <= valid_states:
        raise ValueError(f"unknown value states: {sorted(states - valid_states)!r}")
    illegal = frame.filter(
        ((pl.col("value_state") == ValueState.PUBLISHED_VALUE.value) & pl.col("value").is_null())
        | ((pl.col("value_state") != ValueState.PUBLISHED_VALUE.value) & pl.col("value").is_not_null())
    )
    if not illegal.is_empty():
        raise ValueError("store rows contain illegal value/value_state combinations")
    return native_columns


def _physical_partition(frame: pl.DataFrame, native_columns: tuple[str, ...]) -> pl.DataFrame:
    return (
        frame.sort("station_id")
        .select(*_ENGINE_PHYSICAL_COLUMNS, *native_columns)
        .with_columns(pl.col("time").cast(pl.Datetime("us")))
    )


def _write_partition(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(path, compression="zstd", statistics=True)


def _write_manifest(root: Path, request: StoreCompileRequest, counts: dict[str, int]) -> None:
    columns = [{"name": column.name, "type": column.type} for column in request.source_columns]
    dispositions: list[dict[str, str]] = []
    for item in request.source_column_dispositions:
        record = {"source_column": item.source_column, "disposition": item.disposition.value}
        if item.reconstruction_rule is not None:
            record["reconstruction_rule"] = item.reconstruction_rule
        if item.rationale is not None:
            record["rationale"] = item.rationale
        dispositions.append(record)
    built_at = request.built_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    manifest = {
        "format_version": 1,
        "compiler_version": request.compiler_version,
        "built_at": built_at,
        "source_vintage": request.source_vintage.isoformat(),
        "publisher_artifact": {
            "url": request.publisher_artifact.url,
            "sha256": request.publisher_artifact.sha256,
        },
        "source_schema": {
            "columns": columns,
            "fingerprint": source_schema_fingerprint(request.source_columns),
        },
        "source_column_dispositions": dispositions,
        "partition_row_counts": counts,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _remove_new_store(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            path.rmdir()
    root.rmdir()
