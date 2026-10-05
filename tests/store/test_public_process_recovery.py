"""Public inspection/recovery for real sealed stores after process termination."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal import bulk
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.store.integrity import audit_store
from rivretrieve._internal.store.lifecycle import Ownership, StoreLifecycleError

WRITER = r"""
import os, signal, sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store import StoreRoot, certify_store
from rivretrieve._internal.store import lifecycle as life
from tests.store.certification_support import artifact_and_request, complete, rows
from tests.store.test_shared_publication import _certify
from tests.test_accumulated_store import _coverage, _rows, _rows_update
from rivretrieve._internal.store.accumulation import accumulate, StoreUpdate
import rivretrieve._internal.store.accumulation as accumulation

base, kind, boundary, first = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] == 'yes'
base.mkdir(parents=True, exist_ok=True)
root = base / 'store'
if kind in {'bulk', 'streaming'}:
    artifact, request = artifact_and_request(base)
    def write(value):
        artifact.write_bytes(b'publisher fixture')
        import hashlib
        from rivretrieve._internal.store import ArtifactChecksum, PublisherArtifact
        current = replace(request, publisher_artifact=PublisherArtifact(
            'https://example.test/source', ArtifactChecksum('sha256:' + hashlib.sha256(artifact.read_bytes()).hexdigest())))
        _certify(current, artifact, kind == 'streaming', value=value)
else:
    provider = ProviderId('fixture_live')
    def write(value):
        data = _rows([datetime(2020, 1, 1)], [value])
        accumulate(StoreRoot(root), provider, _rows_update(provider, data, _coverage('2020-01-01', '2020-01-02')))
if not first:
    write(1.0)
replace_path, publish, remove = life.os.replace, life.StoreTransaction.publish, life._remove

def kill():
    os.kill(os.getpid(), signal.SIGKILL)

def renamed(source, destination):
    if boundary == 'seal' and Path(destination) == root / 'integrity.json':
        kill()
    replace_path(source, destination)
    if boundary == 'old' and Path(destination).name.startswith('.store.previous-'):
        kill()
    if boundary == 'new' and Path(destination) == root:
        kill()
    if boundary == 'seal' and Path(destination) == root / 'integrity.json':
        kill()

def publishing(self, validate):
    if boundary == 'stage':
        kill()
    return publish(self, validate)

def removed(path):
    if boundary == 'cleanup' and path.name.startswith('.store.previous-'):
        next(path.rglob('*.parquet')).unlink()
        kill()
    return remove(path)
life.os.replace, life.StoreTransaction.publish, life._remove = renamed, publishing, removed
if boundary == 'witness':
    accumulation.refresh_witnesses = lambda *args, **kwargs: kill()
    accumulate(StoreRoot(root), ProviderId('fixture_live'), StoreUpdate((), (), (), ()))
elif boundary == 'seal':
    accumulate(StoreRoot(root), ProviderId('fixture_live'), StoreUpdate((), (), (), ()))
else:
    write(2.0)
