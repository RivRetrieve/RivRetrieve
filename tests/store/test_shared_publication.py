"""Both certificate entrypoints use one commit and recovery contract."""

from __future__ import annotations

import errno
import hashlib
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.store import (
    ArtifactChecksum,
    NativeObservationBatch,
    ObservationBatchStream,
    PublisherArtifact,
    SourceUnitContribution,
    SourceUnitCount,
    certify_store,
    certify_store_batches,
    lifecycle,
    source_unit_inventory_fingerprint,
    validate_store,
)
from rivretrieve._internal.store.integrity import audit_store
from tests.store.certification_support import COLUMNS, artifact_and_request, complete, rows


def _certify(request, artifact, streaming, value=2.0):
    if not streaming:
        return certify_store(request, artifact, lambda _: complete(rows(value=value)))

    def decode(_):
        batch = NativeObservationBatch(
            rows(value=value), (SourceUnitCount("unit", 1, 1),), (SourceUnitContribution("unit", 1),)
        )
        return ObservationBatchStream(COLUMNS, (batch,), 1, 1, source_unit_inventory_fingerprint((("unit", 1, 1),)))

    return certify_store_batches(request, artifact, decode)


def _previous(tmp_path):
    artifact, request = artifact_and_request(tmp_path)
    certify_store(request, artifact, lambda _: complete(rows(value=1.0)))
    artifact.write_bytes(b"second publisher")
    request = replace(
        request,
        publisher_artifact=PublisherArtifact(
            "https://example.test/second",
            ArtifactChecksum("sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()),
        ),
    )
    return artifact, request


@pytest.mark.parametrize("streaming", [False, True])
def test_compilers_publish_sealed_generation_with_rebased_paths(tmp_path, streaming):
    artifact, request = artifact_and_request(tmp_path)
    result = _certify(request, artifact, streaming)
    assert result.root == request.destination
    assert all(path.is_file() and path.is_relative_to(result.root) for path in result.partition_files.values())
    assert audit_store(result.root, request.provider_id).rows_checked == 1
    assert not artifact.exists()
    assert not lifecycle.inspect_lifecycle(Path(result.root)).interrupted_paths


@pytest.mark.parametrize("streaming", [False, True])
def test_publication_failure_preserves_prior_and_artifact(tmp_path, monkeypatch, streaming):
    artifact, request = _previous(tmp_path)
    real_replace = lifecycle.os.replace

    def fail_stage(source, target):
        if Path(source).name.startswith(".store.stage-"):
            raise OSError(errno.ENOSPC, "late resource failure")
        return real_replace(source, target)

    monkeypatch.setattr(lifecycle.os, "replace", fail_stage)
    with pytest.raises(OSError, match="late resource failure"):
        _certify(request, artifact, streaming)
    assert artifact.exists()
    prior = validate_store(request.destination, request.provider_id)
    assert pl.read_parquet(next(iter(prior.partition_files.values())))["value"].to_list() == [1.0]


@pytest.mark.parametrize("streaming", [False, True])
def test_failed_restoration_retains_original_error_and_recoverable_prior(tmp_path, monkeypatch, streaming):
    artifact, request = _previous(tmp_path)
    real_replace = lifecycle.os.replace

    def fail_install_and_restore(source, target):
        if Path(source).name.startswith(".store.stage-"):
            raise OSError("install failed")
        if Path(source).name.startswith(".store.previous-"):
            raise PermissionError("restore failed")
        return real_replace(source, target)

    monkeypatch.setattr(lifecycle.os, "replace", fail_install_and_restore)
    with pytest.raises(lifecycle.StoreTransactionError) as caught:
        _certify(request, artifact, streaming)
    assert str(caught.value.original) == "install failed"
    assert any(str(error) == "restore failed" for error in caught.value.cleanup_errors)
    assert artifact.exists()
    previous = lifecycle.inspect_lifecycle(Path(request.destination)).committed_path
    assert previous is not None
    assert audit_store(previous, request.provider_id).rows_checked == 1
    monkeypatch.setattr(lifecycle.os, "replace", real_replace)
    lifecycle.recover_store(Path(request.destination), lambda path: audit_store(path, request.provider_id))
    assert Path(request.destination).exists()


@pytest.mark.parametrize("streaming", [False, True])
def test_backup_cleanup_debt_keeps_new_authority(tmp_path, monkeypatch, streaming):
    artifact, request = _previous(tmp_path)
    real_remove = lifecycle._remove

    def fail_backup(path):
        if path.name.startswith(".store.previous-"):
            raise PermissionError("backup cleanup failed")
        return real_remove(path)

    monkeypatch.setattr(lifecycle, "_remove", fail_backup)
    with pytest.raises(lifecycle.StorePostCommitCleanupError) as caught:
        _certify(request, artifact, streaming)
    assert caught.value.committed_path == Path(request.destination)
    assert caught.value.generation_id == audit_store(request.destination, request.provider_id).generation_id
    assert caught.value.cleanup_errors
    assert not artifact.exists()
    current = validate_store(request.destination, request.provider_id)
    assert pl.read_parquet(next(iter(current.partition_files.values())))["value"].to_list() == [2.0]
    monkeypatch.setattr(lifecycle, "_remove", real_remove)
    lifecycle.recover_store(Path(request.destination), lambda path: audit_store(path, request.provider_id))
    assert not lifecycle.inspect_lifecycle(Path(request.destination)).cleanup_paths


def test_staging_cleanup_preserves_initiating_failure(tmp_path, monkeypatch):
    artifact, request = _previous(tmp_path)
    real_remove = lifecycle._remove

    def writer(staged, materialized):
        from rivretrieve._internal.store import compile_store

        compile_store(staged, materialized)
        raise RuntimeError("writer failed")

    def fail_stage(path):
        if path.name.startswith(".store.stage-"):
            raise OSError("stage cleanup failed")
        return real_remove(path)

    monkeypatch.setattr(lifecycle, "_remove", fail_stage)
    with pytest.raises(lifecycle.StoreTransactionError) as caught:
        certify_store(request, artifact, lambda _: complete(rows()), writer=writer)
    assert str(caught.value.original) == "writer failed"
    assert any(str(error) == "stage cleanup failed" for error in caught.value.cleanup_errors)
    assert artifact.exists()
    assert audit_store(request.destination, request.provider_id).rows_checked == 1


@pytest.mark.parametrize("provider", ["ca_eccc", "pl_imgw"])
def test_public_download_owns_transfer_compile_and_workspace(
    tmp_path, monkeypatch, stub_packaged_catalogue_artifact, provider
):
    from datetime import date
    from importlib import import_module
    from types import SimpleNamespace

    import rivretrieve as rr
    from rivretrieve._internal import bulk
    from rivretrieve._internal.providers.registration import BulkStore
    from rivretrieve._internal.registry import ProviderRegistry
    from rivretrieve._internal.store import StoreRoot
    from tests.store.test_ca_eccc_provenance import _hydat
    from tests.store.test_pl_imgw_publication_public import publication

    declaration = import_module(f"rivretrieve._internal.providers.{provider}.declaration").declaration
    declared = declaration.observations
    assert isinstance(declared, BulkStore)
    root = StoreRoot(tmp_path / provider / "store")
    if provider == "ca_eccc":
        source = tmp_path / "source.sqlite3"
        _hydat(source)
        responses = None
        content = source.read_bytes()
    else:
        source_bulk = import_module("rivretrieve._internal.providers.pl_imgw.bulk")
        monkeypatch.setattr(source_bulk, "FIRST_PUBLISHED_YEAR", 2022)
        responses = publication({2022: ["codz_2022_01.zip"]})
        content = b""
    checked = []
    fail_compile = False
    compile_failure = ValueError("synthetic compile refusal")

    class Client:
        def send(self, request):
            assert lifecycle.inspect_lifecycle(Path(root)).ownership is lifecycle.Ownership.ACTIVE
            with pytest.raises(lifecycle.StoreLifecycleError, match="active"):
                lifecycle.clear_store(Path(root))
            checked.append("transfer")
            return SimpleNamespace(status_code=200, content=content if responses is None else responses[request.url])

    def compile_request(request):
        assert request.transaction is not None
        assert all(item.path.parent == request.transaction.workspace for item in request.publisher_artifacts)
        assert request.transaction.workspace.stat().st_dev == Path(root).parent.stat().st_dev
        assert lifecycle.inspect_lifecycle(Path(root)).ownership is lifecycle.Ownership.ACTIVE
        checked.append("compile")
        if fail_compile:
            raise compile_failure
        return declared.compile(request)

    operations = BulkStore(declared.config, declared.download, compile_request)
    registry = ProviderRegistry()
    registry.register(
        provider,
        stub_packaged_catalogue_artifact(provider),
        bulk_config=operations.config,
        observation_store=root,
        bulk_operations=operations,
    )
    monkeypatch.setattr(bulk, "_registry", registry)
    monkeypatch.setattr(bulk, "_ensure_default_providers_registered", lambda: None)
    result = bulk._download(provider, free_space_probe=lambda _: 10**12, client_factory=Client, today=date(2026, 9, 22))
    assert "transfer" in checked and "compile" in checked
    assert audit_store(result.root, result.manifest.provider_id).rows_checked > 0
    assert lifecycle.inspect_lifecycle(Path(root)).ownership is lifecycle.Ownership.IDLE
    assert not tuple(Path(root).parent.glob(".store.workspace-*"))
    assert rr.cache_status(provider).root == Path(root)

    # A failed refresh keeps inputs and prior authority. Retry must not start
    # another transfer until explicit recovery has handled the saved transaction.
    fail_compile = True
    with pytest.raises(lifecycle.StoreTransactionError) as caught:
        bulk._download(provider, free_space_probe=lambda _: 10**12, client_factory=Client, today=date(2026, 9, 22))
    assert caught.value.original is compile_failure
    assert type(caught.value.original) is ValueError
    assert str(caught.value.original) == "synthetic compile refusal"
    assert caught.value.__cause__ is compile_failure
    assert caught.value.cleanup_errors == ()
    assert caught.value.generation_id is None
    assert caught.value.committed_path == Path(root)
    assert caught.value.transaction_id
    assert any(path.name.startswith(".store.workspace-") for path in caught.value.residue_paths)
    state = rr.cache_status(provider)
    assert state.generation_id is not None
    assert state.source_vintage == result.manifest.source_vintage
    assert state.interrupted_paths
    saved = {
        path: path.read_bytes() for path in Path(root).parent.glob(".store.workspace-*/publisher-artifact.download*")
    }
    assert saved
    before_retry = list(checked)
    with pytest.raises(lifecycle.StoreLifecycleError, match="requires explicit recovery"):
        bulk._download(provider, free_space_probe=lambda _: 10**12, client_factory=Client, today=date(2026, 9, 22))
    assert checked == before_retry
    assert {path: path.read_bytes() for path in saved} == saved
    lifecycle.recover_store(Path(root), lambda path: audit_store(path, result.manifest.provider_id))
    assert rr.cache_status(provider).generation_id == state.generation_id
    assert rr.cache_status(provider).source_vintage == result.manifest.source_vintage
    assert all(not path.exists() for path in saved)


@pytest.mark.parametrize("streaming", [False, True])
def test_first_rename_failure_never_restores_or_changes_previous(tmp_path, monkeypatch, streaming):
    artifact, request = _previous(tmp_path)
    root = Path(request.destination)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    real_replace = lifecycle.os.replace
    restored = []

    def fail_first(source, target):
        if Path(source) == root:
            raise PermissionError("previous rename refused")
        if Path(source).name.startswith(".store.previous-"):
            restored.append(source)
        return real_replace(source, target)

    monkeypatch.setattr(lifecycle.os, "replace", fail_first)
    with pytest.raises(PermissionError, match="previous rename refused"):
        _certify(request, artifact, streaming)
    assert artifact.exists()
    assert not restored
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert not lifecycle.inspect_lifecycle(root).interrupted_paths


@pytest.mark.parametrize("streaming", [False, True])
def test_post_install_journal_failure_reports_committed_generation_and_source(tmp_path, monkeypatch, streaming):
    artifact, request = _previous(tmp_path)
    real_journal = lifecycle._write_journal

    def fail_committed(root, record):
        if record["phase"] == "committed":
            raise OSError("commit journal failed")
        return real_journal(root, record)

    monkeypatch.setattr(lifecycle, "_write_journal", fail_committed)
    with pytest.raises(lifecycle.StorePostCommitCleanupError) as caught:
        _certify(request, artifact, streaming)
    assert caught.value.generation_id == audit_store(request.destination, request.provider_id).generation_id
    assert caught.value.committed_path == Path(request.destination)
    assert artifact in caught.value.residue_paths
    assert artifact.exists()
