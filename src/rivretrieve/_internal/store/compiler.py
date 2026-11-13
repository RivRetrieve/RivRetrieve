"""compile_store_batches : StoreCompileRequest × ObservationBatchStream → StreamingCompileEvidence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import NewType, cast

import polars as pl
import pyarrow.parquet as pq

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    AnnotationSchema,
    ObservationAnnotationTable,
    SeriesAnnotationTable,
    advance_partition_key_ordinals,
    dump_annotation_schema,
    dump_series_annotations,
    encode_observation_table_for_parquet,
    filter_native_with_annotations,
    merge_series_tables,
    sort_native_by_station_with_annotations,
    validate_bundle_for_result,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    SeriesScope,
    SourceSeries,
    stable_id,
    validate_series_rows,
)
from rivretrieve._internal.store.integrity import seal_store
from rivretrieve._internal.store.lifecycle import StoreTransactionError
from rivretrieve._internal.store.validation import (
    Disposition,
    PublisherArtifact,
    SourceColumn,
    SourceColumnDisposition,
    SourceSchemaFingerprint,
    StoreRoot,
    ValidatedStore,
)

NativeStoreRows = NewType("NativeStoreRows", pl.DataFrame)
_PRODUCT_ID = re.compile(r"[^/=]+")
_ENGINE_INPUT_COLUMNS = (
    "product",
    "station_id",
    "time",
    "time_zone",
    "value",
    "value_state",
    "series_id",
    "facts_id",
    "source_unit",
)
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
    publisher_artifacts: tuple[PublisherArtifact, ...] = ()
    series: tuple[SourceSeries, ...] = ()
    annotations: AnnotationBundle = field(default_factory=AnnotationBundle.empty)

    def __post_init__(self) -> None:
        if self.publisher_artifacts and self.publisher_artifacts[0] != self.publisher_artifact:
            raise ValueError("singular publisher artifact must equal the first plural artifact")

    @property
    def all_publisher_artifacts(self) -> tuple[PublisherArtifact, ...]:
        return self.publisher_artifacts or (self.publisher_artifact,)

    @property
    def store(self) -> StoreRoot:
        return self.destination


def source_schema_fingerprint(columns: tuple[SourceColumn, ...]) -> SourceSchemaFingerprint:
    """Return the revision-10 fingerprint of an ordered publisher schema."""
    encoded_columns = [{"name": column.name, "type": column.type} for column in columns]
    canonical = json.dumps(encoded_columns, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return SourceSchemaFingerprint(f"sha256:{hashlib.sha256(canonical).hexdigest()}")


def _register_annotation_schemas(
    schemas_by_id: dict[str, AnnotationSchema],
    schemas: Iterable[AnnotationSchema],
) -> None:
    for schema in schemas:
        existing = schemas_by_id.get(schema.schema_id)
        if existing is not None and existing != schema:
            raise ValueError(f"Conflicting annotation schema definition for {schema.schema_id!r}")
        schemas_by_id[schema.schema_id] = schema


def _merge_compiled_series_annotations(
    tables: Iterable[SeriesAnnotationTable],
    definitions: Mapping[str, SourceSeries],
) -> dict[str, SeriesAnnotationTable]:
    table_list = [table for table in tables if table.row_count > 0]
    if not table_list:
        return {}
    try:
        merged = merge_series_tables(table_list, conflict="raise")
    except FatalContractError as error:
        raise ValueError(str(error)) from error
    if definitions:
        for table in merged.values():
            for sid in table.rows.get_column("series_id").to_list():
                if sid not in definitions:
                    raise ValueError(
                        f"Series annotation in {table.schema.schema_id!r} references unknown series {sid!r}"
                    )
    return merged


def _partition_pairs(
    frame: pl.DataFrame,
    obs_tables: Mapping[str, ObservationAnnotationTable],
) -> list[tuple[str, int]]:
    pairs: set[tuple[str, int]] = set()
    if not frame.is_empty():
        for prod, yr in frame.select(pl.col("product"), pl.col("time").dt.year().alias("year")).unique().iter_rows():
            pairs.add((cast(str, prod), cast(int, yr)))
    for table in obs_tables.values():
        if table.row_count > 0:
            for prod, yr in (
                table.rows.select(pl.col("product_id"), pl.col("time").dt.year().alias("year")).unique().iter_rows()
            ):
                product_str = cast(str, prod)
                if not _PRODUCT_ID.fullmatch(product_str):
                    raise ValueError(f"product id cannot form a revision-10 partition: {product_str!r}")
                pairs.add((product_str, cast(int, yr)))
    return sorted(pairs, key=lambda pair: (pair[0].encode("utf-8"), pair[1]))


def _partition_slices(
    frame: pl.DataFrame,
    bundle: AnnotationBundle,
    native_columns: tuple[str, ...],
    source_columns: tuple[SourceColumn, ...],
) -> list[tuple[str, int, str, pl.DataFrame, dict[str, ObservationAnnotationTable]]]:
    slices: list[tuple[str, int, str, pl.DataFrame, dict[str, ObservationAnnotationTable]]] = []
    has_obs_annotations = bool(bundle.observation_tables)
    for product, year in _partition_pairs(frame, bundle.observation_tables):
        identifier = f"product={product}/year={year:04d}"
        if not has_obs_annotations:
            selected = frame.filter((pl.col("product") == product) & (pl.col("time").dt.year() == year))
            selected_obs: dict[str, ObservationAnnotationTable] = {}
        else:
            flags = (
                frame.select(((pl.col("product") == product) & (pl.col("time").dt.year() == year)).alias("_k"))[
                    "_k"
                ].to_list()
                if not frame.is_empty()
                else []
            )
            kept_indices = [idx for idx, flag in enumerate(flags) if flag]
            selected, narrowed_bundle = filter_native_with_annotations(
                frame,
                bundle,
                kept_indices,
                unmeasured_expr=(pl.col("product_id") == product) & (pl.col("time").dt.year() == year),
            )
            if selected.is_empty() and not narrowed_bundle.observation_tables:
                continue
            if narrowed_bundle.observation_tables:
                selected, narrowed_bundle = sort_native_by_station_with_annotations(selected, narrowed_bundle)
            selected_obs = dict(narrowed_bundle.observation_tables)
        if selected.is_empty() and not selected_obs:
            continue
        physical = (
            _physical_partition(selected, native_columns, source_columns) if not selected.is_empty() else pl.DataFrame()
        )
        slices.append((product, year, identifier, physical, selected_obs))
    return slices


def compile_store(request: StoreCompileRequest, rows: NativeStoreRows | pl.DataFrame) -> ValidatedStore:
    """Materialize already-decoded native observations without interpreting them.

    This is deliberately only the network-free layout writer. Atomic replacement,
    artifact lifetime, source parsing, and certification belong to the caller.
    """
    frame = pl.DataFrame(rows)
    root = Path(request.destination)
    _check_request(request, root)
    native_columns = _check_rows(frame, request.source_columns, request.source_column_dispositions)
    validate_series_rows(frame.rename({"product": "product_id"}), request.series)
    validate_bundle_for_result(request.annotations, frame.rename({"product": "product_id"}), request.series)
    schemas_by_id: dict[str, AnnotationSchema] = {}
    _register_annotation_schemas(schemas_by_id, request.annotations.all_schemas())
    series_annotations = _merge_compiled_series_annotations(
        request.annotations.series_tables.values(),
        {item.series_id: item for item in request.series},
    )

    root.mkdir(parents=False)
    counts: dict[str, int] = {}
    ann_counts: dict[str, int] = {}
    try:
        for _product, _year, identifier, physical, selected_obs in _partition_slices(
            frame, request.annotations, native_columns, request.source_columns
        ):
            directory = root / identifier
            directory.mkdir(parents=True)
            if not physical.is_empty():
                _write_partition(physical, directory / "part-0.parquet")
                counts[identifier] = physical.height
            if selected_obs:
                row_ordinals = advance_partition_key_ordinals(physical)
                for schema_id in sorted(selected_obs):
                    ann_identifier = f"{identifier}/annotations={schema_id}"
                    ann_dir = directory / f"annotations={schema_id}"
                    ann_dir.mkdir(parents=True)
                    encoded = encode_observation_table_for_parquet(
                        selected_obs[schema_id],
                        physical,
                        row_ordinals=row_ordinals,
                    )
                    _write_partition(encoded, ann_dir / "rows.parquet")
                    ann_counts[ann_identifier] = encoded.height
        _write_manifest(
            root,
            request,
            counts,
            request.series,
            annotation_schemas=tuple(schemas_by_id[k] for k in sorted(schemas_by_id)),
            annotation_counts=ann_counts,
            series_annotations=series_annotations,
        )
        return seal_store(request.destination, request.provider_id).store
    except BaseException as original:
        # Removing a newly created destination does not alter existing evidence.
        _cleanup_failed_compile(root, original, ())
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
        raise ValueError("revision-10 stores cannot contain zero rows")
    if frame.columns[: len(_ENGINE_INPUT_COLUMNS)] != list(_ENGINE_INPUT_COLUMNS):
        raise ValueError(f"store row engine fields must be first and ordered as {_ENGINE_INPUT_COLUMNS!r}")

    expected_schema_names = [column.name for column in source_columns]
    collisions = [name for name in expected_schema_names if name in _ENGINE_INPUT_COLUMNS]
    if collisions:
        raise ValueError(f"source schema columns collide with engine fields: {collisions!r}")
    disposition_by_name = {item.source_column: item for item in dispositions}
    if len(disposition_by_name) != len(dispositions) or set(disposition_by_name) != set(expected_schema_names):
        raise ValueError("source-column dispositions must cover the declared source schema exactly once")
    retained = tuple(
        name for name in expected_schema_names if disposition_by_name[name].disposition is Disposition.RETAINED
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
        "series_id": pl.String,
        "facts_id": pl.String,
        "source_unit": pl.String,
    }
    wrong_types = {
        name: (schema[name], expected) for name, expected in expected_types.items() if schema[name] != expected
    }
    if wrong_types:
        raise TypeError(f"store row engine field types are not revision-10 types: {wrong_types!r}")

    required_non_null = (
        "product",
        "station_id",
        "time",
        "time_zone",
        "value_state",
        "series_id",
        "facts_id",
        "source_unit",
    )
    for name in required_non_null:
        if frame.get_column(name).null_count():
            raise ValueError(f"store rows contain null {name!r}")
    if frame.get_column("station_id").str.len_bytes().min() == 0:
        raise ValueError("store station identifiers must be non-empty")
    for product in frame.get_column("product").unique().to_list():
        if not _PRODUCT_ID.fullmatch(product):
            raise ValueError(f"product id cannot form a revision-10 partition: {product!r}")
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


def _physical_partition(
    frame: pl.DataFrame,
    native_columns: tuple[str, ...],
    source_columns: tuple[SourceColumn, ...],
) -> pl.DataFrame:
    source_types = {column.name: column.type.lower() for column in source_columns}
    physical_types = {
        "text": pl.String,
        "string": pl.String,
        "integer": pl.Int64,
        "double": pl.Float64,
        "float64": pl.Float64,
        "timestamp[us]": pl.Datetime("us"),
    }
    casts = [pl.col(name).cast(physical_types[source_types[name]]) for name in native_columns]
    return (
        frame.sort("station_id", maintain_order=True)
        .select(*_ENGINE_PHYSICAL_COLUMNS, *native_columns)
        .with_columns(pl.col("time").cast(pl.Datetime("us")), *casts)
    )


def _write_partition(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(path, compression="zstd", statistics=True)


def _write_manifest(
    root: Path,
    request: StoreCompileRequest,
    counts: dict[str, int],
    series: tuple[SourceSeries, ...],
    *,
    annotation_schemas: tuple[AnnotationSchema, ...] = (),
    annotation_counts: Mapping[str, int] | None = None,
    series_annotations: Mapping[str, SeriesAnnotationTable] | None = None,
) -> None:
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
    manifest: dict[str, object] = {
        "format_version": 10,
        "provider_id": str(request.provider_id),
        "compiler_version": request.compiler_version,
        "built_at": built_at,
        "source_vintage": request.source_vintage.isoformat(),
        **(
            {"publisher_artifact": {"url": request.publisher_artifact.url, "sha256": request.publisher_artifact.sha256}}
            if not request.publisher_artifacts
            else {
                "publisher_artifacts": [
                    {"url": artifact.url, "sha256": artifact.sha256} for artifact in request.publisher_artifacts
                ]
            }
        ),
        "source_schema": {
            "columns": columns,
            "fingerprint": source_schema_fingerprint(request.source_columns),
        },
        "source_column_dispositions": dispositions,
        "partition_row_counts": counts,
        "series": [item.model_dump(mode="json") for item in series],
        "inventories": [
            InventorySnapshot(
                snapshot_id=stable_id(
                    str(request.provider_id), *(str(item.sha256) for item in request.all_publisher_artifacts)
                ),
                scope=SeriesScope(
                    provider_ids=(str(request.provider_id),),
                    station_ids=tuple(sorted({item.station_id for item in series})),
                    product_ids=tuple(sorted({item.product_id for item in series})),
                ),
                members=tuple(item.series_id for item in series),
                member_facts=tuple((item.series_id, tuple(fact.facts_id for fact in item.facts)) for item in series),
                completeness=InventoryCompleteness.COMPLETE,
                access="compiled publisher artifact supported physical cells",
                origin="compiled",
                acquired_at=None,
                evidence=tuple(str(item.sha256) for item in request.all_publisher_artifacts),
            ).model_dump(mode="json")
        ],
        "outcomes": [],
        "issues": [],
        "source_calls": [],
    }
    if annotation_schemas:
        manifest["annotation_schemas"] = [dump_annotation_schema(schema) for schema in annotation_schemas]
    if annotation_counts:
        manifest["annotation_partition_row_counts"] = dict(annotation_counts)
    if series_annotations:
        manifest["series_annotations"] = dump_series_annotations(series_annotations)
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _cleanup_failed_compile(
    root: Path, original: BaseException, close_resources: Iterable[Callable[[], object]]
) -> None:
    errors: list[BaseException] = []
    for close in close_resources:
        try:
            close()
        except BaseException as error:
            errors.append(error)
    residue: tuple[Path, ...] = ()
    try:
        _remove_new_store(root)
    except BaseException as error:
        errors.append(error)
        residue = (root,)
    if errors:
        raise StoreTransactionError(original, cleanup_errors=tuple(errors), residue_paths=residue) from original


def _remove_new_store(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            path.rmdir()
    root.rmdir()


def source_unit_inventory_fingerprint(units: Iterable[tuple[str, int, int]]) -> str:
    """Hash exact ordered source-unit identities and their one-to-many cardinalities."""
    digest = hashlib.sha256()
    for name, publisher_records, expected_rows in units:
        encoded = json.dumps(
            [name, publisher_records, expected_rows], separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True, slots=True)
class NativeObservationBatch:
    """One bounded native row batch plus its complete source-unit reconciliation."""

    rows: NativeStoreRows | pl.DataFrame
    source_units: tuple[object, ...]
    source_contributions: tuple[object, ...]
    series: tuple[SourceSeries, ...] = ()
    annotations: AnnotationBundle = field(default_factory=AnnotationBundle.empty)


@dataclass(frozen=True, slots=True)
class ObservationBatchStream:
    """A declared source schema, independent expected-cell count, and bounded batches."""

    observed_source_columns: tuple[SourceColumn, ...]
    batches: Iterable[NativeObservationBatch]
    expected_publisher_records: int
    expected_emitted_rows: int
    expected_inventory_sha256: str
    series_annotations: tuple[SeriesAnnotationTable, ...] = ()

    def __post_init__(self) -> None:
        if type(self.expected_publisher_records) is not int or self.expected_publisher_records < 0:
            raise ValueError("expected publisher-record inventory count must be a non-negative integer")
        if type(self.expected_emitted_rows) is not int or self.expected_emitted_rows < 0:
            raise ValueError("expected emitted-row count must be a non-negative integer")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.expected_inventory_sha256):
            raise ValueError("expected source inventory fingerprint must be SHA-256")


@dataclass(frozen=True, slots=True)
class StreamingCompileEvidence:
    """Bounded writer evidence used for complete staged read-back certification."""

    partition_row_counts: Mapping[str, int]
    partition_row_group_rows: Mapping[str, tuple[int, ...]]
    annotation_partition_row_counts: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    annotation_partition_row_group_rows: Mapping[str, tuple[int, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )


def compile_store_batches(request: StoreCompileRequest, stream: ObservationBatchStream) -> StreamingCompileEvidence:
    """compile_store_batches : StoreCompileRequest × ObservationBatchStream → StreamingCompileEvidence."""
    root = Path(request.destination)
    _check_request(request, root)
    if stream.observed_source_columns != request.source_columns:
        raise ValueError("batch stream source schema differs from the declared source schema")
    if request.annotations.observation_tables:
        raise ValueError("streamed compilation expects observation annotations per batch")
    schemas_by_id: dict[str, AnnotationSchema] = {}
    _register_annotation_schemas(schemas_by_id, request.annotations.all_schemas())
    _register_annotation_schemas(schemas_by_id, (table.schema for table in stream.series_annotations))
    all_series_tables: list[SeriesAnnotationTable] = [
        *request.annotations.series_tables.values(),
        *stream.series_annotations,
    ]
    root.mkdir(parents=False)
    writers: dict[str, pq.ParquetWriter] = {}
    ann_writers: dict[str, pq.ParquetWriter] = {}
    counts: dict[str, int] = {}
    row_groups: dict[str, list[int]] = {}
    ann_counts: dict[str, int] = {}
    ann_row_groups: dict[str, list[int]] = {}
    last_station: dict[str, bytes] = {}
    last_ann_station: dict[str, bytes] = {}
    partition_key_counts: dict[str, dict[tuple[str, str, datetime, str], int]] = {}
    native_columns: tuple[str, ...] | None = None
    batch_schema: pl.Schema | None = None
    emitted_total = 0
    definitions = {item.series_id: item for item in request.series}
    last_partition_identifier: str | None = None
    last_partition_key: tuple[bytes, int] | None = None
    unit_database: sqlite3.Connection | None = None
    try:
        unit_database = sqlite3.connect(root / ".source-units.sqlite3")
        unit_database.execute(
            "CREATE TABLE source_units (name TEXT PRIMARY KEY, publisher_records INTEGER NOT NULL, expected_rows INTEGER NOT NULL, emitted_rows INTEGER NOT NULL) WITHOUT ROWID"
        )
        for batch_number, batch in enumerate(stream.batches, start=1):
            if not isinstance(batch, NativeObservationBatch):
                raise TypeError("observation batch iterator yielded an invalid batch")
            for definition in batch.series:
                if definition.series_id in definitions and definitions[definition.series_id] != definition:
                    raise ValueError("compiled batch contradicts an established source-series definition")
                definitions[definition.series_id] = definition
            frame = pl.DataFrame(batch.rows)
            frame_with_product_id = frame.rename({"product": "product_id"})
            validate_series_rows(frame_with_product_id, tuple(definitions.values()))
            validate_bundle_for_result(batch.annotations, frame_with_product_id, tuple(definitions.values()))
            _register_annotation_schemas(schemas_by_id, batch.annotations.all_schemas())
            all_series_tables.extend(batch.annotations.series_tables.values())
            if frame.is_empty():
                raise ValueError(f"observation batch {batch_number} is empty")
            batch_native = _check_rows(frame, request.source_columns, request.source_column_dispositions)
            if native_columns is None:
                native_columns = batch_native
                batch_schema = frame.schema
            elif batch_native != native_columns or frame.schema != batch_schema:
                raise ValueError("observation batch schema changed between batches")
            _record_source_units(unit_database, batch.source_units)
            _record_source_contributions(unit_database, batch.source_contributions)
            emitted_total += frame.height
            for product, year, identifier, physical, selected_obs in _partition_slices(
                frame, batch.annotations, batch_native, request.source_columns
            ):
                partition_key = (product.encode("utf-8"), year)
                if last_partition_key is not None and partition_key != last_partition_key:
                    if partition_key < last_partition_key:
                        raise ValueError(
                            f"streamed partition order is not strictly increasing: {identifier} after {last_partition_identifier}"
                        )
                    for active in writers.values():
                        active.close()
                    writers.clear()
                    for active in ann_writers.values():
                        active.close()
                    ann_writers.clear()
                last_partition_key = partition_key
                last_partition_identifier = identifier
                directory = root / identifier
                directory.mkdir(parents=True, exist_ok=True)
                if not physical.is_empty():
                    stations = physical.get_column("station_id").to_list()
                    first = stations[0].encode("utf-8")
                    if identifier in last_station and first < last_station[identifier]:
                        raise ValueError(f"streamed partition order regressed for {identifier}")
                    last_station[identifier] = stations[-1].encode("utf-8")
                    table = physical.to_arrow()
                    writer = writers.get(identifier)
                    if writer is None:
                        writer = pq.ParquetWriter(
                            directory / "part-0.parquet",
                            table.schema,
                            compression="zstd",
                            write_statistics=True,
                        )
                        writers[identifier] = writer
                    elif writer.schema != table.schema:
                        raise TypeError(f"streamed partition schema changed for {identifier}")
                    writer.write_table(table, row_group_size=table.num_rows)
                    counts[identifier] = counts.get(identifier, 0) + physical.height
                    row_groups.setdefault(identifier, []).append(physical.height)
                row_ordinals = (
                    advance_partition_key_ordinals(physical, partition_key_counts.setdefault(identifier, {}))
                    if not physical.is_empty()
                    else []
                )
                for schema_id in sorted(selected_obs):
                    ann_identifier = f"{identifier}/annotations={schema_id}"
                    encoded = encode_observation_table_for_parquet(
                        selected_obs[schema_id],
                        physical,
                        row_ordinals=row_ordinals,
                    )
                    ann_stations = encoded.get_column("station_id").to_list()
                    ann_first = ann_stations[0].encode("utf-8")
                    if ann_identifier in last_ann_station and ann_first < last_ann_station[ann_identifier]:
                        raise ValueError(f"streamed annotation partition order regressed for {ann_identifier}")
                    last_ann_station[ann_identifier] = ann_stations[-1].encode("utf-8")
                    ann_arrow = encoded.to_arrow()
                    ann_writer = ann_writers.get(ann_identifier)
                    if ann_writer is None:
                        ann_dir = directory / f"annotations={schema_id}"
                        ann_dir.mkdir(parents=True, exist_ok=True)
                        ann_writer = pq.ParquetWriter(
                            ann_dir / "rows.parquet",
                            ann_arrow.schema,
                            compression="zstd",
                            write_statistics=True,
                        )
                        ann_writers[ann_identifier] = ann_writer
                    elif ann_writer.schema != ann_arrow.schema:
                        raise TypeError(f"streamed annotation partition schema changed for {ann_identifier}")
                    ann_writer.write_table(ann_arrow, row_group_size=ann_arrow.num_rows)
                    ann_counts[ann_identifier] = ann_counts.get(ann_identifier, 0) + encoded.height
                    ann_row_groups.setdefault(ann_identifier, []).append(encoded.height)
        if emitted_total == 0:
            raise ValueError("revision-10 stores cannot contain zero rows")
        series_annotations = _merge_compiled_series_annotations(all_series_tables, definitions)
        unit_database.commit()
        publisher_records, expected_rows, contributed_rows, source_unit_total = unit_database.execute(
            "SELECT COALESCE(SUM(publisher_records),0), COALESCE(SUM(expected_rows),0), "
            "COALESCE(SUM(emitted_rows),0), COUNT(*) FROM source_units"
        ).fetchone()
        incomplete = unit_database.execute(
            "SELECT name FROM source_units WHERE expected_rows != emitted_rows ORDER BY name LIMIT 1"
        ).fetchone()
        actual_inventory_sha256 = source_unit_inventory_fingerprint(
            unit_database.execute("SELECT name, publisher_records, expected_rows FROM source_units ORDER BY name")
        )
        for writer in writers.values():
            writer.close()
        writers.clear()
        for ann_writer in ann_writers.values():
            ann_writer.close()
        ann_writers.clear()
        unit_database.close()
        unit_database = None
        (root / ".source-units.sqlite3").unlink()
        if sum(counts.values()) != emitted_total:
            raise ValueError("streamed partition counts differ from emitted source rows")
        if publisher_records != stream.expected_publisher_records:
            raise ValueError(
                "publisher-record inventory differs from independently scanned source: "
                f"expected={stream.expected_publisher_records}; actual={publisher_records}"
            )
        if expected_rows != stream.expected_emitted_rows:
            raise ValueError(
                "source-unit expected contributions differ from independently scanned source: "
                f"expected={stream.expected_emitted_rows}; actual={expected_rows}"
            )
        if actual_inventory_sha256 != stream.expected_inventory_sha256:
            raise ValueError(
                "source-unit identity inventory differs from independently scanned source: "
                f"expected={stream.expected_inventory_sha256}; actual={actual_inventory_sha256}"
            )
        if source_unit_total == 0 or incomplete is not None:
            raise ValueError(
                f"source unit did not emit every expected row: {None if incomplete is None else incomplete[0]}"
            )
        if contributed_rows != emitted_total:
            raise ValueError(
                "source-unit emitted contributions differ from materialized rows: "
                f"expected={contributed_rows}; actual={emitted_total}"
            )
        _write_manifest(
            root,
            request,
            counts,
            tuple(definitions.values()),
            annotation_schemas=tuple(schemas_by_id[k] for k in sorted(schemas_by_id)),
            annotation_counts=ann_counts,
            series_annotations=series_annotations,
        )
        seal_store(request.destination, request.provider_id)
        return StreamingCompileEvidence(
            MappingProxyType(dict(counts)),
            MappingProxyType({key: tuple(value) for key, value in row_groups.items()}),
            MappingProxyType(dict(ann_counts)),
            MappingProxyType({key: tuple(value) for key, value in ann_row_groups.items()}),
        )
    except BaseException as original:
        close_resources: list[Callable[[], object]] = [writer.close for writer in writers.values()]
        close_resources.extend(ann_writer.close for ann_writer in ann_writers.values())
        if unit_database is not None:
            close_resources.append(unit_database.close)
        _cleanup_failed_compile(root, original, close_resources)
        raise


def _record_source_units(database: sqlite3.Connection, units: tuple[object, ...]) -> None:
    for unit in units:
        name = getattr(unit, "source_unit", None)
        publisher_records = getattr(unit, "publisher_records", None)
        expected = getattr(unit, "expected_emitted_rows", None)
        if not isinstance(name, str) or not name:
            raise ValueError("source-unit inventory requires non-empty names")
        if any(type(value) is not int or value < 0 for value in (publisher_records, expected)):
            raise ValueError("source-unit inventory counts must be non-negative integers")
        try:
            database.execute("INSERT INTO source_units VALUES (?, ?, ?, 0)", (name, publisher_records, expected))
        except sqlite3.IntegrityError as error:
            raise ValueError(f"duplicate source unit across observation batches: {name}") from error


def _record_source_contributions(database: sqlite3.Connection, contributions: tuple[object, ...]) -> None:
    for contribution in contributions:
        name = getattr(contribution, "source_unit", None)
        emitted = getattr(contribution, "emitted_rows", None)
        if not isinstance(name, str) or not name or type(emitted) is not int or emitted < 0:
            raise ValueError("source-unit contributions require a name and non-negative emitted rows")
        cursor = database.execute(
            "UPDATE source_units SET emitted_rows = emitted_rows + ? WHERE name = ?", (emitted, name)
        )
        if cursor.rowcount != 1:
            raise ValueError(f"source contribution has no declared inventory unit: {name}")
