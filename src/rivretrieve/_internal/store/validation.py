"""validate_store : StoreRoot × ProviderId → ValidatedStore ⊎ StoreRefusal."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, NewType, NoReturn, cast

import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.publication_identity import publication_identity_fields
from rivretrieve._internal.source_series import (
    InventorySnapshot,
    OutcomeStatus,
    RetrievalOutcome,
    SourceSeries,
    admission,
)
from rivretrieve._internal.store.provenance import decode_source_call
from rivretrieve._internal.time_axis import TimeAxis

StoreRoot = NewType("StoreRoot", Path)
PartitionIdentifier = NewType("PartitionIdentifier", str)
ArtifactChecksum = NewType("ArtifactChecksum", str)
SourceSchemaFingerprint = NewType("SourceSchemaFingerprint", str)


class Disposition(StrEnum):
    RETAINED = "retained"
    RECONSTRUCTIBLE = "reconstructible"
    DELIBERATELY_DISCARDED = "deliberately_discarded"


@dataclass(frozen=True, slots=True)
class SourceColumn:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class SourceSchema:
    columns: tuple[SourceColumn, ...]
    fingerprint: SourceSchemaFingerprint


@dataclass(frozen=True, slots=True)
class SourceColumnDisposition:
    source_column: str
    disposition: Disposition
    reconstruction_rule: str | None
    rationale: str | None


@dataclass(frozen=True, slots=True)
class PublisherArtifact:
    url: str
    sha256: ArtifactChecksum


@dataclass(frozen=True, slots=True)
class StoreManifest:
    """Manifest of a compiled bulk store.

    Attributes
    ----------
    format_version : int
        Compiled layout revision, 5.
    provider_id : ProviderId
        Provider whose native observations are stored.
    compiler_version : str
        Software version used to compile the store.
    built_at : datetime
        UTC build instant.
    source_vintage : datetime.date
        Identifies the source publication state the store was compiled from.
        Its derivation depends on the provider: for example, the date of a
        dated publisher release, or the last date covered by the latest
        published period. It is not a freshness verdict. ``download`` passes
        it to the provider, which can refuse a new download whose published
        history would end earlier.
    publisher_artifact : PublisherArtifact
        First publisher artifact identity, retained for single-artifact access.
    publisher_artifacts : tuple[PublisherArtifact, ...]
        Ordered artifact URLs and SHA-256 checksums. These identify deleted inputs.
    source_schema : SourceSchema
        Native column names, types and schema fingerprint.
    source_column_dispositions : tuple[SourceColumnDisposition, ...]
        Retained, reconstructible or deliberately discarded fields and rationale.
    partition_row_counts : Mapping[PartitionIdentifier, int]
        Exact physical row counts keyed by product/year.
    """

    format_version: Literal[5]
    provider_id: ProviderId
    compiler_version: str
    built_at: datetime
    source_vintage: date
    publisher_artifact: PublisherArtifact
    publisher_artifacts: tuple[PublisherArtifact, ...]
    source_schema: SourceSchema
    source_column_dispositions: tuple[SourceColumnDisposition, ...]
    partition_row_counts: Mapping[PartitionIdentifier, int]
    series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    outcomes: tuple[RetrievalOutcome, ...] = ()
    issues: tuple[Issue, ...] = ()
    source_calls: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "partition_row_counts", MappingProxyType(dict(self.partition_row_counts)))


@dataclass(frozen=True, slots=True)
class AccumulatedStoreManifest:
    """Manifest of accumulated live parse output.

    Attributes
    ----------
    format_version : int
        Accumulated layout revision, 8.
    provider_id : ProviderId
        Provider whose native observations are stored.
    built_at : datetime
        UTC store write instant.
    coverage : tuple[CoverageInterval, ...]
        Successfully retrieved series intervals and source retrieval instants.
    partition_row_counts : Mapping[PartitionIdentifier, int]
        Exact physical row counts keyed by product/year.
    """

    format_version: Literal[8]
    provider_id: ProviderId
    built_at: datetime
    coverage: tuple[CoverageInterval, ...]
    partition_row_counts: Mapping[PartitionIdentifier, int]
    series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    outcomes: tuple[RetrievalOutcome, ...] = ()
    issues: tuple[Issue, ...] = ()
    source_calls: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "partition_row_counts", MappingProxyType(dict(self.partition_row_counts)))


@dataclass(frozen=True, slots=True)
class ValidatedStore:
    """A store whose manifest and physical partitions passed validation.

    Attributes
    ----------
    root : StoreRoot
        Resolved local store path.
    manifest : StoreManifest or AccumulatedStoreManifest
        Validated manifest. download returns a compiled StoreManifest.
    partition_files : Mapping[PartitionIdentifier, pathlib.Path]
        Read-only product/year partition paths.
    """

    root: StoreRoot
    manifest: StoreManifest | AccumulatedStoreManifest
    partition_files: Mapping[PartitionIdentifier, Path]

    def __post_init__(self) -> None:
        object.__setattr__(self, "partition_files", MappingProxyType(dict(self.partition_files)))


class StoreRefusalKind(StrEnum):
    INCOMPATIBLE = "incompatible"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class StoreRefusal:
    kind: StoreRefusalKind
    store: StoreRoot
    provider_id: ProviderId
    defect: str

    @property
    def rebuild_instruction(self) -> str:
        return f'rivretrieve.download("{self.provider_id}")'


class ObservationStoreRefusedError(FatalContractError):
    """Raised when an existing local observation store is malformed or incompatible.

    ``refusal`` records the kind (``malformed`` or ``incompatible``), the store
    path, the provider and the defect. The store is left in place. Rebuild a
    compiled store with ``download`` or remove an accumulated store with
    ``clear_cache``.
    """

    refusal: StoreRefusal

    def __init__(self, refusal: StoreRefusal) -> None:
        self.refusal = refusal
        label = refusal.kind.value.capitalize()
        message = (
            f'{label} observation store at "{refusal.store}": {refusal.defect}. '
            f"For a compiled store rebuild it with {refusal.rebuild_instruction}; "
            f'for an accumulated store clear it with rivretrieve.clear_cache("{refusal.provider_id}")'
        )
        super().__init__(message)


class _JSONObject(list[tuple[str, object]]):
    pass


_PARTITION_FILE = re.compile(r"product=[^/=]+/year=[0-9]{4}/[^/]+\.parquet")
_PARTITION_DIRECTORY = re.compile(r"product=[^/=]+/year=[0-9]{4}")
_REQUIRED_FIELD_NAMES = (
    "station_id",
    "time",
    "time_zone",
    "value",
    "value_state",
    "series_id",
    "facts_id",
    "source_unit",
)


def _refuse(
    kind: StoreRefusalKind,
    store: StoreRoot,
    provider_id: ProviderId,
    defect: str,
) -> NoReturn:
    raise ObservationStoreRefusedError(StoreRefusal(kind, store, provider_id, defect))


def _materialize_json(value: object, path: tuple[str, ...]) -> object:
    if isinstance(value, _JSONObject):
        result: dict[str, object] = {}
        for key, member in value:
            member_path = (*path, key)
            if key in result:
                raise ValueError(".".join(member_path))
            result[key] = _materialize_json(member, member_path)
        return result
    if isinstance(value, list):
        return [_materialize_json(member, (*path, str(index))) for index, member in enumerate(value)]
    return value


def _read_raw_manifest(store: StoreRoot, provider_id: ProviderId) -> dict[str, Any]:
    try:
        manifest_bytes = (Path(store) / "manifest.json").read_bytes()
    except OSError:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.io:manifest.json")
    try:
        manifest_text = manifest_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.utf8:manifest.json")
    try:
        parsed = json.loads(
            manifest_text,
            object_pairs_hook=_JSONObject,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except json.JSONDecodeError:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.json:syntax")
    except ValueError as error:
        if isinstance(error, json.JSONDecodeError):
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.json:syntax")
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.json:syntax")
    try:
        materialized = _materialize_json(parsed, ())
    except ValueError as error:
        _refuse(
            StoreRefusalKind.MALFORMED,
            store,
            provider_id,
            f"manifest.json:duplicate:{error}",
        )
    if not isinstance(materialized, dict):
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.root:type")
    return cast(dict[str, Any], materialized)


def _check_revision(raw: dict[str, Any], store: StoreRoot, provider_id: ProviderId) -> None:
    if "format_version" not in raw:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.required:format_version")
    version = raw["format_version"]
    if type(version) is not int:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.type:format_version")
    if version not in (5, 8):
        _refuse(
            StoreRefusalKind.INCOMPATIBLE,
            store,
            provider_id,
            f"unsupported format revision {version!r}",
        )


def _schema_error_path(error: Any, raw: dict[str, Any]) -> str:
    path = tuple(str(part) for part in error.absolute_path)
    if error.validator == "required" and not path:
        missing = next(property_name for property_name in error.validator_value if property_name not in error.instance)
        return missing
    if path[:1] == ("source_column_dispositions",) and len(path) >= 2 and path[1].isdigit():
        item = raw["source_column_dispositions"][int(path[1])]
        if not isinstance(item, dict):
            return ".".join(path)
        subject = item.get("source_column")
        if item.get("disposition") == "reconstructible" and not item.get("reconstruction_rule"):
            return f"__disposition_reconstruction_rule__:{subject}"
        if item.get("disposition") == "deliberately_discarded" and not item.get("rationale"):
            return f"__disposition_rationale__:{subject}"
    return ".".join(path) if path else "root"


def _validate_manifest_schema(raw: dict[str, Any], store: StoreRoot, provider_id: ProviderId) -> None:
    schema_resource = resources.files(__package__).joinpath("manifest.schema.json")
    schema = json.loads(schema_resource.read_text(encoding="utf-8"))
    if raw["format_version"] == 8:
        schema = schema["$defs"]["accumulated"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(raw),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
            error.message,
        ),
    )
    if not errors:
        return
    error = errors[0]
    path = _schema_error_path(error, raw)
    if path.startswith("__disposition_reconstruction_rule__:"):
        defect = f"disposition.reconstruction_rule:{path.split(':', 1)[1]}"
    elif path.startswith("__disposition_rationale__:"):
        defect = f"disposition.rationale:{path.split(':', 1)[1]}"
    else:
        defect = f"manifest.{error.validator}:{path}"
    _refuse(StoreRefusalKind.MALFORMED, store, provider_id, defect)


def _validate_source_contract(raw: dict[str, Any], store: StoreRoot, provider_id: ProviderId) -> None:
    columns = raw["source_schema"]["columns"]
    canonical = json.dumps(columns, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    fingerprint = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    if raw["source_schema"]["fingerprint"] != fingerprint:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "source_schema.fingerprint")

    names: set[str] = set()
    for column in columns:
        name = column["name"]
        if name in names:
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"source_schema.duplicate:{name}")
        names.add(name)

    disposition_names: set[str] = set()
    for item in raw["source_column_dispositions"]:
        name = item["source_column"]
        if name in disposition_names:
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"disposition.duplicate:{name}")
        disposition_names.add(name)
        disposition = item["disposition"]
        rule = item.get("reconstruction_rule")
        rationale = item.get("rationale")
        if disposition == "retained" and rule is not None:
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"disposition.reconstruction_rule:{name}")
        if disposition == "retained" and rationale is not None:
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"disposition.rationale:{name}")
        if disposition == "reconstructible" and (not rule or rationale is not None):
            defect = "reconstruction_rule" if not rule else "rationale"
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"disposition.{defect}:{name}")
        if disposition == "deliberately_discarded" and (not rationale or rule is not None):
            defect = "rationale" if not rationale else "reconstruction_rule"
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"disposition.{defect}:{name}")

    if disposition_names != names:
        missing = sorted(names - disposition_names)
        extra = sorted(disposition_names - names)
        _refuse(
            StoreRefusalKind.MALFORMED,
            store,
            provider_id,
            f"disposition.incomplete:missing={missing!r}:extra={extra!r}",
        )


def _discover_partitions(
    raw: dict[str, Any], store: StoreRoot, provider_id: ProviderId
) -> dict[PartitionIdentifier, Path]:
    root = Path(store)
    try:
        parquet_paths = sorted(root.rglob("*.parquet"), key=lambda path: path.relative_to(root).as_posix())
    except OSError:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "partition.path:.")

    for path in parquet_paths:
        relative = path.relative_to(root).as_posix()
        if not _PARTITION_FILE.fullmatch(relative):
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.path:{relative}")

    directories: dict[PartitionIdentifier, Path] = {}
    for path in parquet_paths:
        identifier = PartitionIdentifier(path.parent.relative_to(root).as_posix())
        directories.setdefault(identifier, path.parent)

    try:
        canonical_directories = sorted(
            (
                path
                for path in root.glob("product=*/year=*")
                if path.is_dir() and _PARTITION_DIRECTORY.fullmatch(path.relative_to(root).as_posix())
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    except OSError:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "partition.path:.")

    for directory in canonical_directories:
        identifier = PartitionIdentifier(directory.relative_to(root).as_posix())
        try:
            files = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix == ".parquet")
        except OSError:
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.file_count:{identifier}")
        if len(files) != 1:
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.file_count:{identifier}")
        directories[identifier] = directory

    manifest_keys = {PartitionIdentifier(key) for key in raw["partition_row_counts"]}
    actual_keys = set(directories)
    if manifest_keys != actual_keys:
        _refuse(
            StoreRefusalKind.MALFORMED,
            store,
            provider_id,
            f"partition.key:expected={sorted(manifest_keys)!r};actual={sorted(actual_keys)!r}",
        )

    return {
        identifier: next(path for path in parquet_paths if path.parent == directories[identifier])
        for identifier in sorted(directories)
    }


def _open_parquet(path: Path) -> pq.ParquetFile:
    return pq.ParquetFile(path)


def _is_utf8_string(data_type: pa.DataType) -> bool:
    return pa.types.is_string(data_type) or pa.types.is_large_string(data_type)


def _validate_partition(
    identifier: PartitionIdentifier,
    path: Path,
    expected_rows: int,
    retained_columns: tuple[str, ...],
    source_columns: tuple[dict[str, str], ...],
    store: StoreRoot,
    provider_id: ProviderId,
    *,
    allowed_null_states: tuple[str, ...] = ("published_null", "published_blank"),
) -> None:
    try:
        parquet = _open_parquet(path)
        actual_rows = parquet.metadata.num_rows
    except (OSError, ValueError, pa.ArrowException):
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.parquet:{identifier}")
    if actual_rows != expected_rows:
        _refuse(
            StoreRefusalKind.MALFORMED,
            store,
            provider_id,
            f"partition.row_count:{identifier}:expected={expected_rows}:actual={actual_rows}",
        )

    schema = parquet.schema_arrow
    types_are_valid = len(schema) >= len(_REQUIRED_FIELD_NAMES) and (
        _is_utf8_string(schema[0].type)
        and pa.types.is_timestamp(schema[1].type)
        and schema[1].type.unit == "us"
        and schema[1].type.tz is None
        and _is_utf8_string(schema[2].type)
        and pa.types.is_float64(schema[3].type)
        and _is_utf8_string(schema[4].type)
    )
    names_are_valid = tuple(schema.names[: len(_REQUIRED_FIELD_NAMES)]) == _REQUIRED_FIELD_NAMES
    types_are_valid = types_are_valid and all(
        _is_utf8_string(schema[index].type) for index in range(5, min(len(schema), len(_REQUIRED_FIELD_NAMES)))
    )
    if not names_are_valid or not types_are_valid:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.schema:{identifier}")
    native_columns = tuple(column for column in retained_columns if column not in _REQUIRED_FIELD_NAMES)
    expected_names = (*_REQUIRED_FIELD_NAMES, *native_columns)
    source_types = {column["name"]: column["type"] for column in source_columns}
    type_checks = {
        "text": _is_utf8_string,
        "string": _is_utf8_string,
        "integer": pa.types.is_int64,
        "double": pa.types.is_float64,
        "float64": pa.types.is_float64,
        "timestamp[us]": lambda value: pa.types.is_timestamp(value) and value.unit == "us" and value.tz is None,
    }
    native_types_are_valid = all(
        source_types[name].lower() in type_checks and type_checks[source_types[name].lower()](schema.field(name).type)
        for name in native_columns
        if name in schema.names
    )
    if tuple(schema.names) != expected_names or not native_types_are_valid:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.schema:{identifier}")
    partition_year = int(str(identifier).rsplit("year=", 1)[1])
    last_station: bytes | None = None
    row_offset = 0
    try:
        batches = parquet.iter_batches(
            batch_size=65_536,
            columns=["station_id", "time", "time_zone", "value", "value_state"],
        )
        for batch in batches:
            station_ids = batch.column("station_id").to_pylist()
            times = batch.column("time").to_pylist()
            time_zones = batch.column("time_zone").to_pylist()
            values = batch.column("value").to_pylist()
            value_states = batch.column("value_state").to_pylist()
            for column_name, values_to_check in (
                ("station_id", station_ids),
                ("time", times),
                ("time_zone", time_zones),
                ("value_state", value_states),
            ):
                if any(value is None for value in values_to_check):
                    _refuse(
                        StoreRefusalKind.MALFORMED,
                        store,
                        provider_id,
                        f"partition.nullability:{identifier}:{column_name}",
                    )
            if any(station_id == "" for station_id in station_ids):
                _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.station_id:{identifier}")
            bytewise_ids = [station_id.encode("utf-8") for station_id in station_ids]
            if last_station is not None and bytewise_ids and last_station > bytewise_ids[0]:
                _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.order:{identifier}")
            if any(left > right for left, right in zip(bytewise_ids, bytewise_ids[1:], strict=False)):
                _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.order:{identifier}")
            if bytewise_ids:
                last_station = bytewise_ids[-1]
            for index, timestamp in enumerate(times, start=row_offset):
                if timestamp.year != partition_year:
                    _refuse(
                        StoreRefusalKind.MALFORMED,
                        store,
                        provider_id,
                        f"partition.year:{identifier}:row={index}",
                    )
            for index, (value, state) in enumerate(zip(values, value_states, strict=True), start=row_offset):
                legal = (state == "published_value" and value is not None) or (
                    state in allowed_null_states and value is None
                )
                if not legal:
                    _refuse(
                        StoreRefusalKind.MALFORMED,
                        store,
                        provider_id,
                        f"value_state.combination:{identifier}:row={index}",
                    )
            row_offset += len(station_ids)
    except (OSError, ValueError, pa.ArrowException):
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.parquet:{identifier}")


def _parse_manifest(raw: dict[str, Any]) -> StoreManifest:
    source_schema = raw["source_schema"]
    return StoreManifest(
        format_version=5,
        provider_id=ProviderId(raw["provider_id"]),
        compiler_version=raw["compiler_version"],
        built_at=datetime.fromisoformat(raw["built_at"].removesuffix("Z") + "+00:00"),
        source_vintage=date.fromisoformat(raw["source_vintage"]),
        publisher_artifact=(
            PublisherArtifact(raw["publisher_artifact"]["url"], ArtifactChecksum(raw["publisher_artifact"]["sha256"]))
            if "publisher_artifact" in raw
            else PublisherArtifact(
                raw["publisher_artifacts"][0]["url"], ArtifactChecksum(raw["publisher_artifacts"][0]["sha256"])
            )
        ),
        publisher_artifacts=tuple(
            PublisherArtifact(item["url"], ArtifactChecksum(item["sha256"]))
            for item in (raw.get("publisher_artifacts") or [raw["publisher_artifact"]])
        ),
        source_schema=SourceSchema(
            columns=tuple(SourceColumn(column["name"], column["type"]) for column in source_schema["columns"]),
            fingerprint=SourceSchemaFingerprint(source_schema["fingerprint"]),
        ),
        source_column_dispositions=tuple(
            SourceColumnDisposition(
                source_column=item["source_column"],
                disposition=Disposition(item["disposition"]),
                reconstruction_rule=item.get("reconstruction_rule"),
                rationale=item.get("rationale"),
            )
            for item in raw["source_column_dispositions"]
        ),
        partition_row_counts={
            PartitionIdentifier(identifier): count for identifier, count in raw["partition_row_counts"].items()
        },
        **_metadata(raw),
    )


def validate_store(store: StoreRoot, provider_id: ProviderId) -> ValidatedStore:
    raw = _read_raw_manifest(store, provider_id)
    _check_revision(raw, store, provider_id)
    stored_provider = raw.get("provider_id")
    identity = publication_identity_fields((stored_provider,)) if isinstance(stored_provider, str) else {}
    for field, expected in identity.items():
        if raw.get(field) != expected:
            _refuse(StoreRefusalKind.INCOMPATIBLE, store, provider_id, f"{field}:expected {expected}")
    _validate_manifest_schema(raw, store, provider_id)
    if raw["provider_id"] != str(provider_id):
        _refuse(StoreRefusalKind.INCOMPATIBLE, store, provider_id, f"manifest.provider_id:{raw['provider_id']!r}")
    _validate_metadata(raw, store, provider_id)
    if raw["format_version"] == 8:
        return _validate_accumulated(raw, store, provider_id)
    _validate_source_contract(raw, store, provider_id)
    partition_files = _discover_partitions(raw, store, provider_id)
    retained_columns = tuple(
        item["source_column"]
        for item in raw["source_column_dispositions"]
        if item["disposition"] == Disposition.RETAINED
    )
    for identifier, path in partition_files.items():
        _validate_partition(
            identifier,
            path,
            raw["partition_row_counts"][identifier],
            retained_columns,
            tuple(raw["source_schema"]["columns"]),
            store,
            provider_id,
        )
    _validate_series_partitions(raw, partition_files, store, provider_id)
    manifest = _parse_manifest(raw)
    return ValidatedStore(root=store, manifest=manifest, partition_files=partition_files)


def _validate_accumulated(raw: dict[str, Any], store: StoreRoot, provider_id: ProviderId) -> ValidatedStore:
    coverage: list[CoverageInterval] = []
    outcomes = {item.outcome_id: item for item in _metadata(raw)["outcomes"]}
    for index, item in enumerate(raw["coverage"]):
        try:
            record = CoverageInterval(
                item["series_id"],
                RequestedInterval(
                    datetime.fromisoformat(item["start"]),
                    datetime.fromisoformat(item["end"]),
                    axis=TimeAxis(item["axis"]),
                ),
                datetime.fromisoformat(item["retrieved_at"]) if item["retrieved_at"] is not None else None,
                item["outcome_id"],
                tuple(item["facts_ids"]),
            )
        except (ValueError, TypeError):
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"coverage.interval:{index}")
        outcome = outcomes.get(record.outcome_id)
        if (
            outcome is None
            or outcome.series_id != record.series_id
            or outcome.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
            or outcome.coverage != "interval"
            or outcome.window.axis is not record.interval.axis
            or outcome.window.start > record.interval.start
            or outcome.window.end < record.interval.end
            or outcome.retrieved_at != record.retrieved_at
            or not record.facts_ids
            or not set(record.facts_ids).issubset(outcome.facts_ids)
        ):
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"coverage.outcome:{index}")
        if any(
            previous.series_id == record.series_id
            and previous.interval.axis is record.interval.axis
            and bool(set(previous.facts_ids).intersection(record.facts_ids))
            and previous.interval.start <= record.interval.end
            and previous.interval.end >= record.interval.start
            for previous in coverage
        ):
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"coverage.overlap:{index}")
        coverage.append(record)
    observed_keys = {
        (outcome.series_id, *key)
        for outcome in outcomes.values()
        if outcome.coverage == "observations" and outcome.status is OutcomeStatus.SUCCESS
        for key in outcome.observation_keys
    }
    partitions = _discover_partitions(raw, store, provider_id)
    for identifier, path in partitions.items():
        _validate_partition(
            identifier,
            path,
            raw["partition_row_counts"][identifier],
            (),
            (),
            store,
            provider_id,
            allowed_null_states=("published_null",),
        )
        for batch in _open_parquet(path).iter_batches(columns=["series_id", "facts_id", "time", "time_zone"]):
            for series_id, facts_id, timestamp, time_zone in zip(
                batch.column("series_id").to_pylist(),
                batch.column("facts_id").to_pylist(),
                batch.column("time").to_pylist(),
                batch.column("time_zone").to_pylist(),
                strict=True,
            ):
                if (
                    not any(
                        c.series_id == series_id
                        and facts_id in c.facts_ids
                        and c.interval.start <= timestamp <= c.interval.end
                        for c in coverage
                    )
                    and (series_id, facts_id, timestamp, time_zone) not in observed_keys
                ):
                    _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"coverage.row:{identifier}")
    _validate_series_partitions(raw, partitions, store, provider_id)
    manifest = AccumulatedStoreManifest(
        format_version=8,
        provider_id=provider_id,
        built_at=datetime.fromisoformat(raw["built_at"].removesuffix("Z") + "+00:00"),
        coverage=tuple(coverage),
        partition_row_counts={PartitionIdentifier(key): value for key, value in raw["partition_row_counts"].items()},
        **_metadata(raw),
    )
    return ValidatedStore(root=store, manifest=manifest, partition_files=partitions)


def _metadata(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "series": tuple(SourceSeries.model_validate(item) for item in raw["series"]),
        "inventories": tuple(InventorySnapshot.model_validate(item) for item in raw["inventories"]),
        "outcomes": tuple(RetrievalOutcome.model_validate(item) for item in raw["outcomes"]),
        "issues": tuple(Issue.model_validate(item) for item in raw["issues"]),
        "source_calls": tuple(decode_source_call(item) for item in raw["source_calls"]),
    }


def _validate_metadata(raw: dict[str, Any], store: StoreRoot, provider_id: ProviderId) -> None:
    try:
        metadata = _metadata(raw)
    except (ValidationError, ValueError, TypeError) as error:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"series.metadata:{error}")
    definitions = {item.series_id: item for item in metadata["series"]}
    if len(definitions) != len(metadata["series"]) or any(
        item.provider_id != provider_id for item in definitions.values()
    ):
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "series.identity")
    facts: dict[str, object] = {}
    for definition in definitions.values():
        for fact in definition.facts:
            if fact.facts_id in facts and facts[fact.facts_id] != fact:
                _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "series.facts_conflict")
            facts[fact.facts_id] = fact
    snapshots: set[str] = set()
    for snapshot in metadata["inventories"]:
        if snapshot.snapshot_id in snapshots or len(set(snapshot.members)) != len(snapshot.members):
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "inventory.identity")
        snapshots.add(snapshot.snapshot_id)
        if any(member not in definitions for member in snapshot.members):
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "inventory.member")
        if snapshot.member_facts:
            member_facts = dict(snapshot.member_facts)
            if len(member_facts) != len(snapshot.member_facts) or set(member_facts) != set(snapshot.members):
                _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "inventory.member_facts")
            for member, fact_ids in snapshot.member_facts:
                allowed = {fact.facts_id for fact in definitions[member].facts}
                if not fact_ids or len(set(fact_ids)) != len(fact_ids) or not set(fact_ids).issubset(allowed):
                    _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "inventory.member_facts")
    outcomes: set[str] = set()
    for outcome in metadata["outcomes"]:
        if not outcome.outcome_id or outcome.outcome_id in outcomes:
            _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "outcome.identity")
        outcomes.add(outcome.outcome_id)
        if outcome.series_id is not None:
            definition = definitions.get(outcome.series_id)
            if definition is None or (definition.station_id, definition.product_id) != (
                outcome.station_id,
                outcome.product_id,
            ):
                _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "outcome.series")
            allowed = {fact.facts_id for fact in definition.facts}
            if any(fact_id not in allowed for fact_id in outcome.facts_ids):
                _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "outcome.facts")
            if outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY) and any(
                admission(fact).status != "supported" for fact in definition.facts if fact.facts_id in outcome.facts_ids
            ):
                _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "outcome.admission")


def _validate_series_partitions(
    raw: dict[str, Any], partitions: Mapping[PartitionIdentifier, Path], store: StoreRoot, provider_id: ProviderId
) -> None:
    definitions = {item.series_id: item for item in _metadata(raw)["series"]}
    for identifier, path in partitions.items():
        product = str(identifier).split("/", 1)[0].removeprefix("product=")
        for batch in _open_parquet(path).iter_batches(columns=["station_id", "series_id", "facts_id", "source_unit"]):
            for row in batch.to_pylist():
                definition = definitions.get(row["series_id"])
                if definition is None or definition.station_id != row["station_id"] or definition.product_id != product:
                    _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.series:{identifier}")
                fact = next((item for item in definition.facts if item.facts_id == row["facts_id"]), None)
                if (
                    fact is None
                    or admission(fact).status != "supported"
                    or fact.source_unit.value != row["source_unit"]
                ):
                    _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.facts:{identifier}")
