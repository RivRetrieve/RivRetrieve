"""StoreReader : StoreQuery → StoreReadResult ⊎ StoreRefusal."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve._internal.store.validation as validation
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.store import (
    ObservationStoreRefusedError,
    StorePresence,
    StoreQuery,
    StoreReader,
    StoreRoot,
)
from rivretrieve._internal.store.integrity import seal_store
from rivretrieve._internal.store.validation import StoreManifest

FIXTURES = Path(__file__).parents[1] / "test_data" / "source_series_store_conformance"


def _published(tmp_path: Path, name: str = "valid_hydat_national") -> Path:
    """Publish a synthetic semantic fixture with a local content identity."""
    store = tmp_path / name
    shutil.copytree(FIXTURES / name, store)
    seal_store(StoreRoot(store), ProviderId("fixture_bulk"))
    return store


def _query(store: Path, *, station: str = "ca-001", product: str = "discharge") -> StoreQuery:
    return StoreQuery(
        store=StoreRoot(store.resolve()),
        provider_id=ProviderId("fixture_bulk"),
        stations=(station,),
        products=(ProductId(product),),
        start=datetime(2023, 1, 1),
        end=datetime(2024, 12, 31, 23, 59, 59),
    )


def test_unknown_revision_is_refused_before_a_partition_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "store"
    shutil.copytree(FIXTURES / "valid_hydat_national", store)
    manifest_path = store / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 87
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    parquet_opened = False

    def forbidden_open(_path: Path) -> object:
        nonlocal parquet_opened
        parquet_opened = True
        raise AssertionError("Parquet must not be opened for an unknown manifest revision")

    monkeypatch.setattr(validation, "_open_parquet", forbidden_open)
    with pytest.raises(ObservationStoreRefusedError) as raised:
        StoreReader().query(_query(store))

    assert not parquet_opened
    assert raised.value.refusal.defect == "unsupported format revision 87"
    assert 'rivretrieve.download("fixture_bulk")' in str(raised.value)


def test_reader_projects_native_rows_and_keeps_physical_value_state(tmp_path: Path) -> None:
    store = _published(tmp_path)
    result = StoreReader().query(_query(store))

    assert result.rows.columns == [
        "station_id",
        "product_id",
        "time",
        "value",
        "time_zone",
        "series_id",
        "facts_id",
        "source_unit",
    ]
    assert result.rows["value"].to_list() == [3.5, None]
    assert result.physical_rows["value_state"].to_list() == ["published_value", "published_null"]
    assert result.physical_rows["source_quality"].to_list() == ["A", "E"]
    assert result.executed_query.products == (ProductId("discharge"),)
    assert result.executed_query.years == (2023, 2024)


def test_reader_preserves_duplicate_source_rows(tmp_path: Path) -> None:
    store = _published(tmp_path, "valid_source_duplicates")
    result = StoreReader().query(
        StoreQuery(
            store=StoreRoot(store.resolve()),
            provider_id=ProviderId("fixture_bulk"),
            stations=("at-001",),
            products=(ProductId("level"),),
            start=datetime(2024, 1, 1),
            end=datetime(2024, 12, 31),
        )
    )
    assert result.physical_rows.height == 2
    assert result.physical_rows.drop("product", "year").row(0) == result.physical_rows.drop("product", "year").row(1)


def test_status_reports_absence_or_validated_manifest_facts(tmp_path: Path) -> None:
    reader = StoreReader()
    missing = StoreRoot((tmp_path / "missing").resolve())
    absent = reader.status(missing, ProviderId("fixture_bulk"))
    assert absent.presence is StorePresence.ABSENT
    assert not absent.exists
    assert absent.source_vintage is None
    assert absent.partition_row_counts == {}

    store = StoreRoot(_published(tmp_path).resolve())
    present = reader.status(store, ProviderId("fixture_bulk"))
    assert present.presence is StorePresence.PRESENT
    assert present.exists
    assert present.format_version == 5
    assert present.manifest is not None
    assert isinstance(present.manifest, StoreManifest)
    assert present.compiler_version == present.manifest.compiler_version
    assert present.source_vintage is not None
    assert str(present.publisher_artifact_checksum).startswith("sha256:")
    assert present.partition_row_counts


def test_empty_query_result_has_engine_rows_schema(tmp_path: Path) -> None:
    result = StoreReader().query(_query(_published(tmp_path), station="not-present"))
    assert result.rows.schema == {
        "station_id": pl.String,
        "product_id": pl.String,
        "time": pl.Datetime("us"),
        "value": pl.Float64,
        "time_zone": pl.String,
        "series_id": pl.String,
        "facts_id": pl.String,
        "source_unit": pl.String,
    }


@pytest.mark.parametrize(
    ("station", "product", "start", "end", "expected"),
    [
        (
            "ca-002",
            "discharge",
            "2024-01-01",
            "2024-01-01T01:00:00",
            [("2024-01-01T01:00:00", "America/Vancouver", None, "published_blank", None)],
        ),
        (
            "ca-001",
            "level",
            "2024-01-01",
            "2024-01-01T23:59:59",
            [("2024-01-01T00:00:00", "America/Toronto", 1.25, "published_value", "A")],
        ),
        (
            "ca-001",
            "discharge",
            "2023-12-31T23:00:00",
            "2024-01-01T00:00:00",
            [
                ("2023-12-31T23:00:00", "America/Toronto", 3.5, "published_value", "A"),
                ("2024-01-01T00:00:00", "America/Toronto", None, "published_null", "E"),
            ],
        ),
        ("ca-002", "discharge", "2024-01-01", "2024-01-01T00:59:59.999999", []),
    ],
    ids=["station", "product", "adjacent-years-closed-bounds", "before-row"],
)
def test_reader_filters_rows_by_identity_and_closed_time_bounds(station, product, start, end, expected, tmp_path):
    from polars.testing import assert_frame_equal

    query = StoreQuery(
        store=StoreRoot(_published(tmp_path).resolve()),
        provider_id=ProviderId("fixture_bulk"),
        stations=(station,),
        products=(ProductId(product),),
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
    )
    result = StoreReader().query(query)
    frame = pl.DataFrame(
        [(datetime.fromisoformat(time), zone, value, state, quality) for time, zone, value, state, quality in expected],
        schema={
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "value": pl.Float64,
            "value_state": pl.String,
            "source_quality": pl.String,
        },
        orient="row",
    )
    assert_frame_equal(result.physical_rows.select(frame.columns), frame)


def test_small_read_hashes_only_candidate_partitions_without_full_decode(tmp_path, monkeypatch):
    from rivretrieve._internal.store import integrity

    store = _published(tmp_path)
    digested = []
    original_digest = integrity._digest

    def digest(path):
        digested.append(path.relative_to(store).as_posix())
        return original_digest(path)

    def unrelated_decode(path):
        raise AssertionError(f"Read must not run whole-partition semantic decoding: {path}")

    monkeypatch.setattr(integrity, "_digest", digest)
    monkeypatch.setattr(validation, "_open_parquet", unrelated_decode)
    query = StoreQuery(
        StoreRoot(store),
        ProviderId("fixture_bulk"),
        ("ca-001",),
        (ProductId("discharge"),),
        datetime(2023, 12, 31),
        datetime(2023, 12, 31, 23, 59, 59),
    )
    result = StoreReader().query(query)
    assert result.rows["value"].to_list() == [3.5]
    assert [name for name in digested if name.endswith(".parquet")] == ["product=discharge/year=2023/data.parquet"]


def test_request_reader_shares_metadata_and_hashes_between_station_queries(tmp_path, monkeypatch):
    from rivretrieve._internal.store import integrity

    store = _published(tmp_path)
    inspections = []
    digested = []
    original_inspect, original_digest = integrity.inspect_integrity, integrity._digest

    def inspect(*args, **kwargs):
        inspections.append(args[0])
        return original_inspect(*args, **kwargs)

    def digest(path):
        digested.append(path)
        return original_digest(path)

    monkeypatch.setattr(integrity, "inspect_integrity", inspect)
    monkeypatch.setattr(integrity, "_digest", digest)
    reader = StoreReader()
    reader.status(StoreRoot(store), ProviderId("fixture_bulk"))
    first = reader.query(_query(store))
    second = reader.query(_query(store, station="ca-002"))
    assert first.rows.height == 2
    assert second.rows.height == 1
    assert len(inspections) == 1
    assert len([path for path in digested if path.suffix == ".parquet"]) == 2


@pytest.mark.parametrize("selected", [False, True])
def test_selected_byte_detection_and_full_audit_have_different_scopes(tmp_path, selected):
    import os

    from rivretrieve._internal.store.integrity import audit_store

    store = _published(tmp_path)
    reader = StoreReader()
    query = _query(store, product="level")
    assert reader.query(query).rows["value"].to_list() == [1.25]
    product = "level" if selected else "discharge"
    path = store / f"product={product}/year=2024/data.parquet"
    before = path.stat()
    content = bytearray(path.read_bytes())
    content[len(content) // 2] ^= 1
    path.write_bytes(content)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    if selected:
        with pytest.raises(ObservationStoreRefusedError, match="digest"):
            reader.query(query)
    else:
        assert reader.query(query).rows["value"].to_list() == [1.25]
    with pytest.raises(ObservationStoreRefusedError, match="digest"):
        audit_store(StoreRoot(store), ProviderId("fixture_bulk"))


def test_prepared_reader_refuses_generation_replacement_until_invalidated(tmp_path):
    store = _published(tmp_path)
    reader = StoreReader()
    query = _query(store, product="level")
    assert reader.query(query).rows["value"].to_list() == [1.25]
    part = store / "product=level/year=2024/data.parquet"
    pl.read_parquet(part).with_columns(pl.lit(2.5).alias("value")).write_parquet(part)
    # An independently published valid replacement must not silently be mixed
    # with request metadata from the preceding generation.
    (store / "integrity.json").unlink()
    seal_store(StoreRoot(store), ProviderId("fixture_bulk"))
    with pytest.raises(ObservationStoreRefusedError, match="generation_changed"):
        reader.query(query)
    reader.invalidate()
    assert reader.query(query).rows["value"].to_list() == [2.5]


@pytest.mark.parametrize("unrelated_rows", [10, 100])
def test_native_scan_decodes_only_matching_row_groups(tmp_path, monkeypatch, capfd, unrelated_rows):
    import re

    from rivretrieve._internal.store import integrity

    store = _published(tmp_path)
    part = store / "product=discharge/year=2024/data.parquet"
    physical = pl.read_parquet(part)
    expanded = pl.concat(
        [
            physical.filter(pl.col("station_id") == "ca-001"),
            *[physical.filter(pl.col("station_id") == "ca-002")] * unrelated_rows,
        ]
    )
    expanded.write_parquet(part, row_group_size=1, statistics=True)
    manifest_path = store / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["partition_row_counts"]["product=discharge/year=2024"] = expanded.height
    manifest_path.write_text(json.dumps(manifest))
    (store / "integrity.json").unlink()
    seal_store(StoreRoot(store), ProviderId("fixture_bulk"))
    hashes = []
    original = integrity._digest

    def digest(path):
        if path.suffix == ".parquet":
            hashes.append(path)
        return original(path)

    monkeypatch.setattr(integrity, "_digest", digest)
    monkeypatch.setattr(validation, "_open_parquet", lambda path: pytest.fail("unpruned semantic decoding"))
    capfd.readouterr()
    # Native execution telemetry counts physical Parquet row groups, not a
    # lazy-plan string. Only its numerical read/total event is inspected.
    with pl.Config(verbose=True):
        result = StoreReader().query(
            StoreQuery(
                StoreRoot(store),
                ProviderId("fixture_bulk"),
                ("ca-001",),
                (ProductId("discharge"),),
                datetime(2024, 1, 1),
                datetime(2024, 1, 2),
            )
        )
    diagnostics = capfd.readouterr().err
    assert result.rows["value"].to_list() == [None]
    assert result.physical_rows["source_quality"].to_list() == ["E"]
    assert hashes == [part]
    decoded = re.findall(r"Predicate pushdown: reading (\d+) / (\d+) row groups", diagnostics)
    assert decoded == [("1", str(unrelated_rows + 1))]


def test_prepared_reader_detects_valid_changed_value_with_restored_mtime(tmp_path):
    import os
    import struct

    import pyarrow.parquet as pq

    store = _published(tmp_path)
    part = store / "product=level/year=2024/data.parquet"
    table = pq.ParquetFile(part).read()
    pq.write_table(table, part, compression="NONE", use_dictionary=False, write_statistics=False)
    (store / "integrity.json").unlink()
    seal_store(StoreRoot(store), ProviderId("fixture_bulk"))
    reader = StoreReader()
    query = _query(store, product="level")
    assert reader.query(query).rows["value"].to_list() == [1.25]
    before = part.stat()
    content = part.read_bytes()
    original = struct.pack("<d", 1.25)
    assert content.count(original) == 1
    part.write_bytes(content.replace(original, struct.pack("<d", 99.0)))
    os.utime(part, ns=(before.st_atime_ns, before.st_mtime_ns))
    # The changed bytes still decode to a well-typed valid native observation.
    # Semantic/schema validation alone cannot detect this altered measurement.
    assert pl.read_parquet(part)["value"].to_list() == [99.0]
    assert reader.status(StoreRoot(store), ProviderId("fixture_bulk")).exists
    with pytest.raises(ObservationStoreRefusedError, match="digest"):
        reader.query(query)


@pytest.mark.parametrize("unrelated_rows", [10, 100])
def test_accumulated_scan_prunes_unrequested_time_row_groups(tmp_path, monkeypatch, capfd, unrelated_rows):
    import re

    from rivretrieve._internal.store import integrity

    store = tmp_path / "live"
    shutil.copytree(FIXTURES / "accumulated/valid_native_rows", store)
    part = next(store.rglob("*.parquet"))
    physical = pl.read_parquet(part)
    expected = physical.filter(pl.col("time") == datetime(2020, 1, 1))
    unrelated = physical.filter(pl.col("time") == datetime(2020, 1, 2))
    expanded = pl.concat([expected, *[unrelated] * unrelated_rows])
    expanded.write_parquet(part, row_group_size=1, statistics=True)
    manifest_path = store / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["partition_row_counts"]["product=level/year=2020"] = expanded.height
    manifest_path.write_text(json.dumps(manifest))
    seal_store(StoreRoot(store), ProviderId("fixture_live"))
    hashes = []
    original = integrity._digest

    def digest(path):
        if path.suffix == ".parquet":
            hashes.append(path)
        return original(path)

    monkeypatch.setattr(integrity, "_digest", digest)
    monkeypatch.setattr(validation, "_open_parquet", lambda path: pytest.fail("unpruned semantic decoding"))
    capfd.readouterr()
    with pl.Config(verbose=True):
        result = StoreReader().query(
            StoreQuery(
                StoreRoot(store),
                ProviderId("fixture_live"),
                ("a",),
                (ProductId("level"),),
                datetime(2020, 1, 1),
                datetime(2020, 1, 1, 23, 59, 59),
            )
        )
    diagnostics = capfd.readouterr().err
    assert result.rows["value"].to_list() == [12.4, 12.4]
    assert hashes == [part]
    assert re.findall(r"Predicate pushdown: reading (\d+) / (\d+) row groups", diagnostics) == [
        ("2", str(unrelated_rows + 2))
    ]
