"""Synthetic local-process transaction guarantees; no host-crash claim."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from rivretrieve._internal.store import lifecycle as life


def validate(path: Path) -> str:
    value = (path / "data").read_text()
    if value not in {"old", "new"}:
        raise ValueError("damaged generation")
    return value


def install(root: Path, value: str = "old") -> None:
    with life.store_transaction(root) as tx:
        tx.stage.mkdir()
        (tx.stage / "data").write_text(value)
        tx.publish(validate)


def test_publish_and_explicit_reentrant_lease(tmp_path):
    root = tmp_path / "store"
    with life.store_lease(root) as lease:
        assert life.inspect_lifecycle(root).ownership == life.Ownership.ACTIVE
        with life.store_transaction(root, lease=lease) as tx:
            tx.stage.mkdir()
            (tx.stage / "data").write_text("old")
            tx.publish(validate)
        with pytest.raises(life.StoreLifecycleError, match="active"):
            life.clear_store(root)
        with pytest.raises(life.StoreLifecycleError, match="active"):
            life.recover_store(root, validate)
        with pytest.raises(life.StoreLifecycleError, match="active"), life.store_lease(root):
            pass
    with pytest.raises(life.StoreLifecycleError, match="token"), life.store_lease(root, lease=lease):
        pass
    state = life.inspect_lifecycle(root)
    assert state.committed_path == root
    assert state.ownership == life.Ownership.IDLE
    assert not state.interrupted_paths and not state.cleanup_paths


KILL_SCRIPT = """
import os, signal, sys
from pathlib import Path
from rivretrieve._internal.store import lifecycle as life
root = Path(sys.argv[1]); boundary = sys.argv[2]
replace = life.os.replace
remove = life._remove
write_journal = life._write_journal
def kill(): os.kill(os.getpid(), signal.SIGKILL)
def renamed(src, dst):
    if boundary == 'journal_temp' and Path(dst).name == '.store.transaction.json': kill()
    replace(src, dst)
    if boundary == 'old' and Path(dst).name.startswith('.store.previous-'): kill()
    if boundary == 'new' and Path(dst) == root: kill()
def journal(root, record):
    write_journal(root, record)
    if boundary == 'journal' and record['phase'] == 'preparing': kill()
def removed(path):
    if boundary == 'cleanup' and path.name.startswith('.store.previous-'):
        (path / 'data').unlink()
        kill()
    remove(path)
life.os.replace = renamed; life._remove = removed; life._write_journal = journal
with life.store_transaction(root) as tx:
    tx.stage.mkdir(); (tx.stage/'data').write_text('new')
    if boundary == 'stage': kill()
    tx.publish(lambda path: (path/'data').read_text())