"""


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL process-boundary test requires POSIX")
@pytest.mark.parametrize("kind", ["bulk", "streaming", "live"])
@pytest.mark.parametrize("boundary", ["stage", "old", "new", "cleanup"])
def test_public_recovery_retains_actual_committed_observations(tmp_path, monkeypatch, kind, boundary):
    root = tmp_path / "store"
    provider = ProviderId("fixture_live" if kind == "live" else "fixture_bulk")
    result = subprocess.run([sys.executable, "-c", WRITER, str(tmp_path), kind, boundary, "no"], check=False)
    assert result.returncode == -signal.SIGKILL
    monkeypatch.setattr(bulk, "_cache_registration", lambda _: (provider, StoreRoot(root)))
    status = rr.cache_status(str(provider))
    assert status.exists and status.committed_path is not None
    assert status.ownership is Ownership.ABANDONED
    assert status.interrupted_paths or status.cleanup_paths
    assert status.generation_id
    expected = 2.0 if boundary in {"new", "cleanup"} else 1.0
    observed = pl.concat([pl.read_parquet(path) for path in status.committed_path.rglob("*.parquet")])
    assert observed["value"].to_list() == [expected]
    before = audit_store(StoreRoot(status.committed_path), provider)
    recovery = rr.recover_cache(str(provider))
    assert recovery.status.generation_id == before.generation_id
    assert recovery.status.ownership is Ownership.IDLE
    assert not recovery.status.interrupted_paths and not recovery.status.cleanup_paths
    checked = rr.audit_cache(str(provider))
    assert checked.generation_id == before.generation_id
    assert checked.rows_checked == 1 and checked.partitions_checked == 1 and checked.bytes_checked > 0
    unrelated = tmp_path / "notes"
    unrelated.write_text("keep")
    removed = rr.clear_cache(str(provider))
    assert root in removed.removed_paths
    assert unrelated.read_text() == "keep"
    assert not rr.cache_status(str(provider)).exists


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL process-boundary test requires POSIX")
@pytest.mark.parametrize("kind", ["bulk", "streaming", "live"])
def test_public_first_install_stage_is_interrupted_not_committed(tmp_path, monkeypatch, kind):
    root = tmp_path / "store"
    provider = ProviderId("fixture_live" if kind == "live" else "fixture_bulk")
    result = subprocess.run([sys.executable, "-c", WRITER, str(tmp_path), kind, "stage", "yes"], check=False)
    assert result.returncode == -signal.SIGKILL
    monkeypatch.setattr(bulk, "_cache_registration", lambda _: (provider, StoreRoot(root)))
    status = rr.cache_status(str(provider))
    assert status.presence == "interrupted"
    assert not status.exists and status.committed_path is None
    with pytest.raises(StoreLifecycleError):
        rr.audit_cache(str(provider))
    recovered = rr.recover_cache(str(provider))
    assert recovered.status.presence == "absent"
    assert not root.exists()


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL process-boundary test requires POSIX")
def test_kill_before_owned_witness_refresh_preserves_digest_and_next_update(tmp_path, monkeypatch):
    from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
    from rivretrieve._internal.store.integrity import inspect_integrity

    root = StoreRoot(tmp_path / "store")
    provider = ProviderId("fixture_live")
    result = subprocess.run([sys.executable, "-c", WRITER, str(tmp_path), "live", "witness", "no"], check=False)
    assert result.returncode == -signal.SIGKILL
    monkeypatch.setattr(bulk, "_cache_registration", lambda _: (provider, root))
    status = rr.cache_status(str(provider))
    assert status.exists and status.cleanup_paths
    before = inspect_integrity(root, provider)
    partition_names = [name for name in before.files if name.endswith(".parquet")]
    assert partition_names
    assert any((root / name).stat().st_ctime_ns != before.files[name].ctime_ns for name in partition_names)
    recovered = rr.recover_cache(str(provider))
    assert recovered.status.generation_id == before.generation_id
    assert rr.audit_cache(str(provider)).rows_checked == 1
    accumulate(root, provider, StoreUpdate((), (), (), ()))
    after = inspect_integrity(root, provider)
    assert {name: item.sha256 for name, item in after.files.items() if name.endswith(".parquet")} == {
        name: before.files[name].sha256 for name in partition_names
    }
    assert rr.audit_cache(str(provider)).rows_checked == 1


def test_public_audit_is_read_only_and_status_does_not_claim_observation_audit(tmp_path, monkeypatch):
    import hashlib

    from rivretrieve._internal.store import certify_store
    from tests.store.certification_support import artifact_and_request, complete, rows

    artifact, request = artifact_and_request(tmp_path)
    certify_store(request, artifact, lambda _: complete(rows(value=4.0)))
    monkeypatch.setattr(bulk, "_cache_registration", lambda _: (request.provider_id, request.destination))
    root = request.destination

    def contents():
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*")
            if path.is_file()
        }

    original = contents()
    status = rr.cache_status(str(request.provider_id))
    audited = rr.audit_cache(str(request.provider_id))
    assert status.generation_id == audited.generation_id
    assert audited.rows_checked == 1
    assert contents() == original
    assert not status.interrupted_paths and not status.cleanup_paths


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL process-boundary test requires POSIX")
def test_killed_seal_refresh_is_reported_and_explicitly_recovered(tmp_path, monkeypatch):
    from rivretrieve._internal.store import ObservationStoreRefusedError

    root = StoreRoot(tmp_path / "store")
    provider = ProviderId("fixture_live")
    result = subprocess.run([sys.executable, "-c", WRITER, str(tmp_path), "live", "seal", "no"], check=False)
    assert result.returncode == -signal.SIGKILL
    pending = root / ".integrity.pending"
    assert pending.is_file()
    monkeypatch.setattr(bulk, "_cache_registration", lambda _: (provider, root))
    status = rr.cache_status(str(provider))
    assert status.exists and pending in status.cleanup_paths
    with pytest.raises(ObservationStoreRefusedError):
        rr.audit_cache(str(provider))
    recovered = rr.recover_cache(str(provider))
    assert recovered.status.generation_id == status.generation_id
    assert not pending.exists()
    assert rr.audit_cache(str(provider)).rows_checked == 1


def test_public_operations_protect_an_active_other_process(tmp_path, monkeypatch):
    root = StoreRoot(tmp_path / "store")
    provider = ProviderId("fixture_live")
    monkeypatch.setattr(bulk, "_cache_registration", lambda _: (provider, root))
    program = """
import sys
from pathlib import Path
from rivretrieve._internal.store.lifecycle import store_lease
with store_lease(Path(sys.argv[1])):
    print('owned', flush=True)
    sys.stdin.read(1)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", program, str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "owned"
        status = rr.cache_status(str(provider))
        assert status.ownership is Ownership.ACTIVE
        assert status.presence == "interrupted"
        for operation in (rr.clear_cache, rr.recover_cache, rr.audit_cache):
            with pytest.raises(StoreLifecycleError):
                operation(str(provider))
        assert (tmp_path / ".store.owner").exists()
        child.communicate("x", timeout=10)
        assert child.returncode == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
    assert rr.cache_status(str(provider)).ownership is Ownership.IDLE
