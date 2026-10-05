"""Local-process publication, recovery and exclusive store ownership.

Configured cache ancestors may resolve through symlinks. The managed provider
parent and managed entries below it may not be symlinks. Clear unlinks terminal
symlinks without following them. A permanent kernel-lock file coordinates local processes; it is never removed, including by
clear. This contract does not cover network filesystems, hostile local mutation,
concurrent readers during replacement, or host/power failure.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO
from uuid import uuid4

from rivretrieve._internal.issues import FatalContractError


class Ownership(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    ABANDONED = "abandoned"
    AMBIGUOUS = "ambiguous"


class StoreLifecycleError(FatalContractError):
    """The store requires explicit inspection or recovery before mutation."""


class StoreTransactionError(StoreLifecycleError):
    """A failed operation, its cleanup failures and surviving paths.

    ``committed_path`` identifies authoritative data, if any. ``original`` and
    ``cleanup_errors`` retain exception objects rather than only their messages.
    """

    def __init__(
        self,
        original: BaseException,
        *,
        cleanup_errors: tuple[BaseException, ...] = (),
        committed_path: Path | None = None,
        transaction_id: str | None = None,
        generation_id: str | None = None,
        residue_paths: tuple[Path, ...] = (),
    ) -> None:
        self.original = original
        self.cleanup_errors = cleanup_errors
        self.committed_path = committed_path
        self.transaction_id = transaction_id
        self.generation_id = generation_id
        self.residue_paths = residue_paths
        super().__init__(f"Store operation failed: {original}; remaining owned paths: {residue_paths}")


class StorePostCommitCleanupError(StoreTransactionError):
    """Publication succeeded; cleanup failed and must not be treated as acquisition failure."""


@dataclass(frozen=True)
class LifecycleState:
    committed_path: Path | None
    interrupted_paths: tuple[Path, ...]
    cleanup_paths: tuple[Path, ...]
    ownership: Ownership
    transaction_id: str | None = None


@dataclass
class StoreLease:
    root: Path
    stream: IO[str]
    pid: int
    _committed_transaction: StoreTransaction | None = None

    def check(self, root: Path) -> None:
        if self.root != _root(root) or self.stream.closed or self.pid != os.getpid():
            raise StoreLifecycleError("Invalid or released store ownership token")


def _root(root: Path) -> Path:
    root = Path(root).absolute()
    if root.parent.is_symlink():
        raise StoreLifecycleError(f"Managed provider symlink refused: {root.parent}")
    return root.parent.resolve() / root.name


def _entry(root: Path, suffix: str) -> Path:
    return root.with_name(f".{root.name}.{suffix}")


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _no_link(path: Path) -> None:
    if path.is_symlink():
        raise StoreLifecycleError(f"Managed symlink refused: {path}")


def _flock(stream: IO[str], *, unlock: bool = False) -> None:
    if os.name == "nt":
        import errno
        import msvcrt

        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if not unlock and error.errno in {errno.EACCES, errno.EDEADLK, errno.EAGAIN}:
                raise BlockingIOError("Store ownership is active") from error
            raise
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unique_record(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate lifecycle field: {key}")
        value[key] = item
    return value


def _owner(stream: IO[str]) -> Ownership:
    stream.seek(0)
    try:
        text = stream.read()
        if not text:
            return Ownership.IDLE
        value = json.loads(text, object_pairs_hook=_unique_record)
        if value == {"state": "idle"}:
            return Ownership.IDLE
        if (
            set(value) == {"host", "pid", "token"}
            and value["host"] == socket.gethostname()
            and type(value["pid"]) is int
            and value["pid"] > 0
            and isinstance(value["token"], str)
        ):
            return Ownership.ABANDONED
    except (ValueError, TypeError):
        pass
    return Ownership.AMBIGUOUS


def _write_owner(stream: IO[str], value: dict[str, object]) -> None:
    stream.seek(0)
    stream.write(json.dumps(value))
    stream.truncate()
    stream.flush()


@contextmanager
def store_lease(root: Path, *, lease: StoreLease | None = None, recovery: bool = False) -> Iterator[StoreLease]:
    """Exclude writers, recovery and clear; reuse only an explicitly supplied token.

    Recovery can claim a released local kernel lock with a well-formed abandoned
    owner record. Foreign or malformed owner records remain ambiguous and refuse.
    """
    root = _root(root)
    if lease is not None:
        lease.check(root)
        yield lease
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    if _exists(_entry(root, "write-lock")):
        raise StoreLifecycleError("Legacy store ownership is ambiguous; preserve the lock")
    lock = _entry(root, "owner")
    _no_link(lock)
    if _exists(lock) and not lock.is_file():
        raise StoreLifecycleError(f"Store ownership is ambiguous: non-regular owner file {lock}")
    with os.fdopen(os.open(lock, os.O_RDWR | os.O_CREAT, 0o600), "r+", encoding="utf-8") as stream:
        try:
            _flock(stream)
        except BlockingIOError as error:
            raise StoreLifecycleError(f"Store writer already active: {root}") from error
        try:
            owner = _owner(stream)
            if owner == Ownership.AMBIGUOUS or (owner == Ownership.ABANDONED and not recovery):
                raise StoreLifecycleError(f"Store ownership requires recovery: {owner}")
            _write_owner(stream, {"host": socket.gethostname(), "pid": os.getpid(), "token": uuid4().hex})
            original: BaseException | None = None
            acquired = StoreLease(root, stream, os.getpid())
            try:
                yield acquired
            except BaseException as error:
                original = error
                raise
            finally:
                try:
                    _write_owner(stream, {"state": "idle"})
                except OSError as cleanup:
                    prior = original if isinstance(original, StoreTransactionError) else None
                    committed = acquired._committed_transaction
                    kind = (
                        StorePostCommitCleanupError
                        if isinstance(prior, StorePostCommitCleanupError) or committed is not None
                        else StoreTransactionError
                    )
                    cause = prior.original if prior is not None else original or cleanup
                    raise kind(
                        cause,
                        cleanup_errors=(*(prior.cleanup_errors if prior is not None else ()), cleanup),
                        committed_path=prior.committed_path if prior is not None else root if root.exists() else None,
                        transaction_id=(
                            prior.transaction_id
                            if prior is not None
                            else committed.transaction_id
                            if committed
                            else None
                        ),
                        generation_id=(
                            prior.generation_id if prior is not None else committed.generation_id if committed else None
                        ),
                        residue_paths=tuple(
                            dict.fromkeys((*(prior.residue_paths if prior is not None else ()), *_residue(root), lock))
                        ),
                    ) from (original or cleanup)
        finally:
            _flock(stream, unlock=True)


def _ownership(root: Path) -> Ownership:
    if _exists(_entry(root, "write-lock")):
        return Ownership.AMBIGUOUS
    lock = _entry(root, "owner")
    if not _exists(lock):
        return Ownership.IDLE
    if lock.is_symlink() or not lock.is_file():
        return Ownership.AMBIGUOUS
    with lock.open("r+", encoding="utf-8") as stream:
        try:
            _flock(stream)
        except BlockingIOError:
            return Ownership.ACTIVE
        try:
            return _owner(stream)
        finally:
            _flock(stream, unlock=True)


def _journal(root: Path) -> dict[str, str] | None:
    path = _entry(root, "transaction.json")
    if not _exists(path):
        return None
    _no_link(path)
    try:
        value = json.loads(path.read_text(), object_pairs_hook=_unique_record)
        if (
            set(value) != {"id", "phase"}
            or not isinstance(value["id"], str)
            or len(value["id"]) != 32
            or any(c not in "0123456789abcdef" for c in value["id"])
            or value["phase"] not in {"preparing", "replacing", "committed"}
        ):
            raise ValueError("invalid journal")
        return value
    except (ValueError, TypeError, KeyError) as error:
        raise StoreLifecycleError(f"Ambiguous transaction journal: {path}") from error


def _paths(root: Path, record: dict[str, str]) -> tuple[Path, Path]:
    return _entry(root, f"stage-{record['id']}"), _entry(root, f"previous-{record['id']}")


def _residue(root: Path) -> tuple[Path, ...]:
    if not root.parent.exists():
        return ()
    prefixes = tuple(
        f".{root.name}.{name}" for name in ("stage-", "previous-", "pending-", "backup-", "staging-", "workspace-")
    )
    prefixes += (".publisher-artifacts.rollback-",)
    exact = {
        _entry(root, "transaction.json").name,
        _entry(root, "transaction.new").name,
        _entry(root, "write-lock").name,
    }
    return tuple(sorted(p for p in root.parent.iterdir() if p.name.startswith(prefixes) or p.name in exact))


def inspect_lifecycle(root: Path) -> LifecycleState:
    """Inspect names and ownership without validating observation bytes."""
    root = _root(root)
    _no_link(root)
    record = _journal(root)
    residue = _residue(root)
    committed = root if root.exists() else None
    pending_seal = root / ".integrity.pending"
    cleanup: tuple[Path, ...] = (pending_seal,) if _exists(pending_seal) else ()
    if record:
        stage, previous = _paths(root, record)
        installed = record["phase"] in {"replacing", "committed"} and not _exists(stage) and root.exists()
        if installed:
            cleanup = (*cleanup, *residue)
        elif not root.exists() and previous.exists() and record["phase"] == "replacing":
            committed = previous
    return LifecycleState(
        committed,
        tuple(p for p in residue if p not in cleanup),
        cleanup,
        _ownership(root),
        record["id"] if record else None,
    )


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _write_journal(root: Path, record: dict[str, str]) -> None:
    temporary = _entry(root, "transaction.new")
    _no_link(temporary)
    temporary.write_text(json.dumps(record))
    os.replace(temporary, _entry(root, "transaction.json"))


class StoreTransaction:
    """Build in ``stage`` and publish only after the injected validator succeeds.

    Use with ``store_transaction``. The stage-to-canonical rename is the commit
    point. Journal ordering makes this point discoverable after process death.
    """

    def __init__(self, root: Path, lease: StoreLease) -> None:
        self.root = root
        self.lease = lease
        self.transaction_id = uuid4().hex
        self.record = {"id": self.transaction_id, "phase": "preparing"}
        self.stage, self.previous = _paths(root, self.record)
        self.workspace = _entry(root, f"workspace-{self.transaction_id}")
        self.cleanup_paths: tuple[Path, ...] = ()
        self.after_cleanup: Callable[[Path], object] | None = None
        self.committed = False
        self.generation_id: str | None = None
        _write_journal(root, self.record)

    def register_cleanup(self, paths: tuple[Path, ...]) -> None:
        """Retain caller-managed artifact paths in errors, without deleting them.

        External inputs are not recovery deletion targets. The caller deletes them
        after publication; files inside ``workspace`` are cleaned by this protocol.
        """
        self.cleanup_paths = tuple(dict.fromkeys((*self.cleanup_paths, *paths)))

    def publish(self, validate: Callable[[Path], object]) -> object:
        self.lease.check(self.root)
        if self.committed:
            raise StoreLifecycleError("Transaction has already committed")
        _no_link(self.root)
        _no_link(self.stage)
        validated = validate(self.stage)
        generation_id = getattr(validated, "generation_id", None)
        self.generation_id = generation_id if isinstance(generation_id, str) else None
        self.record["phase"] = "replacing"
        _write_journal(self.root, self.record)
        if self.root.exists():
            os.replace(self.root, self.previous)
        os.replace(self.stage, self.root)
        self.committed = True
        self.record["phase"] = "committed"
        _write_journal(self.root, self.record)
        return validated

    def _finish(self, original: BaseException | None) -> None:
        errors: list[BaseException] = []
        # Infer commit even if interruption occurred immediately after os.replace.
        committed = self.committed or (
            self.record["phase"] in {"replacing", "committed"} and not _exists(self.stage) and self.root.exists()
        )
        self.committed = committed
        if committed:
            self.lease._committed_transaction = self
        if not committed and self.previous.exists() and not self.root.exists():
            try:
                os.replace(self.previous, self.root)
            except OSError as error:
                errors.append(error)
        if not committed and not errors:
            # A killed rollback must not resemble a completed first installation.
            self.record["phase"] = "preparing"
            try:
                _write_journal(self.root, self.record)
            except OSError as error:
                errors.append(error)
        try:
            retain_workspace = (
                original is not None
                and not self.workspace.is_symlink()
                and self.workspace.is_dir()
                and any(self.workspace.iterdir())
            )
        except OSError as error:
            errors.append(error)
            retain_workspace = True
        cleanup_paths = (self.previous,) if committed else (self.stage,)
        if not retain_workspace:
            cleanup_paths += (self.workspace,)
        for path in cleanup_paths:
            try:
                _remove(path)
            except OSError as error:
                errors.append(error)
        if not errors and self.after_cleanup is not None and self.root.exists():
            try:
                self.after_cleanup(self.root)
            except Exception as error:
                errors.append(error)
        if not errors and not retain_workspace:
            for path in (_entry(self.root, "transaction.new"), _entry(self.root, "transaction.json")):
                try:
                    _remove(path)
                except OSError as error:
                    errors.append(error)
        prior = original if isinstance(original, StoreTransactionError) else None
        if errors or prior is not None or (original is not None and (committed or retain_workspace)):
            kind = StorePostCommitCleanupError if committed else StoreTransactionError
            cause = prior.original if prior is not None else original or errors[0]
            raise kind(
                cause,
                cleanup_errors=(*(prior.cleanup_errors if prior is not None else ()), *errors),
                committed_path=self.root if self.root.exists() else self.previous if self.previous.exists() else None,
                transaction_id=self.transaction_id,
                generation_id=self.generation_id if committed else None,
                residue_paths=tuple(
                    dict.fromkeys(
                        (
                            *(p for p in (prior.residue_paths if prior is not None else ()) if _exists(p)),
                            *_residue(self.root),
                            *(p for p in self.cleanup_paths if _exists(p)),
                        )
                    )
                ),
            ) from cause


@contextmanager
def store_transaction(root: Path, *, lease: StoreLease | None = None) -> Iterator[StoreTransaction]:
    root = _root(root)
    with store_lease(root, lease=lease) as acquired:
        _no_link(root)
        if _residue(root):
            raise StoreLifecycleError("Interrupted work or cleanup residue requires explicit recovery")
        transaction = StoreTransaction(root, acquired)
        try:
            yield transaction
        except BaseException as error:
            transaction._finish(error)
            raise
        else:
            transaction._finish(None)


def _discard_pending_seal(root: Path, actions: list[str]) -> None:
    pending = root / ".integrity.pending"
    if _exists(pending):
        if pending.is_symlink() or not pending.is_file():
            raise StoreLifecycleError(f"Malformed pending integrity file: {pending}")
        pending.unlink()
        actions.append(f"removed {pending}")


def recover_store(root: Path, validate: Callable[[Path], object]) -> tuple[str, ...]:
    """Validate the committed candidate before restoring or removing residue.

    Unjournaled generations and conflicting paths refuse without deleting data.
    First-install staging is discarded, never promoted to committed data.
    """
    root = _root(root)
    abandoned = _ownership(root) == Ownership.ABANDONED
    with store_lease(root, recovery=True):
        _no_link(root)
        record = _journal(root)
        residue = _residue(root)
        actions: list[str] = []
        generation_id: str | None = None

        def cleanup_failure(error: OSError, selected: Path | None) -> StoreTransactionError:
            kind = StorePostCommitCleanupError if selected is not None else StoreTransactionError
            pending = selected / ".integrity.pending" if selected is not None else None
            residue = _residue(root)
            if pending is not None and _exists(pending):
                residue += (pending,)
            return kind(
                error,
                cleanup_errors=(error,),
                committed_path=selected,
                transaction_id=record["id"] if record else None,
                generation_id=generation_id,
                residue_paths=residue,
            )

        def validate_candidate(candidate: Path) -> None:
            nonlocal generation_id
            validated = validate(candidate)
            identity = getattr(validated, "generation_id", None)
            generation_id = identity if isinstance(identity, str) else None
            try:
                _discard_pending_seal(candidate, actions)
            except OSError as error:
                raise cleanup_failure(error, candidate) from error

        if abandoned:
            actions.append(f"released abandoned ownership: {_entry(root, 'owner')}")
        if record is None:
            temporary = _entry(root, "transaction.new")
            if any(path != temporary for path in residue):
                raise StoreLifecycleError("Unjournaled store residue; cannot infer committed generation")
            if _exists(temporary) and (temporary.is_symlink() or not temporary.is_file()):
                raise StoreLifecycleError(f"Malformed pending transaction file: {temporary}")
            if root.exists():
                validate_candidate(root)
            if _exists(temporary):
                try:
                    _remove(temporary)
                except OSError as error:
                    raise cleanup_failure(error, root if root.exists() else None) from error
                actions.append(f"removed {temporary}")
            return tuple(actions)
        stage, previous = _paths(root, record)
        workspace = _entry(root, f"workspace-{record['id']}")
        allowed = {stage, previous, workspace, _entry(root, "transaction.json"), _entry(root, "transaction.new")}
        if any(p not in allowed for p in residue):
            raise StoreLifecycleError("Multiple transactions; recovery is ambiguous")
        for path in (stage, previous, workspace):
            _no_link(path)
        installed = record["phase"] in {"replacing", "committed"} and not stage.exists() and root.exists()
        if installed:
            validate_candidate(root)
            actions.append(f"kept committed store: {root}")
        elif record["phase"] == "committed":
            raise StoreLifecycleError("Committed store missing or conflicting stage; refusing backup restoration")
        elif previous.exists() and record["phase"] == "preparing":
            raise StoreLifecycleError("Previous store contradicts preparation journal")
        elif root.exists() and previous.exists():
            raise StoreLifecycleError("Conflicting committed paths")
        elif previous.exists():
            validate_candidate(previous)
            os.replace(previous, root)
            actions.append(f"restored previous store: {previous} -> {root}")
        elif root.exists():
            validate_candidate(root)
            actions.append(f"kept previous store: {root}")
        elif record["phase"] == "replacing" and not stage.exists():
            raise StoreLifecycleError("No recoverable store or staged candidate")
        if not installed:
            record["phase"] = "preparing"
            _write_journal(root, record)
        for path in (stage, previous, workspace, _entry(root, "transaction.new"), _entry(root, "transaction.json")):
            if _exists(path):
                try:
                    _remove(path)
                except OSError as error:
                    raise cleanup_failure(error, root if root.exists() else None) from error
                actions.append(f"removed {path}")
        return tuple(actions)


def managed_paths(root: Path) -> tuple[Path, ...]:
    """List owned paths lexically, without trusting a transaction journal.

    Acquire ``store_lease`` when using this list for deletion accounting. The
    permanent ownership file is excluded from requested cache data.
    """
    root = _root(root)
    return tuple(path for path in (root, *_residue(root)) if _exists(path))


def clear_store(root: Path, *, extra_paths: tuple[Path, ...] = (), lease: StoreLease | None = None) -> tuple[Path, ...]:
    """Remove owned state, never symlink targets or unrelated siblings.

    Explicit extra paths must be immediate children of the resolved store parent.
    The permanent coordination file remains. Active or ambiguous ownership refuses.
    """
    root = _root(root)
    extras = tuple(root.parent / p.name for p in extra_paths)
    if any(Path(p).absolute().parent.resolve() != root.parent for p in extra_paths):
        raise StoreLifecycleError("Clear paths must belong to the store parent")
    if any(p == _entry(root, "owner") for p in extras):
        raise StoreLifecycleError("Cannot remove permanent ownership file")
    with store_lease(root, lease=lease, recovery=True):
        removed: list[Path] = []
        for path in dict.fromkeys((root, *_residue(root), *extras)):
            if _exists(path):
                _remove(path)
                removed.append(path)
        return tuple(removed)