"""


@pytest.mark.parametrize("boundary", ["journal", "stage", "old", "new", "cleanup"])
def test_sigkill_retains_discoverable_committed_generation(tmp_path, boundary):
    root = tmp_path / "store"
    install(root)
    result = subprocess.run([sys.executable, "-c", KILL_SCRIPT, str(root), boundary], check=False)
    assert result.returncode == -signal.SIGKILL
    state = life.inspect_lifecycle(root)
    assert state.ownership == life.Ownership.ABANDONED
    assert state.committed_path is not None
    expected = "new" if boundary in {"new", "cleanup"} else "old"
    assert validate(state.committed_path) == expected
    assert state.interrupted_paths or state.cleanup_paths
    with pytest.raises(life.StoreLifecycleError, match="recovery"):
        install(root)
    actions = life.recover_store(root, validate)
    assert actions
    assert validate(root) == expected
    assert not life.inspect_lifecycle(root).interrupted_paths
    assert not life.inspect_lifecycle(root).cleanup_paths
    install(root, "new")


@pytest.mark.parametrize("boundary", ["journal", "stage", "new"])
def test_sigkill_first_install_stage_is_not_committed(tmp_path, boundary):
    root = tmp_path / "store"
    result = subprocess.run([sys.executable, "-c", KILL_SCRIPT, str(root), boundary], check=False)
    assert result.returncode == -signal.SIGKILL
    state = life.inspect_lifecycle(root)
    assert (state.committed_path is not None) == (boundary == "new")
    assert state.interrupted_paths or state.cleanup_paths
    life.recover_store(root, validate)
    assert root.exists() == (boundary == "new")


def test_cleanup_debt_keeps_new_store_and_exception_objects(tmp_path, monkeypatch):
    root = tmp_path / "store"
    install(root)
    cleanup = PermissionError("cannot remove backup")
    remove = life._remove

    def failed(path):
        if path.name.startswith(".store.previous-"):
            raise cleanup
        remove(path)

    monkeypatch.setattr(life, "_remove", failed)
    with pytest.raises(life.StorePostCommitCleanupError) as caught:
        install(root, "new")
    error = caught.value
    assert error.original is cleanup
    assert error.cleanup_errors == (cleanup,)
    assert error.committed_path == root
    assert error.transaction_id
    assert error.residue_paths
    assert validate(root) == "new"
    state = life.inspect_lifecycle(root)
    assert state.committed_path == root and state.cleanup_paths
    monkeypatch.setattr(life, "_remove", remove)
    life.recover_store(root, validate)
    assert validate(root) == "new"


def test_original_and_cleanup_failure_both_survive(tmp_path, monkeypatch):
    root = tmp_path / "store"
    install(root)
    original = OSError("disk full")
    cleanup = PermissionError("stage deletion")
    remove = life._remove

    def failed(path):
        if path.name.startswith(".store.stage-"):
            raise cleanup
        remove(path)

    monkeypatch.setattr(life, "_remove", failed)
    with pytest.raises(life.StoreTransactionError) as caught, life.store_transaction(root) as tx:
        tx.stage.mkdir()
        raise original
    assert caught.value.original is original
    assert caught.value.cleanup_errors == (cleanup,)
    assert caught.value.committed_path == root
    assert validate(root) == "old"


def test_second_rename_failure_restores_old_store(tmp_path, monkeypatch):
    root = tmp_path / "store"
    install(root)
    replace = life.os.replace
    failure = OSError("rename failure")

    def failed(src, dst):
        if Path(src).name.startswith(".store.stage-"):
            raise failure
        replace(src, dst)

    monkeypatch.setattr(life.os, "replace", failed)
    with pytest.raises(OSError) as caught:
        install(root, "new")
    assert caught.value is failure
    assert validate(root) == "old"
    assert not life.inspect_lifecycle(root).interrupted_paths


def test_recovery_refuses_partly_deleted_previous(tmp_path):
    root = tmp_path / "store"
    install(root)
    subprocess.run([sys.executable, "-c", KILL_SCRIPT, str(root), "old"], check=False)
    previous = life.inspect_lifecycle(root).committed_path
    assert previous is not None
    (previous / "data").write_text("damaged")
    with pytest.raises(ValueError, match="damaged"):
        life.recover_store(root, validate)
    assert previous.exists()
    assert not root.exists()
    assert life.inspect_lifecycle(root).interrupted_paths


def test_unjournaled_previous_is_not_guessed(tmp_path):
    root = tmp_path / "store"
    previous = tmp_path / ".store.previous-unknown"
    previous.mkdir()
    (previous / "data").write_text("old")
    with pytest.raises(life.StoreLifecycleError, match="Unjournaled"):
        life.recover_store(root, validate)
    assert validate(previous) == "old"


@pytest.mark.parametrize("owner", ["not json", json.dumps({"host": "foreign", "pid": 1, "token": "x"})])
def test_ambiguous_ownership_refuses_recovery_and_clear(tmp_path, owner):
    root = tmp_path / "store"
    install(root)
    (tmp_path / ".store.owner").write_text(owner)
    assert life.inspect_lifecycle(root).ownership == life.Ownership.AMBIGUOUS
    for operation in (lambda: life.recover_store(root, validate), lambda: life.clear_store(root)):
        with pytest.raises(life.StoreLifecycleError, match="ambiguous"):
            operation()
    assert validate(root) == "old"


def test_local_released_kernel_lock_not_pid_liveness_is_authority(tmp_path):
    root = tmp_path / "store"
    install(root)
    (tmp_path / ".store.owner").write_text(
        json.dumps({"host": socket.gethostname(), "pid": os.getpid(), "token": "old"})
    )
    # PID may be reused. No kernel lock is held, so no local owner remains.
    assert life.inspect_lifecycle(root).ownership == life.Ownership.ABANDONED
    life.recover_store(root, validate)
    assert validate(root) == "old"


def test_clear_unlinks_managed_symlinks_without_touching_targets(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data").write_text("unrelated")
    parent = tmp_path / "cache"
    parent.mkdir()
    root = parent / "store"
    root.symlink_to(outside, target_is_directory=True)
    (parent / ".store.stage-unknown").symlink_to(outside, target_is_directory=True)
    unrelated = parent / "notes"
    unrelated.write_text("keep")
    removed = life.clear_store(root)
    assert root in removed
    assert len(removed) == 2
    assert (outside / "data").read_text() == "unrelated"
    assert unrelated.read_text() == "keep"
    assert (parent / ".store.owner").is_file()


def test_configured_parent_symlink_allowed_managed_symlink_refused(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    configured = tmp_path / "configured"
    configured.symlink_to(actual, target_is_directory=True)
    root = configured / "provider" / "store"
    install(root)
    assert validate(actual / "provider" / "store") == "old"
    root.rename(actual / "outside")
    root.symlink_to(actual / "outside", target_is_directory=True)
    with pytest.raises(life.StoreLifecycleError, match="symlink"):
        install(root)
    assert validate(actual / "outside") == "old"


def test_clear_rejects_extra_paths_outside_parent(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("keep")
    with pytest.raises(life.StoreLifecycleError, match="parent"):
        life.clear_store(tmp_path / "provider" / "store", extra_paths=(outside,))
    assert outside.read_text() == "keep"


def test_managed_provider_symlink_refuses_all_mutations(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    provider = tmp_path / "provider"
    provider.symlink_to(target, target_is_directory=True)
    for operation in (
        lambda: install(provider / "store"),
        lambda: life.clear_store(provider / "store"),
        lambda: life.recover_store(provider / "store", validate),
    ):
        with pytest.raises(life.StoreLifecycleError, match="provider symlink"):
            operation()
    assert not list(target.iterdir())


def test_legacy_lock_remains_ambiguous_and_quarantine_is_visible(tmp_path):
    root = tmp_path / "store"
    lock = tmp_path / ".store.write-lock"
    lock.mkdir()
    quarantine = tmp_path / ".publisher-artifacts.rollback-old"
    quarantine.mkdir()
    state = life.inspect_lifecycle(root)
    assert state.ownership == life.Ownership.AMBIGUOUS
    assert set(state.interrupted_paths) == {lock, quarantine}
    with pytest.raises(life.StoreLifecycleError, match="ambiguous"):
        life.clear_store(root)
    lock.rmdir()
    assert life.clear_store(root) == (quarantine,)


def test_workspace_discovered_after_killed_transfer_and_cleared(tmp_path):
    root = tmp_path / "store"
    script = """
