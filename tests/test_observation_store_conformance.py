"""conformance : ManifestSchema × CommittedStore × CaseUniverse → ordered list[ConformanceDefect] (test-only).

The governing prose is docs/design/observation-store-layout.md. Helpers in this module are test-only conformance inspectors, not a production reader or compiler. The case universe is supplied to conformance and is not a manifest property.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow.parquet as pq
import pytest
from jsonschema import Draft202012Validator, FormatChecker, SchemaError
from polars.testing import assert_frame_equal

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/test_data/source_series_store_conformance"
SCHEMA_PATH = ROOT / "src/rivretrieve/_internal/store/manifest.schema.json"
PARTITION_PATTERN = re.compile(r"^product=(?P<product>[^/=]+)/year=(?P<year>[0-9]{4})/(?P<basename>[^/]+\.parquet)$")
PHYSICAL_SCHEMA = pl.Schema(
    {
        "station_id": pl.String,
        "time": pl.Datetime("us"),
        "time_zone": pl.String,
        "value": pl.Float64,
        "value_state": pl.String,
        "series_id": pl.String,
        "facts_id": pl.String,
        "source_unit": pl.String,
        "native_unit": pl.String,
        "source_quality": pl.String,
        "source_note": pl.String,
    }
)
NATIVE_PHYSICAL_SCHEMA = pl.Schema(
    {name: dtype for name, dtype in PHYSICAL_SCHEMA.items() if name not in {"series_id", "facts_id", "source_unit"}}
)
FINGERPRINT = "sha256:fec7d282faad87c744bd83241c5be29a15b7a7254760b7a9aed0f4e27ba3ecca"
VALID_NAMES = {
    "valid_hydat_national",
    "valid_yearly_archives",
    "valid_future_austria",
    "valid_source_duplicates",
}
INVALID_DEFECTS = {
    "invalid_manifest_required_field": "manifest.required:built_at",
    "invalid_manifest_type": "manifest.type:compiler_version",
    "invalid_manifest_version": "manifest.version:format_version",
    "invalid_manifest_checksum": "manifest.checksum:publisher_artifact.sha256",
    "invalid_manifest_fingerprint": "manifest.fingerprint:source_schema.fingerprint",
    "invalid_manifest_count": "manifest.count:partition_row_counts.product=level/year=2024",
    "invalid_partition_path": "partition.path:product=level/year-2024/part-0.parquet",
    "invalid_partition_key": "partition.key:expected=['product=stage/year=2024'];actual=['product=level/year=2024']",
    "invalid_partition_row_count": "partition.row_count:product=level/year=2024:expected=2:actual=1",
    "invalid_value_state_combination": "value_state.combination:product=level/year=2024:row=0",
    "invalid_disposition_incomplete": "disposition.incomplete:missing=['source_note']:extra=[]",
    "invalid_disposition_duplicate": "disposition.duplicate:source_note",
    "invalid_disposition_reconstructible_without_rule": "disposition.reconstruction_rule:source_note",
    "invalid_disposition_discard_without_rationale": "disposition.rationale:source_note",
}


@dataclass(frozen=True)
class Case:
    station_id: str
    product: str
    day: date


FUTURE_UNIVERSE = (Case("at-001", "level", date(2024, 1, 2)),)
CASE_UNIVERSES = {
    "valid_hydat_national": (
        Case("ca-001", "discharge", date(2023, 12, 31)),
        Case("ca-001", "discharge", date(2024, 1, 1)),
        Case("ca-002", "discharge", date(2024, 1, 1)),
        Case("ca-001", "level", date(2024, 1, 1)),
        Case("ca-002", "level", date(2024, 1, 1)),
    ),
    "valid_yearly_archives": (
        Case("pl-001", "discharge", date(2023, 12, 31)),
        Case("pl-001", "discharge", date(2024, 1, 1)),
    ),
    "valid_future_austria": FUTURE_UNIVERSE,
    "valid_source_duplicates": FUTURE_UNIVERSE,
    **dict.fromkeys(INVALID_DEFECTS, FUTURE_UNIVERSE),
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_load_json(SCHEMA_PATH), format_checker=FormatChecker())


def _raw_errors(manifest: dict[str, Any]) -> list[Any]:
    return sorted(
        _validator().iter_errors(manifest),
        key=lambda error: (
            list(error.absolute_path),
            error.validator,
            error.message,
        ),
    )


def _schema_error_code(error: Any, manifest: dict[str, Any]) -> str:
    path = list(error.absolute_path)
    dotted = ".".join(map(str, path)) or "root"
    if error.validator == "required":
        if path == []:
            missing = sorted(set(error.validator_value) - set(error.instance))
            return f"manifest.required:{missing[0]}"
        if path[:1] == ["source_column_dispositions"]:
            disposition = manifest["source_column_dispositions"][path[1]]
            column = disposition["source_column"]
            if disposition["disposition"] == "reconstructible":
                return f"disposition.reconstruction_rule:{column}"
            if disposition["disposition"] == "deliberately_discarded":
                return f"disposition.rationale:{column}"
    if error.validator == "type":
        return f"manifest.type:{dotted}"
    if error.validator == "const" and path == ["format_version"]:
        return "manifest.version:format_version"
    if error.validator == "pattern":
        if path == ["partition_row_counts"]:
            pattern = _load_json(SCHEMA_PATH)["properties"]["partition_row_counts"]["propertyNames"]["pattern"]
            key = (
                error.instance
                if isinstance(error.instance, str)
                else next(key for key in error.instance if re.fullmatch(pattern, key) is None)
            )
            return f"manifest.partition_key:{key}"
        if path == ["publisher_artifact", "sha256"]:
            return "manifest.checksum:publisher_artifact.sha256"
        if path == ["source_schema", "fingerprint"]:
            return "manifest.fingerprint:source_schema.fingerprint"
        return f"manifest.pattern:{dotted}"
    if error.validator == "minimum" and path[:1] == ["partition_row_counts"]:
        return f"manifest.count:partition_row_counts.{path[1]}"
    if error.validator == "propertyNames" and path == ["partition_row_counts"]:
        pattern = _load_json(SCHEMA_PATH)["properties"]["partition_row_counts"]["propertyNames"]["pattern"]
        key = next(key for key in error.instance if re.fullmatch(pattern, key) is None)
        return f"manifest.partition_key:{key}"
    return f"manifest.{error.validator}:{dotted}"


def _fingerprint(columns: list[dict[str, str]]) -> str:
    encoded = json.dumps(columns, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def inspect_store(path: Path, case_universe: tuple[Case, ...]) -> list[str]:
    manifest = _load_json(path / "manifest.json")
    errors = _raw_errors(manifest)
    if errors:
        return [_schema_error_code(errors[0], manifest)]

    columns = manifest["source_schema"]["columns"]
    if _fingerprint(columns) != manifest["source_schema"]["fingerprint"]:
        return ["manifest.fingerprint:source_schema.fingerprint"]
    source_names = [column["name"] for column in columns]
    source_counts = Counter(source_names)
    duplicate_sources = sorted(name for name, count in source_counts.items() if count > 1)
    if duplicate_sources:
        return [f"source_schema.duplicate:{duplicate_sources[0]}"]
    dispositions = manifest["source_column_dispositions"]
    disposition_counts = Counter(item["source_column"] for item in dispositions)
    duplicates = sorted(name for name, count in disposition_counts.items() if count > 1)
    if duplicates:
        return [f"disposition.duplicate:{duplicates[0]}"]
    missing = sorted(set(source_names) - disposition_counts.keys())
    extra = sorted(disposition_counts.keys() - set(source_names))
    if missing or extra:
        return [f"disposition.incomplete:missing={missing!r}:extra={extra!r}"]
    for disposition in dispositions:
        column = disposition["source_column"]
        kind = disposition["disposition"]
        has_rule = "reconstruction_rule" in disposition
        has_rationale = "rationale" in disposition
        if (kind == "reconstructible") != has_rule:
            return [f"disposition.reconstruction_rule:{column}"]
        if (kind == "deliberately_discarded") != has_rationale:
            return [f"disposition.rationale:{column}"]

    partitions: dict[str, list[Path]] = {}
    partition_parts: dict[str, tuple[str, int]] = {}
    for parquet_path in sorted(path.rglob("*.parquet")):
        relative = parquet_path.relative_to(path).as_posix()
        match = PARTITION_PATTERN.fullmatch(relative)
        if match is None:
            return [f"partition.path:{relative}"]
        identifier = f"product={match.group('product')}/year={match.group('year')}"
        partitions.setdefault(identifier, []).append(parquet_path)
        partition_parts[identifier] = (match.group("product"), int(match.group("year")))
    for identifier, files in partitions.items():
        if len(files) != 1:
            return [f"partition.file_count:{identifier}"]
    expected = sorted(manifest["partition_row_counts"])
    actual = sorted(partitions)
    if expected != actual:
        return [f"partition.key:expected={expected!r};actual={actual!r}"]
    for identifier, files in partitions.items():
        expected_count = manifest["partition_row_counts"][identifier]
        actual_count = pq.ParquetFile(files[0]).metadata.num_rows
        if expected_count != actual_count:
            return [f"partition.row_count:{identifier}:expected={expected_count}:actual={actual_count}"]

    if len(case_universe) != len(set(case_universe)):
        return ["case_universe.duplicate"]
    universe = set(case_universe)
    for identifier, files in partitions.items():
        frame = pl.read_parquet(files[0])
        required_schema = list(PHYSICAL_SCHEMA.items())[:8]
        if list(frame.schema.items())[:8] != required_schema:
            return [f"partition.schema:{identifier}"]
        for column in ["native_unit", "source_quality", "source_note"]:
            if column in frame.schema and frame.schema[column] != PHYSICAL_SCHEMA[column]:
                return [f"partition.schema:{identifier}"]
        for column in [
            "station_id",
            "time",
            "time_zone",
            "value_state",
            "native_unit",
        ]:
            if column in frame.schema and frame[column].null_count():
                return [f"partition.nullability:{identifier}:{column}"]
        if any(not station for station in frame["station_id"]):
            return [f"partition.station_id:{identifier}"]
        stations = frame["station_id"].to_list()
        if stations != sorted(stations, key=lambda station: station.encode("utf-8")):
            return [f"partition.order:{identifier}"]
        product, year = partition_parts[identifier]
        for row_index, row in enumerate(frame.iter_rows(named=True)):
            if row["time"].year != year:
                return [f"partition.year:{identifier}:row={row_index}"]
            state = row["value_state"]
            value = row["value"]
            legal = (state == "published_value" and value is not None) or (
                state in {"published_null", "published_blank"} and value is None
            )
            if not legal:
                return [f"value_state.combination:{identifier}:row={row_index}"]
            case = Case(row["station_id"], product, row["time"].date())
            if case not in universe:
                return [f"case_universe.missing:{identifier}:row={row_index}"]
    return []


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name
    shutil.copytree(FIXTURES / name, destination)
    return destination


def _part(store: Path) -> Path:
    return next(store.rglob("*.parquet"))


def _rewrite_row(path: Path, row_index: int, **updates: object) -> None:
    rows = pl.read_parquet(path).to_dicts()
    rows[row_index].update(updates)
    pl.DataFrame(rows, schema=PHYSICAL_SCHEMA).write_parquet(path, compression="zstd", statistics=True)


def _future_row() -> pl.DataFrame:
    return pl.DataFrame(
        [
            (
                "at-001",
                datetime(2024, 1, 2, 7, 30),
                "Europe/Vienna",
                152.4,
                "published_value",
                _load_json(FIXTURES / "valid_future_austria/manifest.json")["series"][0]["series_id"],
                _load_json(FIXTURES / "valid_future_austria/manifest.json")["series"][0]["facts"][0]["facts_id"],
                "cm",
                "cm",
                "checked",
                "future-source-only text",
            )
        ],
        schema=PHYSICAL_SCHEMA,
        orient="row",
    )


def test_manifest_schema_is_valid_draft_2020_12() -> None:
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "https://rivretrieve.org/schemas/observation-store-manifest-5.json"
    assert schema["required"] == [
        "format_version",
        "provider_id",
        "compiler_version",
        "built_at",
        "source_vintage",
        "source_schema",
        "source_column_dispositions",
        "partition_row_counts",
        "series",
        "inventories",
        "outcomes",
        "issues",
        "source_calls",
    ]
    assert schema["oneOf"] == [
        {"required": ["publisher_artifact"], "not": {"required": ["publisher_artifacts"]}},
        {"required": ["publisher_artifacts"], "not": {"required": ["publisher_artifact"]}},
    ]
    assert schema["properties"]["format_version"]["const"] == 5
    assert schema["properties"]["built_at"]["pattern"] == (
        r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
    )
    assert schema["properties"]["source_vintage"]["pattern"] == (r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    assert schema["properties"]["publisher_artifact"]["properties"]["sha256"]["pattern"] == r"^sha256:[0-9a-f]{64}$"
    assert schema["properties"]["source_schema"]["properties"]["fingerprint"]["pattern"] == r"^sha256:[0-9a-f]{64}$"
    counts = schema["properties"]["partition_row_counts"]
    assert counts["propertyNames"]["pattern"] == r"^product=[^/=]+/year=[0-9]{4}$"
    assert counts["additionalProperties"]["minimum"] == 1
    assert schema["$defs"]["source_column"] == {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "type"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "type": {"type": "string", "minLength": 1},
        },
    }
    disposition = schema["$defs"]["source_column_disposition"]
    assert disposition["properties"]["disposition"]["enum"] == [
        "retained",
        "reconstructible",
        "deliberately_discarded",
    ]
    assert disposition["allOf"][0]["then"]["required"] == ["reconstruction_rule"]
    assert disposition["allOf"][1]["then"]["required"] == ["rationale"]
    assert "case_universe" not in schema["required"]
    assert "case_universe" not in schema["properties"]

    template = _load_json(FIXTURES / "valid_future_austria/manifest.json")
    validator = _validator()
    for version in ["1.0rc1", "0.1.49.post1", "2024.1"]:
        candidate = deepcopy(template)
        candidate["compiler_version"] = version
        assert list(validator.iter_errors(candidate)) == []
    template["compiler_version"] = "not-pep440"
    errors = list(validator.iter_errors(template))
    assert [(error.validator, list(error.absolute_path)) for error in errors] == [("pattern", ["compiler_version"])]


def test_manifest_schema_checker_rejects_a_broken_schema_control() -> None:
    schema = _load_json(SCHEMA_PATH)
    schema["type"] = "not-a-json-schema-type"
    with pytest.raises(SchemaError):
        Draft202012Validator.check_schema(schema)


def test_every_valid_conformance_store_is_accepted() -> None:
    # Pin this shared contract exactly: hive-partitioned Parquet; partition keys `product` and `year`; on-disk directory form `product=<product_id>/year=<YYYY>/`; one Parquet file per partition; rows sorted by `station_id`; and canonical partition identifier `product=<product_id>/year=<YYYY>` used as the key of the manifest's per-partition row counts.
    for name in sorted(VALID_NAMES):
        assert inspect_store(FIXTURES / name, CASE_UNIVERSES[name]) == []


def test_valid_fixture_acceptance_has_a_controlled_rejection(tmp_path: Path) -> None:
    store = _copy_fixture("valid_future_austria", tmp_path)
    manifest = _load_json(store / "manifest.json")
    manifest["partition_row_counts"]["product=level/year=2024"] = 2
    _write_json(store / "manifest.json", manifest)
    assert inspect_store(store, FUTURE_UNIVERSE) == ["partition.row_count:product=level/year=2024:expected=2:actual=1"]


def test_parquet_basename_is_not_the_contract(tmp_path: Path) -> None:
    original = FIXTURES / "valid_future_austria/product=level/year=2024"
    assert (original / "part-0.parquet").exists()
    assert not (original / "data.parquet").exists()
    assert inspect_store(FIXTURES / "valid_future_austria", FUTURE_UNIVERSE) == []
    store = _copy_fixture("valid_future_austria", tmp_path)
    partition = store / "product=level/year=2024"
    renamed = partition / "observations.parquet"
    (partition / "part-0.parquet").rename(renamed)
    assert inspect_store(store, FUTURE_UNIVERSE) == []
    shutil.copy2(renamed, partition / "second.parquet")
    assert inspect_store(store, FUTURE_UNIVERSE) == ["partition.file_count:product=level/year=2024"]


def test_source_duplicates_are_preserved_and_readable() -> None:
    # Duplicate source rows remain rows; physical position is their identity.
    store = FIXTURES / "valid_source_duplicates"
    assert inspect_store(store, FUTURE_UNIVERSE) == []
    actual = pl.read_parquet(store / "product=level/year=2024/source-rows.parquet")
    assert_frame_equal(actual, pl.concat([_future_row(), _future_row()]))


def test_schema_error_normalizer_names_actual_field_and_validator(
    tmp_path: Path,
) -> None:
    stores = [_copy_fixture("valid_future_austria", tmp_path / str(index)) for index in range(3)]
    manifests = [_load_json(store / "manifest.json") for store in stores]
    del manifests[0]["source_vintage"]
    manifests[1]["compiler_version"] = "not-pep440"
    manifests[2]["partition_row_counts"] = {"level/2024": 1}
    expected = [
        "manifest.required:source_vintage",
        "manifest.pattern:compiler_version",
        "manifest.partition_key:level/2024",
    ]
    for store, manifest, defect in zip(stores, manifests, expected, strict=True):
        _write_json(store / "manifest.json", manifest)
        assert inspect_store(store, FUTURE_UNIVERSE) == [defect]


def test_fingerprint_covers_names_and_types(tmp_path: Path) -> None:
    manifest = _load_json(FIXTURES / "valid_future_austria/manifest.json")
    assert _fingerprint(manifest["source_schema"]["columns"]) == FINGERPRINT
    store = _copy_fixture("valid_future_austria", tmp_path)
    manifest["source_schema"]["columns"][3]["type"] = "float32"
    _write_json(store / "manifest.json", manifest)
    assert inspect_store(store, FUTURE_UNIVERSE) == ["manifest.fingerprint:source_schema.fingerprint"]


def test_every_invalid_conformance_store_is_rejected_for_its_named_defect() -> None:
    names = {path.name for path in FIXTURES.iterdir() if path.is_dir() and path.name != "accumulated"}
    assert names == VALID_NAMES | INVALID_DEFECTS.keys()
    for name, defect in INVALID_DEFECTS.items():
        assert inspect_store(FIXTURES / name, CASE_UNIVERSES[name]) == [defect]


def _json_differences(left: Any, right: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        differences = [path + (key,) for key in left.keys() ^ right.keys()]
        for key in left.keys() & right.keys():
            differences.extend(_json_differences(left[key], right[key], path + (key,)))
        return differences
    if isinstance(left, list):
        if len(left) != len(right):
            return [path]
        differences = []
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            differences.extend(_json_differences(left_item, right_item, path + (index,)))
        return differences
    return [] if left == right else [path]


MANIFEST_MUTATION_PATHS = {
    "invalid_manifest_required_field": [("built_at",)],
    "invalid_manifest_type": [("compiler_version",)],
    "invalid_manifest_version": [("format_version",)],
    "invalid_manifest_checksum": [("publisher_artifact", "sha256")],
    "invalid_manifest_fingerprint": [("source_schema", "fingerprint")],
    "invalid_manifest_count": [("partition_row_counts", "product=level/year=2024")],
    "invalid_partition_path": [],
    "invalid_partition_key": [
        ("partition_row_counts", "product=level/year=2024"),
        ("partition_row_counts", "product=stage/year=2024"),
    ],
    "invalid_partition_row_count": [("partition_row_counts", "product=level/year=2024")],
    "invalid_value_state_combination": [],
    "invalid_disposition_incomplete": [("source_column_dispositions",)],
    "invalid_disposition_duplicate": [("source_column_dispositions",)],
    "invalid_disposition_reconstructible_without_rule": [("source_column_dispositions", 6, "disposition")],
    "invalid_disposition_discard_without_rationale": [("source_column_dispositions", 6, "disposition")],
}


def test_each_invalid_fixture_is_valid_future_plus_one_mutation() -> None:
    valid = FIXTURES / "valid_future_austria"
    valid_manifest = _load_json(valid / "manifest.json")
    valid_bytes = _part(valid).read_bytes()
    valid_frame = pl.read_parquet(_part(valid))
    for name in INVALID_DEFECTS:
        store = FIXTURES / name
        differences = _json_differences(valid_manifest, _load_json(store / "manifest.json"))
        assert sorted(differences, key=str) == sorted(MANIFEST_MUTATION_PATHS[name], key=str)
        path = _part(store)
        if name == "invalid_value_state_combination":
            repaired = pl.read_parquet(path).with_columns(pl.lit("published_value").alias("value_state"))
            assert_frame_equal(repaired, valid_frame)
        else:
            assert path.read_bytes() == valid_bytes
        if name == "invalid_partition_path":
            assert path.relative_to(store).as_posix() == ("product=level/year-2024/part-0.parquet")


def test_schema_level_invalid_fixtures_fail_at_the_intended_raw_validator() -> None:
    expected = {
        "invalid_manifest_required_field": ("required", []),
        "invalid_manifest_type": ("type", ["compiler_version"]),
        "invalid_manifest_version": ("const", ["format_version"]),
        "invalid_manifest_checksum": ("pattern", ["publisher_artifact", "sha256"]),
        "invalid_manifest_count": (
            "minimum",
            ["partition_row_counts", "product=level/year=2024"],
        ),
        "invalid_disposition_reconstructible_without_rule": (
            "required",
            ["source_column_dispositions", 6],
        ),
        "invalid_disposition_discard_without_rationale": (
            "required",
            ["source_column_dispositions", 6],
        ),
    }
    for name, pair in expected.items():
        errors = _raw_errors(_load_json(FIXTURES / name / "manifest.json"))
        assert [(error.validator, list(error.absolute_path)) for error in errors] == [pair]
    semantic = set(INVALID_DEFECTS) - set(expected)
    for name in semantic:
        assert _raw_errors(_load_json(FIXTURES / name / "manifest.json")) == []


def _repair(name: str, store: Path) -> None:
    valid = FIXTURES / "valid_future_austria"
    if name == "invalid_partition_path":
        source = _part(store)
        destination = store / "product=level/year=2024/part-0.parquet"
        destination.parent.mkdir(parents=True)
        source.rename(destination)
        source.parent.rmdir()
        return
    if name == "invalid_value_state_combination":
        _rewrite_row(_part(store), 0, value_state="published_value")
        return
    manifest = _load_json(store / "manifest.json")
    valid_manifest = _load_json(valid / "manifest.json")
    if name == "invalid_manifest_required_field":
        manifest["built_at"] = valid_manifest["built_at"]
    elif name == "invalid_manifest_type":
        manifest["compiler_version"] = valid_manifest["compiler_version"]
    elif name == "invalid_manifest_version":
        manifest["format_version"] = 5
    elif name == "invalid_manifest_checksum":
        manifest["publisher_artifact"]["sha256"] = valid_manifest["publisher_artifact"]["sha256"]
    elif name == "invalid_manifest_fingerprint":
        manifest["source_schema"]["fingerprint"] = FINGERPRINT
    elif name in {"invalid_manifest_count", "invalid_partition_row_count"}:
        manifest["partition_row_counts"]["product=level/year=2024"] = 1
    elif name == "invalid_partition_key":
        manifest["partition_row_counts"] = {"product=level/year=2024": 1}
    elif name in {
        "invalid_disposition_incomplete",
        "invalid_disposition_duplicate",
        "invalid_disposition_reconstructible_without_rule",
        "invalid_disposition_discard_without_rationale",
    }:
        manifest["source_column_dispositions"] = valid_manifest["source_column_dispositions"]
    else:
        raise AssertionError(name)
    _write_json(store / "manifest.json", manifest)


@pytest.mark.parametrize("name", list(INVALID_DEFECTS))
def test_each_invalid_fixture_becomes_valid_when_its_single_defect_is_repaired(name: str, tmp_path: Path) -> None:
    store = _copy_fixture(name, tmp_path)
    _repair(name, store)
    assert inspect_store(store, FUTURE_UNIVERSE) == []


def test_pinned_partition_pruning() -> None:
    pattern = str(FIXTURES / "valid_hydat_national/product=*/year=*/*.parquet")
    actual = (
        pl.scan_parquet(pattern, hive_partitioning=True)
        .filter((pl.col("product") == "discharge") & (pl.col("year") == 2024) & (pl.col("station_id") == "ca-002"))
        .collect()
    )
    expected = pl.DataFrame(
        [
            (
                "ca-002",
                datetime(2024, 1, 1, 1),
                "America/Vancouver",
                None,
                "published_blank",
                "m3/s",
                None,
                "source field was empty text",
                "discharge",
                2024,
            )
        ],
        schema=NATIVE_PHYSICAL_SCHEMA | pl.Schema({"product": pl.String, "year": pl.Int64}),
        orient="row",
    )
    assert_frame_equal(actual.select(expected.columns), expected)
    assert actual.schema["product"] == pl.String
    assert actual.schema["year"] == pl.Int64


def test_partition_pruning_control_selects_a_known_other_partition() -> None:
    pattern = str(FIXTURES / "valid_hydat_national/product=*/year=*/*.parquet")
    scan = pl.scan_parquet(pattern, hive_partitioning=True)
    actual = scan.filter(
        (pl.col("product") == "level") & (pl.col("year") == 2024) & (pl.col("station_id") == "ca-001")
    ).collect()
    expected = pl.DataFrame(
        [("ca-001", datetime(2024, 1, 1), "America/Toronto", 1.25, "published_value", "m", "A", None, "level", 2024)],
        schema=NATIVE_PHYSICAL_SCHEMA | pl.Schema({"product": pl.String, "year": pl.Int64}),
        orient="row",
    )
    assert_frame_equal(actual.select(expected.columns), expected)
    assert scan.filter(pl.col("product") == "temperature").collect().is_empty()


def test_imgw_hydrological_archive_spans_adjacent_calendar_partitions() -> None:
    store = FIXTURES / "valid_yearly_archives"
    frames = [pl.read_parquet(path) for path in sorted(store.rglob("*.parquet"))]
    expected = [
        pl.DataFrame(
            [
                (
                    "pl-001",
                    datetime(2023, 12, 31, 6),
                    "unknown",
                    7.25,
                    "published_value",
                    "m3/s",
                    "provisional",
                    "codz_2024 November-December side",
                )
            ],
            schema=NATIVE_PHYSICAL_SCHEMA,
            orient="row",
        ),
        pl.DataFrame(
            [
                (
                    "pl-001",
                    datetime(2024, 1, 1, 6),
                    "unknown",
                    7.5,
                    "published_value",
                    "m3/s",
                    "approved",
                    "codz_2024 January-October side",
                )
            ],
            schema=NATIVE_PHYSICAL_SCHEMA,
            orient="row",
        ),
    ]
    for actual, wanted in zip(frames, expected, strict=True):
        assert_frame_equal(actual.select(wanted.columns), wanted)
    manifest = _load_json(store / "manifest.json")
    assert manifest["publisher_artifact"]["url"] == "https://example.invalid/imgw/codz_2024.zip"
    assert [frame["time"][0].year for frame in frames] == [2023, 2024]


def test_four_value_states_are_physically_distinguishable() -> None:
    # Pin this shared value-state encoding exactly: stored rows carry a `value_state` column whose exact token set is `published_null`, `published_blank`, and `published_value`; no record is represented by row absence within a declared station-product-day case universe.
    store = FIXTURES / "valid_hydat_national"
    rows = []
    physical_cases = set()
    for path in sorted(store.rglob("*.parquet")):
        match = PARTITION_PATTERN.fullmatch(path.relative_to(store).as_posix())
        assert match is not None
        for row in pl.read_parquet(path).iter_rows(named=True):
            rows.append((row["value_state"], row["value"]))
            physical_cases.add(Case(row["station_id"], match.group("product"), row["time"].date()))
    assert set(rows) == {
        ("published_value", 3.5),
        ("published_value", 1.25),
        ("published_null", None),
        ("published_blank", None),
    }
    assert set(CASE_UNIVERSES["valid_hydat_national"]) - physical_cases == {Case("ca-002", "level", date(2024, 1, 1))}
    for path in FIXTURES.glob("*/manifest.json"):
        assert "case_universe" not in _load_json(path)
    assert all("no_record" not in str(row) for row in rows)


def test_value_state_detector_control(tmp_path: Path) -> None:
    source = FIXTURES / "valid_hydat_national"
    for path in sorted(source.rglob("*.parquet")):
        relative = path.relative_to(source)
        identifier = relative.parent.as_posix()
        frame = pl.read_parquet(path)
        for row_index, row in enumerate(frame.iter_rows(named=True)):
            store = tmp_path / identifier.replace("/", "-") / str(row_index)
            shutil.copytree(source, store)
            target = store / relative
            updates = {"value": None} if row["value"] is not None else {"value": 1.0}
            _rewrite_row(target, row_index, **updates)
            assert inspect_store(store, CASE_UNIVERSES["valid_hydat_national"]) == [
                f"value_state.combination:{identifier}:row={row_index}"
            ]


def test_native_physics_time_zones_and_source_columns_survive() -> None:
    stores = [FIXTURES / name for name in ["valid_hydat_national", "valid_yearly_archives", "valid_future_austria"]]
    actual = pl.concat([pl.read_parquet(path) for store in stores for path in sorted(store.rglob("*.parquet"))])
    expected_rows = [
        (
            "ca-001",
            datetime(2023, 12, 31, 23),
            "America/Toronto",
            3.5,
            "published_value",
            "m3/s",
            "A",
            "national database row",
        ),
        (
            "ca-001",
            datetime(2024, 1, 1),
            "America/Toronto",
            None,
            "published_null",
            "m3/s",
            "E",
            "source published SQL NULL",
        ),
        (
            "ca-002",
            datetime(2024, 1, 1, 1),
            "America/Vancouver",
            None,
            "published_blank",
            "m3/s",
            None,
            "source field was empty text",
        ),
        ("ca-001", datetime(2024, 1, 1), "America/Toronto", 1.25, "published_value", "m", "A", None),
        (
            "pl-001",
            datetime(2023, 12, 31, 6),
            "unknown",
            7.25,
            "published_value",
            "m3/s",
            "provisional",
            "codz_2024 November-December side",
        ),
        (
            "pl-001",
            datetime(2024, 1, 1, 6),
            "unknown",
            7.5,
            "published_value",
            "m3/s",
            "approved",
            "codz_2024 January-October side",
        ),
        (
            "at-001",
            datetime(2024, 1, 2, 7, 30),
            "Europe/Vienna",
            152.4,
            "published_value",
            "cm",
            "checked",
            "future-source-only text",
        ),
    ]
    assert_frame_equal(
        actual.select(NATIVE_PHYSICAL_SCHEMA.names()),
        pl.DataFrame(expected_rows, schema=NATIVE_PHYSICAL_SCHEMA, orient="row"),
    )
    assert actual.schema["time"] == pl.Datetime("us")
    assert set(actual["native_unit"]) == {"m3/s", "m", "cm"}
    # Pin this shared source-column disposition record exactly: each record has `source_column`, a `disposition` drawn from exactly `retained`, `reconstructible`, and `deliberately_discarded`, `reconstruction_rule` containing the reconstruction rule and required when and only when the disposition is `reconstructible`, and `rationale` required when and only when the disposition is `deliberately_discarded`; completeness means every source column of the declared source schema appears exactly once.


def test_store_accepts_additional_provider_native_column(tmp_path: Path) -> None:
    store = _copy_fixture("valid_future_austria", tmp_path)
    part = _part(store)
    pl.read_parquet(part).with_columns(pl.lit("AB").alias("source_flag")).write_parquet(
        part, compression="zstd", statistics=True
    )
    manifest = _load_json(store / "manifest.json")
    manifest["source_schema"]["columns"].append({"name": "source_flag", "type": "string"})
    manifest["source_schema"]["fingerprint"] = _fingerprint(manifest["source_schema"]["columns"])
    manifest["source_column_dispositions"].append({"source_column": "source_flag", "disposition": "retained"})
    _write_json(store / "manifest.json", manifest)

    assert inspect_store(store, FUTURE_UNIVERSE) == []


def test_store_accepts_only_required_physical_columns(tmp_path: Path) -> None:
    store = _copy_fixture("valid_future_austria", tmp_path)
    part = _part(store)
    required_names = ["station_id", "time", "time_zone", "value", "value_state", "series_id", "facts_id", "source_unit"]
    pl.read_parquet(part).select(required_names).write_parquet(part, compression="zstd", statistics=True)
    manifest = _load_json(store / "manifest.json")
    source_names = {"station_id", "time", "time_zone", "value"}
    manifest["source_schema"]["columns"] = [
        column for column in manifest["source_schema"]["columns"] if column["name"] in source_names
    ]
    manifest["source_schema"]["fingerprint"] = _fingerprint(manifest["source_schema"]["columns"])
    manifest["source_column_dispositions"] = [
        disposition
        for disposition in manifest["source_column_dispositions"]
        if disposition["source_column"] in source_names
    ]
    _write_json(store / "manifest.json", manifest)

    assert inspect_store(store, FUTURE_UNIVERSE) == []


def test_retyped_required_column_is_partition_schema_defect(tmp_path: Path) -> None:
    store = _copy_fixture("valid_future_austria", tmp_path)
    part = _part(store)
    pl.read_parquet(part).with_columns(pl.col("value").cast(pl.Float32)).write_parquet(
        part, compression="zstd", statistics=True
    )

    assert inspect_store(store, FUTURE_UNIVERSE) == ["partition.schema:product=level/year=2024"]
