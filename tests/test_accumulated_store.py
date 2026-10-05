"""accumulated store conformance : Manifest × ParseRows × Coverage → NativeStoreEffects."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import polars as pl
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from polars.testing import assert_frame_equal

from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval, remainder
from rivretrieve._internal.engine import RowsSchema
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)
from rivretrieve._internal.store import ObservationStoreRefusedError, StoreQuery, StoreReader, StoreRoot, validate_store
from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate
from rivretrieve._internal.store.integrity import seal_store
from rivretrieve._internal.store.validation import AccumulatedStoreManifest

_ROOT = Path(__file__).parents[1]
_FIXTURES = _ROOT / "tests/test_data/source_series_store_conformance/accumulated"
_PROVIDER = ProviderId("fixture_live")
_PRODUCT = ProductId("level")
_T1 = datetime(2026, 9, 1, tzinfo=UTC)
_T2 = datetime(2026, 9, 2, tzinfo=UTC)


def _interval(start: str, end: str) -> RequestedInterval:
    return RequestedInterval(datetime.fromisoformat(start), datetime.fromisoformat(end))


def _coverage(start: str, end: str, retrieved: datetime = _T1, station: str = "a") -> CoverageInterval:
    return CoverageInterval(
        stable_id("controlled fixture", str(_PROVIDER), station, str(_PRODUCT)),
        _interval(start, end),
        retrieved,
        stable_id(start, end, retrieved.isoformat()),
    )


def _rows(times: list[datetime], values: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "station_id": ["a"] * len(times),
            "product_id": ["level"] * len(times),
            "time": times,
            "value": values,
            "time_zone": ["unknown"] * len(times),
            "series_id": [stable_id("controlled fixture", str(_PROVIDER), "a", str(_PRODUCT))] * len(times),
            "facts_id": [stable_id("controlled fixture", "level", "cm")] * len(times),
            "source_unit": ["cm"] * len(times),
        },
        schema=RowsSchema.polars_schema,
    )


def _rows_update(provider: ProviderId, rows: pl.DataFrame, coverage: CoverageInterval) -> StoreUpdate:
    facts = PhysicalFacts(
        facts_id=stable_id("controlled fixture", "level", "cm"),
        quantity=known("stage", "controlled fixture"),
        source_unit=known("cm", "controlled fixture"),
        normalized_unit="cm",
    )
    definition = SourceSeries(
        series_id=coverage.series_id,
        provider_id=str(provider),
        station_id="a",
        product_id="level",
        identity=SourceIdentity(namespace="controlled fixture", origin="mapping", evidence=("controlled fixture",)),
        facts=(facts,),
    )
    outcome = RetrievalOutcome(
        outcome_id=uuid4().hex,
        series_id=coverage.series_id,
        station_id="a",
        product_id="level",
        window=SeriesWindow(start=coverage.interval.start, end=coverage.interval.end),
        status=OutcomeStatus.EMPTY if rows.is_empty() else OutcomeStatus.SUCCESS,
        facts_ids=(facts.facts_id,),
        retrieved_at=coverage.retrieved_at,
    )
    coverage = CoverageInterval(coverage.series_id, coverage.interval, coverage.retrieved_at, outcome.outcome_id)
    return StoreUpdate((definition,), (), (outcome,), (SuccessfulReplacement(coverage, rows),))


def _accumulate_rows(store: StoreRoot, provider: ProviderId, rows: pl.DataFrame, coverage: CoverageInterval):
    return accumulate(store, provider, _rows_update(provider, rows, coverage))


def _coverage_shape(coverage):
    return tuple((item.series_id, item.interval, item.retrieved_at) for item in coverage)


def _read(store: Path) -> pl.DataFrame:
    return (
        StoreReader()
        .query(StoreQuery(StoreRoot(store), _PROVIDER, ("a",), (_PRODUCT,), datetime(2019, 1, 1), datetime(2022, 1, 1)))
        .rows
    )


def test_normative_schema_and_committed_conformance_stores(tmp_path: Path) -> None:
    schema = json.loads((_ROOT / "src/rivretrieve/_internal/store/manifest.schema.json").read_text())["$defs"][
        "accumulated"
    ]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid = tmp_path / "valid_empty"
    shutil.copytree(_FIXTURES / "valid_empty", valid)
    seal_store(StoreRoot(valid), _PROVIDER)
    document = json.loads((valid / "manifest.json").read_text())
    validator.validate(document)
    manifest = validate_store(StoreRoot(valid), _PROVIDER).manifest
    assert isinstance(manifest, AccumulatedStoreManifest)
    assert manifest.coverage[0].interval == _interval("2020-01-01", "2020-01-31T23:59:59.999999")
    assert_frame_equal(_read(valid), pl.DataFrame(schema=RowsSchema.polars_schema))
    invalid = _FIXTURES / "invalid_coverage_order"
    with pytest.raises(ObservationStoreRefusedError, match="coverage.interval:0"):
        validate_store(StoreRoot(invalid), _PROVIDER)
    physical = tmp_path / "valid_native_rows"
    shutil.copytree(_FIXTURES / "valid_native_rows", physical)
    seal_store(StoreRoot(physical), _PROVIDER)
    validator.validate(json.loads((physical / "manifest.json").read_text()))
    assert_frame_equal(_read(physical), _rows([datetime(2020, 1, 1)] * 2 + [datetime(2020, 1, 2)], [12.4, 12.4, None]))
    with pytest.raises(ObservationStoreRefusedError, match="value_state.combination"):
        validate_store(StoreRoot(_FIXTURES / "invalid_published_blank"), _PROVIDER)
    document["coverage"][0]["retrieved_at"] = "2026-09-06T11:00:00.000000"
    assert list(validator.iter_errors(document))


def test_closed_interval_remainder_preserves_single_microsecond_holes() -> None:
    whole = _interval("2020-01-01", "2020-12-31T23:59:59.999999")
    held = _interval("2020-01-01", "2020-06-30T23:59:59.999999")
    assert remainder(whole, (held,)) == (_interval("2020-07-01", "2020-12-31T23:59:59.999999"),)
    point = datetime(2020, 3, 1)
    assert remainder(
        whole,
        (
            RequestedInterval(whole.start, point - timedelta(microseconds=1)),
            RequestedInterval(point + timedelta(microseconds=1), whole.end),
        ),
    ) == (RequestedInterval(point, point),)
    assert remainder(whole, (whole,)) == ()


def test_accumulation_refresh_keeps_native_values_duplicates_and_other_windows(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    january = _coverage("2020-01-01", "2020-01-31T23:59:59.999999")
    february = _coverage("2020-02-01", "2020-02-29T23:59:59.999999", _T2)
    first = _rows([datetime(2020, 1, 1)] * 2, [12.4, 12.4])
    second = _rows([datetime(2020, 2, 1)], [None])
    _accumulate_rows(store, _PROVIDER, first, january)
    _accumulate_rows(store, _PROVIDER, second, february)
    assert_frame_equal(_read(store), pl.concat([first, second]))
    status = StoreReader().status(store, _PROVIDER)
    assert _coverage_shape(status.coverage) == _coverage_shape((january, february))
    assert status.bytes_on_disk == sum(path.stat().st_size for path in store.rglob("*") if path.is_file())
    physical = pl.read_parquet(next(store.rglob("*.parquet")))
    assert physical["value"].to_list() == [12.4, 12.4, None]
    _accumulate_rows(store, _PROVIDER, first.head(1), january)
    assert_frame_equal(_read(store), pl.concat([second, first.head(1)]))
    _accumulate_rows(store, _PROVIDER, first.clear(), january)
    assert_frame_equal(_read(store), second)
    assert _coverage_shape(StoreReader().status(store, _PROVIDER).coverage) == _coverage_shape((february, january))


def test_refresh_splits_coverage_with_original_retrieval_instants(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    empty = pl.DataFrame(schema=RowsSchema.polars_schema)
    _accumulate_rows(store, _PROVIDER, empty, _coverage("2020-01-01", "2020-01-31T23:59:59.999999"))
    _accumulate_rows(store, _PROVIDER, empty, _coverage("2020-01-10", "2020-01-20T23:59:59.999999", _T2))
    assert _coverage_shape(StoreReader().status(store, _PROVIDER).coverage) == _coverage_shape(
        (
            _coverage("2020-01-01", "2020-01-09T23:59:59.999999"),
            _coverage("2020-01-21", "2020-01-31T23:59:59.999999"),
            _coverage("2020-01-10", "2020-01-20T23:59:59.999999", _T2),
        )
    )


def test_failed_atomic_replacement_keeps_previous_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = StoreRoot(tmp_path / "store")
    rows = _rows([datetime(2020, 1, 1)], [12.4])
    coverage = _coverage("2020-01-01", "2020-01-31T23:59:59.999999")
    _accumulate_rows(store, _PROVIDER, rows, coverage)
    before = {p.relative_to(store): p.read_bytes() for p in store.rglob("*") if p.is_file()}
    rename = os.replace

    def fail_publish(path: Path, target: Path) -> None:
        if ".stage-" in Path(path).name and target == store:
            raise OSError("controlled publish failure")
        return rename(path, target)

    monkeypatch.setattr(os, "replace", fail_publish)
    with pytest.raises(OSError, match="controlled publish failure"):
        _accumulate_rows(store, _PROVIDER, rows.clear(), coverage)
    assert {p.relative_to(store): p.read_bytes() for p in store.rglob("*") if p.is_file()} == before
    assert [path.name for path in tmp_path.glob(".store.*")] == [".store.owner"]


def test_unknown_revision_and_overlapping_coverage_refuse_before_parquet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import rivretrieve._internal.store.validation as validation

    store = tmp_path / "store"
    shutil.copytree(_FIXTURES / "valid_empty", store)
    path = store / "manifest.json"
    doc = json.loads(path.read_text())
    doc["coverage"].append(doc["coverage"][0])
    path.write_text(json.dumps(doc))
    with pytest.raises(ObservationStoreRefusedError, match="coverage.overlap:"):
        validate_store(StoreRoot(store), _PROVIDER)
    doc["format_version"] = 99
    path.write_text(json.dumps(doc))

    def forbidden_open(path: Path) -> None:
        pytest.fail(f"opened {path}")

    monkeypatch.setattr(validation, "_open_parquet", forbidden_open)
    with pytest.raises(ObservationStoreRefusedError, match="unsupported format revision 99"):
        validate_store(StoreRoot(store), _PROVIDER)


def test_one_batch_reads_and_writes_affected_partition_once(tmp_path, monkeypatch):
    store = StoreRoot(tmp_path / "store")
    first = _rows([datetime(2020, 1, 1), datetime(2020, 2, 1)], [1.0, 2.0])
    _accumulate_rows(store, _PROVIDER, first, _coverage("2020-01-01", "2020-12-31"))
    additions = tuple(
        _rows_update(
            _PROVIDER,
            _rows([datetime(2020, month, 1)] * 2, [3.0, 3.0]),
            _coverage(f"2020-{month:02d}-01", f"2020-{month:02d}-28", _T2),
        )
        for month in (1, 2)
    )
    update = StoreUpdate(
        additions[0].series,
        (),
        tuple(item.outcomes[0] for item in additions),
        tuple(item.replacements[0] for item in additions),
    )
    read, write = pl.read_parquet, pl.DataFrame.write_parquet
    reads, writes = [], []

    def track_read(path, *args, **kwargs):
        reads.append(Path(path))
        return read(path, *args, **kwargs)

    def track_write(frame, path, *args, **kwargs):
        writes.append(Path(path))
        return write(frame, path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pl, "read_parquet", track_read)
        patch.setattr(pl.DataFrame, "write_parquet", track_write)
        accumulate(store, _PROVIDER, update)
    assert len(reads) == len(writes) == 1
    expected = pl.concat([item.replacements[0].rows for item in additions])
    assert_frame_equal(_read(store), expected)


def test_metadata_only_update_opens_no_observations_and_preserves_hardlink_identity(tmp_path, monkeypatch):
    import rivretrieve._internal.store.integrity as integrity
    import rivretrieve._internal.store.validation as validation

    store = StoreRoot(tmp_path / "store")
    _accumulate_rows(store, _PROVIDER, _rows([datetime(2020, 1, 1)], [1.0]), _coverage("2020-01-01", "2020-12-31"))
    path = next(store.rglob("*.parquet"))
    inode = path.stat().st_ino
    digest = integrity._digest

    def forbidden(*args, **kwargs):
        pytest.fail("Metadata-only update opened observation data")

    def metadata_digest(path):
        if path.suffix == ".parquet":
            forbidden()
        return digest(path)

    with monkeypatch.context() as patch:
        patch.setattr(pl, "read_parquet", forbidden)
        patch.setattr(pl.DataFrame, "write_parquet", forbidden)
        patch.setattr(validation, "_open_parquet", forbidden)
        patch.setattr(integrity, "_digest", metadata_digest)
        accumulate(store, _PROVIDER, StoreUpdate((), (), (), ()))
    assert next(store.rglob("*.parquet")).stat().st_ino == inode
    integrity.inspect_integrity(store, _PROVIDER)


def test_small_update_never_reads_unrelated_partition_and_bounds_support(tmp_path, monkeypatch):
    import rivretrieve._internal.store.integrity as integrity
    import rivretrieve._internal.store.validation as validation

    store = StoreRoot(tmp_path / "store")
    for year in (2020, 2021):
        _accumulate_rows(
            store, _PROVIDER, _rows([datetime(year, 1, 1)], [1.0]), _coverage(f"{year}-01-01", f"{year}-12-31")
        )
    unrelated = next((store / "product=level/year=2021").glob("*.parquet"))
    inode = unrelated.stat().st_ino
    digest, opened = integrity._digest, validation._open_parquet

    def check_digest(path):
        assert "year=2021" not in str(path)
        return digest(path)

    def check_open(path):
        assert "year=2021" not in str(path)
        return opened(path)

    with monkeypatch.context() as patch:
        patch.setattr(integrity, "_digest", check_digest)
        patch.setattr(validation, "_open_parquet", check_open)
        for _ in range(4):
            manifest = _accumulate_rows(
                store, _PROVIDER, _rows([datetime(2020, 1, 1)], [2.0]), _coverage("2020-01-01", "2020-12-31", _T2)
            )
    assert unrelated.stat().st_ino == inode
    assert len(manifest.outcomes) == len(manifest.coverage) == 2


def test_failed_linked_update_preserves_readable_previous_generation(tmp_path, monkeypatch):
    import rivretrieve._internal.store.integrity as integrity

    store = StoreRoot(tmp_path / "store")
    rows = _rows([datetime(2020, 1, 1)], [1.0])
    _accumulate_rows(store, _PROVIDER, rows, _coverage("2020-01-01", "2020-12-31"))
    write = Path.write_text
    failure = OSError("authored late metadata disk failure")

    def fail_manifest(path, *args, **kwargs):
        if path.name == "manifest.json" and ".stage-" in str(path):
            raise failure
        return write(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", fail_manifest)
        with pytest.raises(OSError) as caught:
            accumulate(store, _PROVIDER, StoreUpdate((), (), (), ()))
    assert caught.value is failure
    integrity.inspect_integrity(store, _PROVIDER)
    assert_frame_equal(_read(store), rows)


def test_compaction_cannot_hide_invalid_unreferenced_stage_outcome(tmp_path):
    store = StoreRoot(tmp_path / "store")
    update = _rows_update(_PROVIDER, _rows([datetime(2020, 1, 1)], [1.0]), _coverage("2020-01-01", "2020-12-31"))
    invalid = update.outcomes[0].model_copy(update={"facts_ids": ("unknown-fact",)})
    with pytest.raises(ObservationStoreRefusedError, match="outcome.facts"):
        accumulate(store, _PROVIDER, StoreUpdate(update.series, (), (invalid,), ()))
    assert not store.exists()


def test_failed_update_cannot_bless_preexisting_ctime_only_corruption(tmp_path):
    store = StoreRoot(tmp_path / "store")
    for year in (2019, 2020, 2021):
        _accumulate_rows(
            store, _PROVIDER, _rows([datetime(year, 1, 1)], [1.0]), _coverage(f"{year}-01-01", f"{year}-12-31")
        )
    partition = next((store / "product=level/year=2021").glob("*.parquet"))
    before = partition.stat()
    content = bytearray(partition.read_bytes())
    content[len(content) // 2] ^= 1
    partition.write_bytes(content)
    os.utime(partition, ns=(before.st_atime_ns, before.st_mtime_ns))
    seal = (store / "integrity.json").read_bytes()
    for _ in range(2):
        with pytest.raises(ObservationStoreRefusedError, match="digest"):
            # Reuse links healthy 2019 before encountering corrupt 2021.
            _accumulate_rows(
                store, _PROVIDER, _rows([datetime(2020, 1, 1)], [2.0]), _coverage("2020-01-01", "2020-12-31", _T2)
            )
        assert (store / "integrity.json").read_bytes() == seal