import os, signal, sys
from pathlib import Path
from rivretrieve._internal.store.lifecycle import store_transaction
with store_transaction(Path(sys.argv[1])) as tx:
    tx.workspace.mkdir()
    (tx.workspace/'partial-download').write_bytes(b'partial')
    os.kill(os.getpid(),signal.SIGKILL)
"""
    result = subprocess.run([sys.executable, "-c", script, str(root)], check=False)
    assert result.returncode == -signal.SIGKILL
    state = life.inspect_lifecycle(root)
    assert state.committed_path is None
    assert any(p.name.startswith(".store.workspace-") for p in state.interrupted_paths)
    actions = life.recover_store(root, validate)
    assert any("workspace" in action for action in actions)
    assert not life.inspect_lifecycle(root).interrupted_paths


def test_external_cleanup_error_reports_input_but_recovery_does_not_delete_it(tmp_path):
    root = tmp_path / "store"
    artifact = tmp_path / "caller-input"
    artifact.write_text("source")
    original = PermissionError("input unlink")
    with pytest.raises(life.StorePostCommitCleanupError) as caught, life.store_transaction(root) as tx:
        tx.register_cleanup((artifact,))
        tx.stage.mkdir()
        (tx.stage / "data").write_text("new")
        tx.publish(validate)
        raise original
    assert caught.value.original is original
    assert artifact in caught.value.residue_paths
    life.recover_store(root, validate)
    assert artifact.read_text() == "source"
    assert validate(root) == "new"


def test_idle_owner_cleanup_failure_preserves_original(tmp_path, monkeypatch):
    root = tmp_path / "store"
    original = OSError("write failed")
    cleanup = PermissionError("owner write failed")
    write = life._write_owner

    def failed(stream, value):
        if value == {"state": "idle"}:
            raise cleanup
        write(stream, value)

    monkeypatch.setattr(life, "_write_owner", failed)
    with pytest.raises(life.StoreTransactionError) as caught, life.store_lease(root):
        raise original
    assert caught.value.original is original
    assert caught.value.cleanup_errors == (cleanup,)
    assert tmp_path / ".store.owner" in caught.value.residue_paths


def test_actual_active_process_excludes_clear_recovery_and_write(tmp_path):
    root = tmp_path / "store"
    install(root)
    script = """
