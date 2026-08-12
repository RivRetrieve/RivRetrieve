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
from typing import Any, Literal, NewType, cast

import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator, FormatChecker

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId

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
    format_version: Literal[1]
    compiler_version: str
    built_at: datetime
    source_vintage: date
    publisher_artifact: PublisherArtifact
    source_schema: SourceSchema
    source_column_dispositions: tuple[SourceColumnDisposition, ...]
    partition_row_counts: Mapping[PartitionIdentifier, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "partition_row_counts", MappingProxyType(dict(self.partition_row_counts)))


@dataclass(frozen=True, slots=True)
class ValidatedStore:
    root: StoreRoot
    manifest: StoreManifest
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
    refusal: StoreRefusal

    def __init__(self, refusal: StoreRefusal) -> None:
        self.refusal = refusal
        label = refusal.kind.value.capitalize()
        message = (
            f'{label} observation store at "{refusal.store}": {refusal.defect}. '
            f"Rebuild it with {refusal.rebuild_instruction}"
        )
        super().__init__(message)


class _JSONObject(list[tuple[str, object]]):
    pass


_PARTITION_FILE = re.compile(r"product=[^/=]+/year=[0-9]{4}/[^/]+\.parquet")
_PARTITION_DIRECTORY = re.compile(r"product=[^/=]+/year=[0-9]{4}")
_REQUIRED_FIELD_NAMES = ("station_id", "time", "time_zone", "value", "value_state")


def _refuse(
    kind: StoreRefusalKind,
    store: StoreRoot,
    provider_id: ProviderId,
    defect: str,
) -> None:
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
    if version != 1:
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
    store: StoreRoot,
    provider_id: ProviderId,
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
    names_are_valid = tuple(schema.names[:5]) == _REQUIRED_FIELD_NAMES
    if not names_are_valid or not types_are_valid:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.schema:{identifier}")
    try:
        table = parquet.read()
    except (OSError, ValueError, pa.ArrowException):
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.parquet:{identifier}")

    station_ids = table.column("station_id").to_pylist()
    times = table.column("time").to_pylist()
    time_zones = table.column("time_zone").to_pylist()
    values = table.column("value").to_pylist()
    value_states = table.column("value_state").to_pylist()
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
    if any(left > right for left, right in zip(bytewise_ids, bytewise_ids[1:], strict=False)):
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"partition.order:{identifier}")

    partition_year = int(str(identifier).rsplit("year=", 1)[1])
    for index, timestamp in enumerate(times):
        if timestamp.year != partition_year:
            _refuse(
                StoreRefusalKind.MALFORMED,
                store,
                provider_id,
                f"partition.year:{identifier}:row={index}",
            )

    for index, (value, state) in enumerate(zip(values, value_states, strict=True)):
        legal = (state == "published_value" and value is not None) or (
            state in {"published_null", "published_blank"} and value is None
        )
        if not legal:
            _refuse(
                StoreRefusalKind.MALFORMED,
                store,
                provider_id,
                f"value_state.combination:{identifier}:row={index}",
            )


def _parse_manifest(raw: dict[str, Any]) -> StoreManifest:
    source_schema = raw["source_schema"]
    return StoreManifest(
        format_version=1,
        compiler_version=raw["compiler_version"],
        built_at=datetime.fromisoformat(raw["built_at"].removesuffix("Z") + "+00:00"),
        source_vintage=date.fromisoformat(raw["source_vintage"]),
        publisher_artifact=PublisherArtifact(
            url=raw["publisher_artifact"]["url"],
            sha256=ArtifactChecksum(raw["publisher_artifact"]["sha256"]),
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
    )


def validate_store(store: StoreRoot, provider_id: ProviderId) -> ValidatedStore:
    raw = _read_raw_manifest(store, provider_id)
    _check_revision(raw, store, provider_id)
    _validate_manifest_schema(raw, store, provider_id)
    _validate_source_contract(raw, store, provider_id)
    partition_files = _discover_partitions(raw, store, provider_id)
    for identifier, path in partition_files.items():
        _validate_partition(identifier, path, raw["partition_row_counts"][identifier], store, provider_id)
    manifest = _parse_manifest(raw)
    return ValidatedStore(root=store, manifest=manifest, partition_files=partition_files)
