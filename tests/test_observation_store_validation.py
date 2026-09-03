"""validate_store : StoreRoot × ProviderId → ValidatedStore ⊎ StoreRefusal."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

import rivretrieve._internal.store.validation as validation_module
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store import (
    ObservationStoreRefusedError,
    PartitionIdentifier,
    StoreManifest,
    StoreRefusalKind,
    StoreRoot,
    ValidatedStore,
    validate_store,
)

FIXTURES = Path(__file__).parent / "test_data" / "observation_store_conformance"
PROVIDER_ID = ProviderId("fixture_bulk")
EXPECTED = {
    "invalid_manifest_required_field": (StoreRefusalKind.MALFORMED, "manifest.required:built_at"),
    "invalid_manifest_type": (StoreRefusalKind.MALFORMED, "manifest.type:compiler_version"),
    "invalid_manifest_version": (
        StoreRefusalKind.INCOMPATIBLE,
        "unsupported format revision 3",
    ),
    "invalid_manifest_checksum": (
        StoreRefusalKind.MALFORMED,
        "manifest.pattern:publisher_artifact.sha256",
    ),
    "invalid_manifest_fingerprint": (
        StoreRefusalKind.MALFORMED,
        "source_schema.fingerprint",
    ),
    "invalid_manifest_count": (
        StoreRefusalKind.MALFORMED,
        "manifest.minimum:partition_row_counts.product=level/year=2024",
    ),
    "invalid_partition_path": (
        StoreRefusalKind.MALFORMED,
        "partition.path:product=level/year-2024/part-0.parquet",
    ),
    "invalid_partition_key": (
        StoreRefusalKind.MALFORMED,
        "partition.key:expected=['product=stage/year=2024'];actual=['product=level/year=2024']",
    ),
    "invalid_partition_row_count": (
        StoreRefusalKind.MALFORMED,
        "partition.row_count:product=level/year=2024:expected=2:actual=1",
    ),
    "invalid_value_state_combination": (
        StoreRefusalKind.MALFORMED,
        "value_state.combination:product=level/year=2024:row=0",
    ),
    "invalid_disposition_incomplete": (
        StoreRefusalKind.MALFORMED,
        "disposition.incomplete:missing=['source_note']:extra=[]",
    ),
    "invalid_disposition_duplicate": (
        StoreRefusalKind.MALFORMED,
        "disposition.duplicate:source_note",
    ),
    "invalid_disposition_reconstructible_without_rule": (
        StoreRefusalKind.MALFORMED,
        "disposition.reconstruction_rule:source_note",
    ),
    "invalid_disposition_discard_without_rationale": (
        StoreRefusalKind.MALFORMED,
        "disposition.rationale:source_note",
    ),
}


def _copy_fixture(tmp_path: Path, name: str = "valid_future_austria") -> Path:
    destination = tmp_path / name
    shutil.copytree(FIXTURES / name, destination)
    return destination.resolve()


def _manifest(store: Path) -> dict[str, object]:
    return json.loads((store / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(store: Path, manifest: dict[str, object]) -> None:
    (store / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _fingerprint(columns: list[dict[str, object]]) -> str:
    encoded = json.dumps(columns, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _only_parquet(store: Path) -> Path:
    paths = sorted(store.rglob("*.parquet"))
    assert len(paths) == 1
    return paths[0]


def _assert_refusal(store: Path, defect: str, kind: StoreRefusalKind = StoreRefusalKind.MALFORMED) -> None:
    with pytest.raises(ObservationStoreRefusedError) as raised:
        validate_store(StoreRoot(store), PROVIDER_ID)
    refusal = raised.value.refusal
    assert refusal.kind is kind
    assert refusal.store == StoreRoot(store)
    assert refusal.provider_id == PROVIDER_ID
    assert refusal.defect == defect
    assert refusal.rebuild_instruction == 'rivretrieve.download("fixture_bulk")'


def _validate_then_rewrite(store: Path, transform: object) -> None:
    assert isinstance(validate_store(StoreRoot(store), PROVIDER_ID), ValidatedStore)
    parquet = _only_parquet(store)
    frame = pl.read_parquet(parquet)
    assert callable(transform)
    transformed = transform(frame)
    assert isinstance(transformed, pl.DataFrame)
    transformed.write_parquet(parquet)


def test_discovered_fixture_inventory_exercises_the_production_seam() -> None:
    paths = {path.name: path for path in FIXTURES.iterdir() if path.is_dir()}
    valid_paths = {name: path for name, path in paths.items() if name.startswith("valid_")}
    invalid_paths = {name: path for name, path in paths.items() if name.startswith("invalid_")}
    assert paths.keys() == valid_paths.keys() | invalid_paths.keys()
    assert invalid_paths.keys() == EXPECTED.keys()
    print(f"discovered stores={len(paths)} valid={len(valid_paths)} invalid={len(invalid_paths)}")

    controlled_name = sorted(invalid_paths)[0]
    with pytest.raises(ObservationStoreRefusedError) as controlled_refusal:
        validate_store(StoreRoot(invalid_paths[controlled_name].resolve()), PROVIDER_ID)
    sentinel_expected = dict(EXPECTED)
    sentinel_expected[controlled_name] = (sentinel_expected[controlled_name][0], "deterministic-control-sentinel")
    with pytest.raises(AssertionError, match=f"CONTROL defect mismatch: {controlled_name}"):
        assert controlled_refusal.value.refusal.defect == sentinel_expected[controlled_name][1], (
            f"CONTROL defect mismatch: {controlled_name}"
        )

    for _name, path in sorted(valid_paths.items()):
        resolved = path.resolve()
        result = validate_store(StoreRoot(resolved), PROVIDER_ID)
        assert isinstance(result, ValidatedStore)
        assert result.root == StoreRoot(resolved)
        assert isinstance(result.manifest, StoreManifest)
        assert result.manifest.format_version == 2
        assert result.manifest.built_at.utcoffset() is not None
        assert result.manifest.publisher_artifact.url.startswith("https://")
        expected_keys = {PartitionIdentifier(key) for key in _manifest(path)["partition_row_counts"]}
        assert result.partition_files.keys() == expected_keys
        for identifier, parquet_path in result.partition_files.items():
            assert parquet_path.parent.relative_to(resolved).as_posix() == identifier
            assert pq.ParquetFile(parquet_path).metadata.num_rows == result.manifest.partition_row_counts[identifier]
        with pytest.raises(TypeError):
            result.partition_files[PartitionIdentifier("product=x/year=2000")] = resolved  # type: ignore[index]
        with pytest.raises(TypeError):
            result.manifest.partition_row_counts[PartitionIdentifier("product=x/year=2000")] = 1  # type: ignore[index]
        with pytest.raises(FrozenInstanceError):
            result.manifest.compiler_version = "2.0"  # type: ignore[misc]
        assert any(len(pq.read_table(file)) > 0 for file in result.partition_files.values())

    duplicate = validate_store(StoreRoot(valid_paths["valid_source_duplicates"].resolve()), PROVIDER_ID)
    duplicate_file = next(iter(duplicate.partition_files.values()))
    duplicate_frame = pq.read_table(duplicate_file)
    assert pq.ParquetFile(duplicate_file).metadata.num_rows == len(pq.read_table(duplicate_file))
    assert len(duplicate_frame) == duplicate.manifest.partition_row_counts[next(iter(duplicate.partition_files))]
    assert duplicate_frame.slice(0, 1).equals(duplicate_frame.slice(1, 1))

    for name, path in sorted(invalid_paths.items()):
        with pytest.raises(ObservationStoreRefusedError) as raised:
            validate_store(StoreRoot(path.resolve()), PROVIDER_ID)
        refusal = raised.value.refusal
        assert refusal.store == StoreRoot(path.resolve())
        assert refusal.provider_id == PROVIDER_ID
        assert refusal.rebuild_instruction == 'rivretrieve.download("fixture_bulk")'
        assert refusal.kind == EXPECTED[name][0]
        assert refusal.defect == EXPECTED[name][1]


def test_compiler_version_does_not_grant_compatibility(tmp_path: Path) -> None:
    store = _copy_fixture(tmp_path)
    manifest = _manifest(store)
    manifest["compiler_version"] = "999!1.2.3rc4.post5.dev6+ordinary"
    _write_manifest(store, manifest)
    assert isinstance(validate_store(StoreRoot(store), PROVIDER_ID), ValidatedStore)

    manifest["compiler_version"] = "1.0"
    manifest["format_version"] = 72
    _write_manifest(store, manifest)
    _assert_refusal(store, "unsupported format revision 72", StoreRefusalKind.INCOMPATIBLE)


@pytest.mark.parametrize(
    ("payload", "defect"),
    [
        (b"\xff", "manifest.utf8:manifest.json"),
        (b"{", "manifest.json:syntax"),
        (b"[]", "manifest.root:type"),
    ],
)
def test_manifest_byte_and_root_refusals(tmp_path: Path, payload: bytes, defect: str) -> None:
    store = _copy_fixture(tmp_path)
    (store / "manifest.json").write_bytes(payload)
    _assert_refusal(store, defect)


def test_missing_manifest_and_duplicate_json_member_are_refused(tmp_path: Path) -> None:
    missing = _copy_fixture(tmp_path / "missing")
    (missing / "manifest.json").unlink()
    _assert_refusal(missing, "manifest.io:manifest.json")

    duplicate = _copy_fixture(tmp_path / "duplicate")
    text = (duplicate / "manifest.json").read_text(encoding="utf-8")
    text = text.replace('  "format_version": 2,', '  "format_version": 2,\n  "format_version": 2,', 1)
    (duplicate / "manifest.json").write_text(text, encoding="utf-8")
    _assert_refusal(duplicate, "manifest.json:duplicate:format_version")


def test_duplicate_source_name_with_different_type_is_refused(tmp_path: Path) -> None:
    store = _copy_fixture(tmp_path)
    manifest = _manifest(store)
    source_schema = manifest["source_schema"]
    assert isinstance(source_schema, dict)
    columns = source_schema["columns"]
    assert isinstance(columns, list)
    columns.append({"name": "source_note", "type": "int64"})
    source_schema["fingerprint"] = _fingerprint(columns)
    _write_manifest(store, manifest)
    _assert_refusal(store, "source_schema.duplicate:source_note")


def test_partition_file_cardinality_and_manifest_closure(tmp_path: Path) -> None:
    second = _copy_fixture(tmp_path / "second")
    parquet = _only_parquet(second)
    shutil.copyfile(parquet, parquet.with_name("another.parquet"))
    _assert_refusal(second, "partition.file_count:product=level/year=2024")

    empty = _copy_fixture(tmp_path / "empty")
    (empty / "product=empty" / "year=2024").mkdir(parents=True)
    _assert_refusal(empty, "partition.file_count:product=empty/year=2024")

    missing = _copy_fixture(tmp_path / "missing")
    shutil.rmtree(_only_parquet(missing).parent)
    _assert_refusal(
        missing,
        "partition.key:expected=['product=level/year=2024'];actual=[]",
    )

    extra = _copy_fixture(tmp_path / "extra")
    source = _only_parquet(extra)
    destination = extra / "product=stage" / "year=2024" / "arbitrary.parquet"
    destination.parent.mkdir(parents=True)
    shutil.copyfile(source, destination)
    _assert_refusal(
        extra,
        "partition.key:expected=['product=level/year=2024'];actual=['product=level/year=2024', "
        "'product=stage/year=2024']",
    )


def test_arbitrary_parquet_basename_and_native_columns_are_accepted(tmp_path: Path) -> None:
    store = _copy_fixture(tmp_path)
    original = _only_parquet(store)
    renamed = original.with_name("provider-chosen-name.parquet")
    original.rename(renamed)
    result = validate_store(StoreRoot(store), ProviderId("fixture_bulk"))
    assert isinstance(result, ValidatedStore)
    assert next(iter(result.partition_files.values())).name == renamed.name
    frame = pl.read_parquet(renamed)
    assert frame.columns[5:] == ["native_unit", "source_quality", "source_note"]


def test_missing_retained_native_column_is_refused(tmp_path: Path) -> None:
    """A store cannot omit a source column whose manifest promises retention."""
    store = _copy_fixture(tmp_path)
    _validate_then_rewrite(store, lambda frame: frame.drop("source_quality"))
    _assert_refusal(
        store,
        "partition.schema:product=level/year=2024",
    )


@pytest.mark.parametrize("column", ["station_id", "time", "time_zone", "value_state"])
def test_null_required_fields_are_refused(tmp_path: Path, column: str) -> None:
    store = _copy_fixture(tmp_path)
    dtype = {
        "station_id": pl.String,
        "time": pl.Datetime("us"),
        "time_zone": pl.String,
        "value_state": pl.String,
    }[column]
    _validate_then_rewrite(store, lambda frame: frame.with_columns(pl.lit(None, dtype=dtype).alias(column)))
    _assert_refusal(store, f"partition.nullability:product=level/year=2024:{column}")


@pytest.mark.parametrize(
    ("column", "expression"),
    [
        ("station_id", pl.lit(1, dtype=pl.Int64)),
        ("time", pl.lit(1, dtype=pl.Int64)),
        ("time_zone", pl.lit(1, dtype=pl.Int64)),
        ("value", pl.lit(1, dtype=pl.Int64)),
        ("value_state", pl.lit(1, dtype=pl.Int64)),
    ],
)
def test_each_wrong_required_physical_type_is_refused(tmp_path: Path, column: str, expression: pl.Expr) -> None:
    store = _copy_fixture(tmp_path)
    _validate_then_rewrite(store, lambda frame: frame.with_columns(expression.alias(column)))
    _assert_refusal(store, "partition.schema:product=level/year=2024")


@pytest.mark.parametrize(
    ("transform", "case"),
    [
        (lambda frame: frame.with_columns(pl.col("time").cast(pl.Datetime("ms"))), "millisecond time"),
        (
            lambda frame: frame.with_columns(pl.col("time").dt.replace_time_zone("UTC")),
            "time-zone-aware time",
        ),
        (
            lambda frame: frame.select("station_id", "time", "time_zone"),
            "prefix shorter than the five required fields",
        ),
        (lambda frame: frame.with_columns(pl.col("value").cast(pl.Float32)), "float32 value"),
        (
            lambda frame: frame.select(
                "station_id",
                "time",
                "time_zone",
                "value",
                "native_unit",
                "value_state",
                "source_quality",
                "source_note",
            ),
            "provider-native field before value_state",
        ),
    ],
)
def test_exact_physical_prefix_controls(tmp_path: Path, transform: object, case: str) -> None:
    store = _copy_fixture(tmp_path)
    _validate_then_rewrite(store, transform)
    _assert_refusal(store, "partition.schema:product=level/year=2024")
    assert case


def test_station_id_content_order_and_native_year(tmp_path: Path) -> None:
    empty = _copy_fixture(tmp_path / "empty")
    _validate_then_rewrite(empty, lambda frame: frame.with_columns(pl.lit("").alias("station_id")))
    _assert_refusal(empty, "partition.station_id:product=level/year=2024")

    disorder = _copy_fixture(tmp_path / "disorder", "valid_source_duplicates")
    _validate_then_rewrite(
        disorder,
        lambda frame: frame.with_columns(pl.Series("station_id", ["z-station", "a-station"])),
    )
    _assert_refusal(disorder, "partition.order:product=level/year=2024")

    wrong_year = _copy_fixture(tmp_path / "year")
    _validate_then_rewrite(
        wrong_year,
        lambda frame: frame.with_columns(pl.col("time").dt.offset_by("-1y")),
    )
    _assert_refusal(wrong_year, "partition.year:product=level/year=2024:row=0")


@pytest.mark.parametrize(
    ("state", "value"),
    [
        ("unknown_token", None),
        ("published_value", None),
        ("published_null", 1.0),
        ("published_blank", 1.0),
    ],
)
def test_every_illegal_value_state_pairing_is_refused(tmp_path: Path, state: str, value: float | None) -> None:
    store = _copy_fixture(tmp_path)
    _validate_then_rewrite(
        store,
        lambda frame: frame.with_columns(
            pl.lit(state, dtype=pl.String).alias("value_state"),
            pl.lit(value, dtype=pl.Float64).alias("value"),
        ),
    )
    _assert_refusal(store, "value_state.combination:product=level/year=2024:row=0")


def test_unknown_revision_precedes_the_single_parquet_open_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _copy_fixture(tmp_path)
    expected_paths = sorted(store.rglob("*.parquet"))
    manifest = _manifest(store)
    manifest["format_version"] = 99
    _write_manifest(store, manifest)
    for path in expected_paths:
        path.write_bytes(b"deterministic invalid parquet sentinel")

    opened: list[Path] = []
    original_open = validation_module._open_parquet

    def record_open(path: Path) -> pq.ParquetFile:
        opened.append(path)
        return original_open(path)

    monkeypatch.setattr(validation_module, "_open_parquet", record_open)
    _assert_refusal(store, "unsupported format revision 99", StoreRefusalKind.INCOMPATIBLE)
    assert opened == []

    manifest["format_version"] = 2
    _write_manifest(store, manifest)
    _assert_refusal(store, "partition.parquet:product=level/year=2024")
    assert opened == expected_paths
    assert len(opened) == len(expected_paths)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _assert_snapshots_equal(before: dict[str, str], after: dict[str, str]) -> None:
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    assert not changed, f"changed paths: {changed!r}"


def test_refusal_never_migrates_or_writes_and_digest_control_fires(tmp_path: Path) -> None:
    store = _copy_fixture(tmp_path, "invalid_value_state_combination")
    before = _snapshot(store)
    _assert_refusal(store, "value_state.combination:product=level/year=2024:row=0")
    _assert_snapshots_equal(before, _snapshot(store))

    control = _copy_fixture(tmp_path / "control", "invalid_value_state_combination")
    control_before = _snapshot(control)
    changed = control / "manifest.json"
    changed.write_bytes(changed.read_bytes() + b" ")
    with pytest.raises(AssertionError, match=r"changed paths: \['manifest.json'\]"):
        _assert_snapshots_equal(control_before, _snapshot(control))


def _forbidden_dependencies(source: str) -> list[str]:
    tree = ast.parse(source)
    findings: list[str] = []
    mutation_calls = {
        "write_text",
        "write_bytes",
        "write_parquet",
        "mkdir",
        "rename",
        "replace",
        "unlink",
        "rmdir",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            findings.extend(
                alias.name
                for alias in node.names
                if "rivretrieve._internal.transport" in alias.name or "rivretrieve._internal.providers" in alias.name
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "rivretrieve._internal.transport" in module or "rivretrieve._internal.providers" in module:
                findings.append(module)
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            attribute = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name in {"HttpClient", "download"} or attribute in {"HttpClient", "download"} | mutation_calls:
                findings.append(attribute or name or "")
    return findings


def test_store_import_closure_has_no_transport_provider_or_write_path() -> None:
    control = "from rivretrieve._internal.transport import HttpClient"
    with pytest.raises(AssertionError, match="CONTROL forbidden dependency: rivretrieve._internal.transport"):
        findings = _forbidden_dependencies(control)
        assert not findings, f"CONTROL forbidden dependency: {findings[0]}"

    store_source = Path(validation_module.__file__).parent
    read_modules = (store_source / "reader.py", store_source / "validation.py")
    findings = {path.name: _forbidden_dependencies(path.read_text(encoding="utf-8")) for path in read_modules}
    assert all(not file_findings for file_findings in findings.values()), findings


def test_fingerprint_canonical_encoding_sorts_keys_and_leaves_non_ascii_unescaped(tmp_path: Path) -> None:
    """The normative canonical encoding is key-sorted and does not escape non-ASCII."""
    reordered = _copy_fixture(tmp_path / "reordered")
    manifest = _manifest(reordered)
    source_schema = manifest["source_schema"]
    assert isinstance(source_schema, dict)
    columns = source_schema["columns"]
    assert isinstance(columns, list)
    rewritten = [{"type": column["type"], "name": column["name"]} for column in columns]
    assert [list(column) for column in rewritten] == [["type", "name"]] * len(rewritten)
    source_schema["columns"] = rewritten
    source_schema["fingerprint"] = _fingerprint(rewritten)
    _write_manifest(reordered, manifest)
    assert isinstance(validate_store(StoreRoot(reordered), PROVIDER_ID), ValidatedStore)

    non_ascii = _copy_fixture(tmp_path / "non_ascii")
    manifest = _manifest(non_ascii)
    source_schema = manifest["source_schema"]
    assert isinstance(source_schema, dict)
    columns = source_schema["columns"]
    assert isinstance(columns, list)
    dispositions = manifest["source_column_dispositions"]
    assert isinstance(dispositions, list)
    renamed = "niveau_r\u00e9f\u00e9rence"
    assert not renamed.isascii()
    columns[-1]["name"] = renamed
    old_name = dispositions[-1]["source_column"]
    dispositions[-1]["source_column"] = renamed
    source_schema["fingerprint"] = _fingerprint(columns)
    parquet_path = next(non_ascii.rglob("*.parquet"))
    pl.read_parquet(parquet_path).rename({old_name: renamed}).write_parquet(parquet_path)
    _write_manifest(non_ascii, manifest)
    assert isinstance(validate_store(StoreRoot(non_ascii), PROVIDER_ID), ValidatedStore)


def test_missing_format_version_is_refused_as_a_missing_required_field(tmp_path: Path) -> None:
    """A manifest without `format_version` is a missing required field, not a crash."""
    store = _copy_fixture(tmp_path)
    manifest = _manifest(store)
    del manifest["format_version"]
    _write_manifest(store, manifest)
    _assert_refusal(store, "manifest.required:format_version")


def test_mistyped_format_version_is_malformed_not_incompatible(tmp_path: Path) -> None:
    """A non-integer `format_version` is a mistyped required field, not an unknown revision."""
    store = _copy_fixture(tmp_path)
    manifest = _manifest(store)
    manifest["format_version"] = "1"
    _write_manifest(store, manifest)
    _assert_refusal(store, "manifest.type:format_version")


def test_non_object_source_column_disposition_is_malformed(tmp_path: Path) -> None:
    """A non-object disposition is malformed and never escapes the refusal boundary."""
    store = _copy_fixture(tmp_path)
    manifest = _manifest(store)
    manifest["source_column_dispositions"] = [42]
    _write_manifest(store, manifest)
    _assert_refusal(store, "manifest.not:source_column_dispositions.0")
