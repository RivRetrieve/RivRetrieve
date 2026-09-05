"""accumulated store conformance : Manifest × ParseRows × Coverage → NativeStoreEffects."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from polars.testing import assert_frame_equal

from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval, remainder
from rivretrieve._internal.engine import RowsSchema
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.store import ObservationStoreRefusedError, StoreQuery, StoreReader, StoreRoot, validate_store
from rivretrieve._internal.store.accumulation import accumulate
from rivretrieve._internal.store.validation import AccumulatedStoreManifest

_ROOT = Path(__file__).parents[1]
_FIXTURES = _ROOT / "tests/test_data/observation_store_conformance/accumulated"
_PROVIDER = ProviderId("fixture_live")
_PRODUCT = ProductId("level")
_T1 = datetime(2026, 9, 1, tzinfo=UTC)
_T2 = datetime(2026, 9, 2, tzinfo=UTC)


def _interval(start: str, end: str) -> RequestedInterval:
    return RequestedInterval(datetime.fromisoformat(start), datetime.fromisoformat(end))


def _coverage(start: str, end: str, retrieved: datetime = _T1, station: str = "a") -> CoverageInterval:
    return CoverageInterval(station, _PRODUCT, _interval(start, end), retrieved)


def _rows(times: list[datetime], values: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "station_id": ["a"] * len(times),
            "product_id": ["level"] * len(times),
            "time": times,
            "value": values,
            "time_zone": ["unknown"] * len(times),
        },
        schema=RowsSchema.polars_schema,
    )


def _read(store: Path) -> pl.DataFrame:
    return (
        StoreReader()
        .query(StoreQuery(StoreRoot(store), _PROVIDER, ("a",), (_PRODUCT,), datetime(2019, 1, 1), datetime(2022, 1, 1)))
        .rows
    )


def test_normative_schema_and_committed_conformance_stores() -> None:
    schema = json.loads((_ROOT / "src/rivretrieve/_internal/store/manifest.schema.json").read_text())["$defs"][
        "accumulated"
    ]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid = _FIXTURES / "valid_empty"
    document = json.loads((valid / "manifest.json").read_text())
    validator.validate(document)
    manifest = validate_store(StoreRoot(valid), _PROVIDER).manifest
    assert isinstance(manifest, AccumulatedStoreManifest)
    assert manifest.coverage[0].interval == _interval("2020-01-01", "2020-01-31T23:59:59.999999")
    assert_frame_equal(_read(valid), pl.DataFrame(schema=RowsSchema.polars_schema))
    invalid = _FIXTURES / "invalid_coverage_order"
    with pytest.raises(ObservationStoreRefusedError, match="coverage.interval:0"):
        validate_store(StoreRoot(invalid), _PROVIDER)
    physical = _FIXTURES / "valid_native_rows"
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
    accumulate(store, _PROVIDER, first, january)
    accumulate(store, _PROVIDER, second, february)
    assert_frame_equal(_read(store), pl.concat([first, second]))
    status = StoreReader().status(store, _PROVIDER)
    assert status.coverage == (january, february)
    assert status.bytes_on_disk == sum(path.stat().st_size for path in store.rglob("*") if path.is_file())
    physical = pl.read_parquet(next(store.rglob("*.parquet")))
    assert physical["value"].to_list() == [12.4, 12.4, None]
    accumulate(store, _PROVIDER, first.head(1), january)
    assert_frame_equal(_read(store), pl.concat([second, first.head(1)]))
    accumulate(store, _PROVIDER, first.clear(), january)
    assert_frame_equal(_read(store), second)
    assert StoreReader().status(store, _PROVIDER).coverage == (february, january)


def test_refresh_splits_coverage_with_original_retrieval_instants(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    empty = pl.DataFrame(schema=RowsSchema.polars_schema)
    accumulate(store, _PROVIDER, empty, _coverage("2020-01-01", "2020-01-31T23:59:59.999999"))
    accumulate(store, _PROVIDER, empty, _coverage("2020-01-10", "2020-01-20T23:59:59.999999", _T2))
    assert StoreReader().status(store, _PROVIDER).coverage == (
        _coverage("2020-01-01", "2020-01-09T23:59:59.999999"),
        _coverage("2020-01-21", "2020-01-31T23:59:59.999999"),
        _coverage("2020-01-10", "2020-01-20T23:59:59.999999", _T2),
    )


def test_failed_atomic_replacement_keeps_previous_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = StoreRoot(tmp_path / "store")
    rows = _rows([datetime(2020, 1, 1)], [12.4])
    coverage = _coverage("2020-01-01", "2020-01-31T23:59:59.999999")
    accumulate(store, _PROVIDER, rows, coverage)
    before = {p.relative_to(store): p.read_bytes() for p in store.rglob("*") if p.is_file()}
    rename = Path.rename

    def fail_publish(path: Path, target: Path) -> Path:
        if ".pending-" in path.name and target == store:
            raise OSError("controlled publish failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_publish)
    with pytest.raises(OSError, match="controlled publish failure"):
        accumulate(store, _PROVIDER, rows.clear(), coverage)
    assert {p.relative_to(store): p.read_bytes() for p in store.rglob("*") if p.is_file()} == before
    assert not list(tmp_path.glob(".store.*"))


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
    with pytest.raises(ObservationStoreRefusedError, match="coverage.overlap:1"):
        validate_store(StoreRoot(store), _PROVIDER)
    doc["format_version"] = 99
    path.write_text(json.dumps(doc))

    def forbidden_open(path: Path) -> None:
        pytest.fail(f"opened {path}")

    monkeypatch.setattr(validation, "_open_parquet", forbidden_open)
    with pytest.raises(ObservationStoreRefusedError, match="unsupported format revision 99"):
        _read(store)