import sys
from pathlib import Path
from rivretrieve._internal.store.lifecycle import store_lease
with store_lease(Path(sys.argv[1])):
    print('ready', flush=True)
    sys.stdin.read(1)
"""
    with subprocess.Popen(
        [sys.executable, "-c", script, str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    ) as process:
        assert process.stdout is not None and process.stdin is not None
        try:
            assert process.stdout.readline().strip() == "ready"
            for operation in (
                lambda: life.clear_store(root),
                lambda: life.recover_store(root, validate),
                lambda: install(root, "new"),
            ):
                with pytest.raises(life.StoreLifecycleError, match="active"):
                    operation()
            assert validate(root) == "old"
        finally:
            process.stdin.write("x")
            process.stdin.flush()
        assert process.wait(timeout=10) == 0


def test_idle_recovery_does_not_claim_abandoned_ownership(tmp_path):
    root = tmp_path / "store"
    assert life.recover_store(root, validate) == ()


@pytest.mark.parametrize("commit", [False, True])
def test_cleanup_hook_runs_after_owned_unlinks_under_lease(tmp_path, commit):
    root = tmp_path / "store"
    install(root)
    observed = []
    with life.store_transaction(root) as tx:
        tx.stage.mkdir()
        (tx.stage / "data").write_text("new")
        tx.workspace.mkdir()

        def checked(path):
            assert not tx.workspace.exists()
            assert not tx.previous.exists()
            assert not tx.stage.exists()
            assert life.inspect_lifecycle(root).ownership == life.Ownership.ACTIVE
            assert (tmp_path / ".store.transaction.json").exists()
            observed.append(validate(root))

        if commit:
            tx.after_cleanup = checked
            tx.publish(validate)
        else:
            tx.after_cleanup = checked
    assert observed == ["new" if commit else "old"]


def test_partial_cleanup_never_refreshes_witness(tmp_path, monkeypatch):
    root = tmp_path / "store"
    install(root)
    observed = []
    remove = life._remove

    def failed(path):
        if path.name.startswith(".store.previous-"):
            (path / "data").unlink()
            raise PermissionError("partial cleanup")
        remove(path)

    monkeypatch.setattr(life, "_remove", failed)
    with pytest.raises(life.StorePostCommitCleanupError), life.store_transaction(root) as tx:
        tx.stage.mkdir()
        (tx.stage / "data").write_text("new")
        tx.after_cleanup = lambda path: observed.append("unsafe refresh")
        tx.publish(validate)
    assert observed == []
    assert validate(root) == "new"
    assert life.inspect_lifecycle(root).cleanup_paths


def test_refresh_callback_failure_is_postcommit_debt(tmp_path):
    root = tmp_path / "store"
    failure = ValueError("stat witness changed")

    def failed(path):
        raise failure

    with pytest.raises(life.StorePostCommitCleanupError) as caught, life.store_transaction(root) as tx:
        tx.stage.mkdir()
        (tx.stage / "data").write_text("new")
        tx.after_cleanup = failed
        tx.publish(validate)
    assert caught.value.original is failure
    assert caught.value.cleanup_errors == (failure,)
    assert validate(root) == "new"
    assert life.inspect_lifecycle(root).cleanup_paths


@pytest.mark.parametrize("commit", [False, True])
def test_failed_operation_retains_workspace_until_explicit_recovery(tmp_path, commit):
    root = tmp_path / "store"
    install(root)
    original = PermissionError("artifact unlink" if commit else "compile failure")
    expected_error = life.StorePostCommitCleanupError if commit else life.StoreTransactionError
    with pytest.raises(expected_error) as caught, life.store_transaction(root) as tx:
        tx.workspace.mkdir()
        artifact = tx.workspace / "publisher.zip"
        artifact.write_bytes(b"original publisher input")
        tx.stage.mkdir()
        (tx.stage / "data").write_text("new")
        if commit:
            tx.publish(validate)
        raise original
    assert caught.value.original is original
    assert caught.value.cleanup_errors == ()
    assert caught.value.committed_path == root
    assert caught.value.transaction_id == tx.transaction_id
    assert caught.value.generation_id is None
    assert tx.workspace in caught.value.residue_paths
    assert isinstance(caught.value, life.StorePostCommitCleanupError) == commit
    assert artifact.read_bytes() == b"original publisher input"
    assert validate(root) == ("new" if commit else "old")
    state = life.inspect_lifecycle(root)
    assert tx.workspace in (state.cleanup_paths if commit else state.interrupted_paths)
    with pytest.raises(life.StoreLifecycleError, match="recovery"):
        install(root)
    life.recover_store(root, validate)
    assert not tx.workspace.exists()
    assert validate(root) == ("new" if commit else "old")


def test_pending_seal_is_cleanup_residue_not_new_authority(tmp_path):
    root = tmp_path / "store"
    install(root)
    pending = root / ".integrity.pending"
    pending.write_text("unfinished replacement metadata")
    assert life.inspect_lifecycle(root).cleanup_paths == (pending,)
    checked = []

    def validated(path):
        assert pending.exists()
        checked.append(validate(path))

    actions = life.recover_store(root, validated)
    assert actions == (f"removed {pending}",)
    assert checked == ["old"]


def test_pending_seal_symlink_recovery_does_not_follow_target(tmp_path):
    root = tmp_path / "store"
    install(root)
    outside = tmp_path / "outside"
    outside.write_text("unrelated")
    (root / ".integrity.pending").symlink_to(outside)
    with pytest.raises(life.StoreLifecycleError, match="pending integrity"):
        life.recover_store(root, validate)
    assert outside.read_text() == "unrelated"


def test_explicit_clear_accepts_malformed_journal_with_held_lease(tmp_path):
    root = tmp_path / "store"
    install(root)
    journal = tmp_path / ".store.transaction.json"
    journal.write_text("partial JSON")
    with life.store_lease(root, recovery=True) as lease:
        assert set(life.managed_paths(root)) == {root, journal}
        assert set(life.clear_store(root, lease=lease)) == {root, journal}
    assert not root.exists()


def test_failed_audit_preserves_pending_integrity_file(tmp_path):
    root = tmp_path / "store"
    install(root)
    pending = root / ".integrity.pending"
    pending.write_text("incomplete metadata")

    def refused(path):
        raise ValueError("main seal invalid")

    with pytest.raises(ValueError, match="main seal invalid"):
        life.recover_store(root, refused)
    assert pending.read_text() == "incomplete metadata"
    assert validate(root) == "old"


def test_duplicate_journal_fields_are_ambiguous_not_last_value_wins(tmp_path):
    root = tmp_path / "store"
    install(root)
    (tmp_path / ".store.transaction.json").write_text(
        '{"id":"' + "a" * 32 + '","phase":"preparing","phase":"committed"}'
    )
    with pytest.raises(life.StoreLifecycleError, match="Ambiguous"):
        life.recover_store(root, validate)
    assert validate(root) == "old"


def test_previous_generation_contradicting_preparation_is_not_restored(tmp_path):
    root = tmp_path / "store"
    identity = "a" * 32
    previous = tmp_path / f".store.previous-{identity}"
    previous.mkdir()
    (previous / "data").write_text("old")
    (tmp_path / ".store.transaction.json").write_text(json.dumps({"id": identity, "phase": "preparing"}))
    with pytest.raises(life.StoreLifecycleError, match="contradicts"):
        life.recover_store(root, validate)
    assert validate(previous) == "old"
    assert not root.exists()


def test_recovery_cleanup_failure_reports_committed_identity_and_residue(tmp_path, monkeypatch):
    root = tmp_path / "store"
    install(root)
    result = subprocess.run([sys.executable, "-c", KILL_SCRIPT, str(root), "new"], check=False)
    assert result.returncode == -signal.SIGKILL
    state = life.inspect_lifecycle(root)
    failure = PermissionError("backup cleanup failed")
    remove = life._remove

    def failed(path):
        if path.name.startswith(".store.previous-"):
            raise failure
        remove(path)

    monkeypatch.setattr(life, "_remove", failed)
    with pytest.raises(life.StorePostCommitCleanupError) as caught:
        life.recover_store(root, validate)
    assert caught.value.original is failure
    assert caught.value.cleanup_errors == (failure,)
    assert caught.value.committed_path == root
    assert caught.value.transaction_id == state.transaction_id
    assert any(p.name.startswith(".store.previous-") for p in caught.value.residue_paths)
    assert validate(root) == "new"
    assert life.inspect_lifecycle(root).cleanup_paths


@pytest.mark.parametrize("prior", [False, True])
def test_sigkill_before_first_journal_rename_recovers_without_adopting_temp(tmp_path, prior):
    root = tmp_path / "store"
    if prior:
        install(root)
    result = subprocess.run([sys.executable, "-c", KILL_SCRIPT, str(root), "journal_temp"], check=False)
    assert result.returncode == -signal.SIGKILL
    temporary = tmp_path / ".store.transaction.new"
    state = life.inspect_lifecycle(root)
    assert state.interrupted_paths == (temporary,)
    assert state.ownership == life.Ownership.ABANDONED
    assert state.committed_path == (root if prior else None)
    # Recovery does not parse or adopt an unfinished candidate record.
    temporary.write_text("partial untrusted JSON")
    actions = life.recover_store(root, validate)
    assert f"removed {temporary}" in actions
    assert not temporary.exists()
    assert root.exists() == prior
    if prior:
        assert validate(root) == "old"


def test_initial_journal_disk_full_partial_write_is_explicitly_recoverable(tmp_path, monkeypatch):
    import errno

    root = tmp_path / "store"
    install(root)
    write = Path.write_text
    failure = OSError(errno.ENOSPC, "journal disk full")

    def failed(path, value, *args, **kwargs):
        if path.name == ".store.transaction.new":
            write(path, '{"id":')
            raise failure
        return write(path, value, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failed)
    with pytest.raises(OSError) as caught:
        install(root, "new")
    assert caught.value is failure
    assert validate(root) == "old"
    temporary = tmp_path / ".store.transaction.new"
    assert life.inspect_lifecycle(root).interrupted_paths == (temporary,)
    life.recover_store(root, validate)
    assert not temporary.exists()
    assert validate(root) == "old"


def test_unjournaled_temp_plus_stage_remains_ambiguous(tmp_path):
    root = tmp_path / "store"
    temporary = tmp_path / ".store.transaction.new"
    temporary.write_text("partial")
    stage = tmp_path / (".store.stage-" + "a" * 32)
    stage.mkdir()
    with pytest.raises(life.StoreLifecycleError, match="Unjournaled"):
        life.recover_store(root, validate)
    assert temporary.exists() and stage.exists()


def test_base_exception_after_new_rename_is_committed_before_cleanup_callback(tmp_path, monkeypatch):
    root = tmp_path / "store"
    install(root)
    interruption = KeyboardInterrupt("after installed rename")
    replace = life.os.replace
    observed = []

    def interrupted(src, dst):
        replace(src, dst)
        if Path(dst) == root:
            raise interruption

    monkeypatch.setattr(life.os, "replace", interrupted)
    with pytest.raises(life.StorePostCommitCleanupError) as caught, life.store_transaction(root) as tx:
        tx.stage.mkdir()
        (tx.stage / "data").write_text("new")

        def refresh(path):
            assert tx.committed
            observed.append(validate(path))

        tx.after_cleanup = refresh
        tx.publish(validate)
    assert caught.value.original is interruption
    assert caught.value.committed_path == root
    assert observed == ["new"]
    assert validate(root) == "new"
    assert not tx.previous.exists()


def test_invalid_utf8_owner_is_ambiguous_and_never_deleted(tmp_path):
    root = tmp_path / "store"
    install(root)
    owner = tmp_path / ".store.owner"
    malformed = b"\xff\xfeinvalid owner"
    owner.write_bytes(malformed)
    assert life.inspect_lifecycle(root).ownership == life.Ownership.AMBIGUOUS
    for operation in (
        lambda: life.recover_store(root, validate),
        lambda: life.clear_store(root),
        lambda: install(root, "new"),
    ):
        with pytest.raises(life.StoreLifecycleError, match="ambiguous"):
            operation()
        assert owner.read_bytes() == malformed
        assert validate(root) == "old"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO boundary")
def test_fifo_owner_refuses_without_opening_and_survives_clear(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    (root / "data").write_text("old")
    owner = tmp_path / ".store.owner"
    os.mkfifo(owner)
    assert life.inspect_lifecycle(root).ownership == life.Ownership.AMBIGUOUS
    for operation in (
        lambda: life.clear_store(root),
        lambda: life.recover_store(root, validate),
        lambda: install(root, "new"),
    ):
        with pytest.raises(life.StoreLifecycleError, match="non-regular owner"):
            operation()
        assert owner.exists()
        assert not owner.is_file()
        assert validate(root) == "old"


def test_directory_owner_refuses_without_modification(tmp_path):
    root = tmp_path / "store"
    owner = tmp_path / ".store.owner"
    owner.mkdir()
    marker = owner / "unrelated"
    marker.write_text("keep")
    with pytest.raises(life.StoreLifecycleError, match="non-regular owner"), life.store_lease(root):
        pass
    assert marker.read_text() == "keep"


def test_retained_workspace_wraps_source_failure_without_changing_source_fields(tmp_path):
    from rivretrieve._internal.transport import (
        HttpMethod,
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
    )

    root = tmp_path / "store"
    install(root)
    request = TransportRequest(HttpMethod.GET, "https://example.test/publisher.zip")
    original = TransportFailure(request, TransportFailureReason.HTTP_STATUS, 2, status_code=503)
    with pytest.raises(life.StoreTransactionError) as caught, life.store_transaction(root) as tx:
        tx.workspace.mkdir()
        (tx.workspace / "previously-downloaded-input").write_bytes(b"source")
        raise original
    error = caught.value
    assert error.original is original
    assert error.__cause__ is original
    assert original.request is request
    assert original.reason == TransportFailureReason.HTTP_STATUS
    assert original.status_code == 503
    assert original.attempts == 2
    assert error.cleanup_errors == ()
    assert error.committed_path == root
    assert error.generation_id is None
    assert not isinstance(error, life.StorePostCommitCleanupError)
    assert tx.workspace in error.residue_paths
    assert validate(root) == "old"


@pytest.mark.parametrize("reentrant", [False, True])
@pytest.mark.parametrize("transaction_failure", [False, True])
def test_idle_owner_failure_retains_publication_identity(tmp_path, monkeypatch, reentrant, transaction_failure):
    from contextlib import nullcontext
    from types import SimpleNamespace

    root = tmp_path / "store"
    install(root)
    owner_cleanup = PermissionError("owner idle write failed")
    original = OSError("postcommit operation failed")
    transaction_cleanup = PermissionError("previous generation deletion failed")
    write = life._write_owner
    remove = life._remove
    artifact = tmp_path / "caller-input"
    artifact.write_text("source")

    def failed_owner(stream, value):
        if value == {"state": "idle"}:
            raise owner_cleanup
        write(stream, value)

    def failed_remove(path):
        if transaction_failure and path.name.startswith(".store.previous-"):
            raise transaction_cleanup
        remove(path)

    def validated(path):
        assert validate(path) == "new"
        return SimpleNamespace(generation_id="new-generation")

    monkeypatch.setattr(life, "_write_owner", failed_owner)
    monkeypatch.setattr(life, "_remove", failed_remove)
    with (
        pytest.raises(life.StorePostCommitCleanupError) as caught,
        life.store_lease(root) if reentrant else nullcontext() as lease,
        life.store_transaction(root, lease=lease) as tx,
    ):
        tx.register_cleanup((artifact,))
        tx.stage.mkdir()
        (tx.stage / "data").write_text("new")
        tx.publish(validated)
        if transaction_failure:
            raise original

    error = caught.value
    assert error.original is (original if transaction_failure else owner_cleanup)
    assert error.cleanup_errors == ((transaction_cleanup, owner_cleanup) if transaction_failure else (owner_cleanup,))
    assert error.transaction_id == tx.transaction_id
    assert error.generation_id == "new-generation"
    assert error.committed_path == root
    assert tmp_path / ".store.owner" in error.residue_paths
    if transaction_failure:
        assert artifact in error.residue_paths
        assert tx.previous in error.residue_paths
    assert validate(root) == "new"
    assert life.inspect_lifecycle(root).ownership == life.Ownership.ABANDONED
