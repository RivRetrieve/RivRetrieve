"""Compiler failures retain their identity when resource cleanup also fails."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from rivretrieve._internal.store import (
    NativeObservationBatch,
    ObservationBatchStream,
    SourceUnitContribution,
    SourceUnitCount,
    certify_store,
    certify_store_batches,
    compiler,
    lifecycle,
    source_unit_inventory_fingerprint,
)
from rivretrieve._internal.store.lifecycle import StoreTransactionError
from tests.store.certification_support import COLUMNS, artifact_and_request, complete, rows


def _stream():
    batch = NativeObservationBatch(rows(), (SourceUnitCount("unit", 1, 1),), (SourceUnitContribution("unit", 1),))
    return ObservationBatchStream(COLUMNS, (batch,), 1, 1, source_unit_inventory_fingerprint((("unit", 1, 1),)))


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("failure_type", [ValueError, KeyboardInterrupt])
def test_compiler_retains_original_failure(tmp_path: Path, monkeypatch, streaming, cleanup_fails, failure_type):
    _artifact, request = artifact_and_request(tmp_path)
    original = failure_type("initiating failure")
    cleanup = PermissionError("cannot remove partial store")
    monkeypatch.setattr(
        compiler, "_physical_partition" if streaming else "_write_partition", Mock(side_effect=original)
    )
    if cleanup_fails:
        monkeypatch.setattr(compiler, "_remove_new_store", Mock(side_effect=cleanup))
    with pytest.raises(BaseException) as caught:
        if streaming:
            compiler.compile_store_batches(request, _stream())
        else:
            compiler.compile_store(request, rows())
    if cleanup_fails:
        assert isinstance(caught.value, StoreTransactionError)
        assert caught.value.original is original
        assert caught.value.cleanup_errors == (cleanup,)
        assert caught.value.residue_paths == (Path(request.destination),)
    else:
        assert caught.value is original
        assert not Path(request.destination).exists()


@pytest.mark.parametrize("removal_fails", [False, True])
def test_streaming_attempts_all_cleanup_after_writer_failure(tmp_path: Path, monkeypatch, removal_fails):
    _artifact, request = artifact_and_request(tmp_path)
    original = ValueError("cannot write partition")
    writer_cleanup = PermissionError("cannot close writer")
    database_cleanup = PermissionError("cannot close database")
    removal_cleanup = PermissionError("cannot remove partial store")
    writer = Mock()
    writer.write_table.side_effect = original
    writer.close.side_effect = writer_cleanup
    monkeypatch.setattr(compiler.pq, "ParquetWriter", Mock(return_value=writer))
    connect = compiler.sqlite3.connect
    database = None

    def failing_database(*args, **kwargs):
        nonlocal database
        real = connect(*args, **kwargs)
        database = Mock(wraps=real)

        def close():
            real.close()
            raise database_cleanup

        database.close.side_effect = close
        return database

    monkeypatch.setattr(compiler.sqlite3, "connect", failing_database)
    remove = Mock(side_effect=removal_cleanup) if removal_fails else Mock(wraps=compiler._remove_new_store)
    monkeypatch.setattr(compiler, "_remove_new_store", remove)
    with pytest.raises(StoreTransactionError) as caught:
        compiler.compile_store_batches(request, _stream())
    assert caught.value.original is original
    assert caught.value.cleanup_errors == (
        writer_cleanup,
        database_cleanup,
        *((removal_cleanup,) if removal_fails else ()),
    )
    assert caught.value.residue_paths == ((Path(request.destination),) if removal_fails else ())
    assert Path(request.destination).exists() is removal_fails
    writer.close.assert_called_once()
    assert database is not None
    database.close.assert_called_once()
    remove.assert_called_once_with(Path(request.destination))


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("transaction_cleanup_fails", [False, True])
def test_lifecycle_retains_compiler_and_transaction_cleanup(
    tmp_path: Path, monkeypatch, streaming, transaction_cleanup_fails
):
    artifact, request = artifact_and_request(tmp_path)
    original = ValueError("invalid source row")
    compiler_cleanup = PermissionError("cannot clean partial compilation")
    transaction_cleanup = PermissionError("cannot remove transaction stage")
    monkeypatch.setattr(compiler, "_physical_partition", Mock(side_effect=original))
    monkeypatch.setattr(compiler, "_remove_new_store", Mock(side_effect=compiler_cleanup))
    remove = lifecycle._remove

    def fail_stage(path):
        if transaction_cleanup_fails and ".stage-" in path.name:
            raise transaction_cleanup
        remove(path)

    monkeypatch.setattr(lifecycle, "_remove", fail_stage)
    with pytest.raises(StoreTransactionError) as caught:
        if streaming:
            certify_store_batches(request, artifact, lambda _: _stream())
        else:
            certify_store(request, artifact, lambda _: complete(rows()))
    assert caught.value.original is original
    assert caught.value.cleanup_errors == (
        compiler_cleanup,
        *((transaction_cleanup,) if transaction_cleanup_fails else ()),
    )
    assert caught.value.transaction_id is not None
    stage = tmp_path / f".store.stage-{caught.value.transaction_id}"
    assert (stage in caught.value.residue_paths) is transaction_cleanup_fails
    assert stage.exists() is transaction_cleanup_fails
    if not transaction_cleanup_fails:
        assert caught.value.residue_paths == ()
    assert artifact.exists()
    assert not Path(request.destination).exists()


@pytest.mark.parametrize("initialization", ["connect", "execute"])
def test_streaming_database_initialization_failure_is_cleaned(tmp_path: Path, monkeypatch, initialization):
    _artifact, request = artifact_and_request(tmp_path)
    original = PermissionError("cannot initialize reconciliation database")
    database = Mock()
    if initialization == "connect":
        connect = Mock(side_effect=original)
    else:
        database.execute.side_effect = original
        connect = Mock(return_value=database)
    monkeypatch.setattr(compiler.sqlite3, "connect", connect)
    with pytest.raises(PermissionError) as caught:
        compiler.compile_store_batches(request, _stream())
    assert caught.value is original
    assert not Path(request.destination).exists()
    if initialization == "execute":
        database.close.assert_called_once()
