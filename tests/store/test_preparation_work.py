"""Deterministic preparation work and scratch bounds, without national inputs."""

import pytest

from rivretrieve._internal.providers.pl_imgw import bulk as imgw
from rivretrieve._internal.store import compiler
from tests.store.certification_support import artifact_and_request, rows


def test_imgw_reconciliation_keys_bound_repeated_path_storage() -> None:
    source = ("1", "S", "R", "2022", "03", "01", "100", "1", "2", "1")
    short = imgw._imgw_source_unit(0, 1, source)
    assert len(short.source_unit) == 84
    assert short.publisher_records == 1
    assert short.expected_emitted_rows == 3
    assert short != imgw._imgw_source_unit(1, 1, source)
    assert short != imgw._imgw_source_unit(0, 2, source)
    assert short != imgw._imgw_source_unit(0, 1, (*source[:-1], ""))


def test_reconciliation_journal_does_not_duplicate_text_keys(tmp_path, monkeypatch) -> None:
    from rivretrieve._internal.store import (
        NativeObservationBatch,
        ObservationBatchStream,
        SourceUnitContribution,
        SourceUnitCount,
        source_unit_inventory_fingerprint,
    )

    _artifact, request = artifact_and_request(tmp_path)
    original = compiler._record_source_units
    schemas = []

    def record(database, units):
        original(database, units)
        schemas.append(database.execute("SELECT sql FROM sqlite_master WHERE name='source_units'").fetchone()[0])

    monkeypatch.setattr(compiler, "_record_source_units", record)
    batch = NativeObservationBatch(rows(), (SourceUnitCount("one", 1, 1),), (SourceUnitContribution("one", 1),))
    compiler.compile_store_batches(
        request,
        ObservationBatchStream(
            request.source_columns,
            (batch,),
            1,
            1,
            source_unit_inventory_fingerprint((("one", 1, 1),)),
        ),
    )
    # A rowid table duplicates the TEXT key in its separate primary-key B-tree.
    assert schemas and all("WITHOUT ROWID" in schema for schema in schemas)


def test_imgw_selected_product_does_not_expand_other_cells(tmp_path, monkeypatch) -> None:
    import zipfile

    from rivretrieve._internal.primitives import ProductId

    artifact = tmp_path / "codz_2022_03.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("codz_2022_03.csv", "1;S;R;2022;03;01;100;1;2;1\r\n")
    original = imgw._native_value
    cells = []

    def decode(raw, *args):
        cells.append(raw)
        return original(raw, *args)

    monkeypatch.setattr(imgw, "_native_value", decode)
    emitted = list(imgw._iter_imgw_product_year(artifact, ProductId("discharge_daily"), 2022, 0))
    assert len(emitted) == 1
    assert emitted[0][1]["value"] == 1.0
    assert cells == ["1"]
    cells.clear()
    records, rows, _fingerprint = imgw._expected_imgw_inventory((artifact,))
    assert (records, rows) == (1, 3)
    assert sorted(cells) == ["1", "100", "2"]
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("codz_2022_03.csv", "1;S;R;2022;03;01;100;1;NaN;1\r\n")
    # A valid selected discharge cell cannot hide an invalid later product.
    with pytest.raises(ValueError, match="finite"):
        imgw.decode_imgw_batches(artifact)


@pytest.mark.parametrize("archive_count", [1, 4])
def test_imgw_sort_bounds_fetched_payloads_and_releases_insertion_tail(tmp_path, monkeypatch, archive_count) -> None:
    import pickle
    import sqlite3

    from rivretrieve._internal.store import SourceUnitCount

    monkeypatch.setattr(imgw, "IMGW_ROWS_PER_BATCH", 4)
    monkeypatch.setattr(imgw, "IMGW_SORT_ROWS_PER_FETCH", 2, raising=False)
    original_dumps = pickle.dumps
    live_payloads = []
    fetch_sizes = []

    class Payload(bytes):
        def __new__(cls, value):
            instance = super().__new__(cls, value)
            live_payloads.append(id(instance))
            return instance

        def __del__(self):
            live_payloads.remove(id(self))

    def dumps(*args, **kwargs):
        return Payload(original_dumps(*args, **kwargs))

    original_connect = sqlite3.connect

    class Cursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchmany(self, size):
            fetch_sizes.append(size)
            return self.cursor.fetchmany(size)

    class Connection:
        def __init__(self, *args, **kwargs):
            self.connection = original_connect(*args, **kwargs)

        def execute(self, sql):
            return Cursor(self.connection.execute(sql))

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(pickle, "dumps", dumps)
    monkeypatch.setattr(sqlite3, "connect", Connection)
    source = [(SourceUnitCount(str(i), 1, 1), {"station_id": str(i)}) for i in range(6)]
    iterators = [imgw._external_station_sort(iter(source), workspace=tmp_path) for _ in range(archive_count)]
    try:
        for iterator in iterators:
            assert next(iterator) == source[0]
        assert live_payloads == []
        assert fetch_sizes == [2] * archive_count
        for iterator in iterators:
            assert list(iterator) == source[1:]
        assert set(fetch_sizes) == {2}
    finally:
        for iterator in iterators:
            iterator.close()
    assert not list(tmp_path.iterdir())


def test_streamed_certification_reuses_semantics_but_replays_source(tmp_path, monkeypatch) -> None:
    from rivretrieve._internal.store import (
        NativeObservationBatch,
        ObservationBatchStream,
        SourceUnitContribution,
        SourceUnitCount,
        certify_store_batches,
        source_unit_inventory_fingerprint,
        validation,
    )

    artifact, request = artifact_and_request(tmp_path)
    original = validation._validate_partition
    validated = []
    decoded = []

    def validate(*args, **kwargs):
        validated.append(args[0])
        return original(*args, **kwargs)

    def decode(path):
        decoded.append(path.read_bytes())
        return ObservationBatchStream(
            request.source_columns,
            (NativeObservationBatch(rows(), (SourceUnitCount("one", 1, 1),), (SourceUnitContribution("one", 1),)),),
            1,
            1,
            source_unit_inventory_fingerprint((("one", 1, 1),)),
        )

    monkeypatch.setattr(validation, "_validate_partition", validate)
    certify_store_batches(request, artifact, decode)
    assert validated == ["product=discharge/year=1998"]
    assert decoded == [b"publisher fixture bytes", b"publisher fixture bytes"]
