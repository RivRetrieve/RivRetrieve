"""Additional disk-growth estimates for compilation and source replay.

Admission compares estimates with current free space; it reserves nothing. Native
SQLite routing is reconstructed only for the default OS VFS with SQLITE_TMPDIR and
TMPDIR set before process startup and unchanged for the process lifetime. SQLite
can cache its initialization-time environment; this module cannot recover that
state after late changes. Such sessions and custom VFS routing are unsupported.
SQLite global temp settings must remain unchanged during compilation. Source
inputs, previous stores and existing candidates already occupy space and must not
be charged again.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId


class FreeSpaceProbe(Protocol):
    def __call__(self, path: Path) -> int: ...


def available_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


class CompilationPhase(StrEnum):
    EXTRACTION = "source extraction"
    COMPILE = "compilation"
    REPLAY = "certification replay"


@dataclass(frozen=True, slots=True)
class CompilationSpaceEstimate:
    """Additional bytes on the managed workspace and native SQLite temp filesystems."""

    phase: CompilationPhase
    workspace_bytes: int
    sqlite_temp_bytes: int = 0

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in (self.workspace_bytes, self.sqlite_temp_bytes)):
            raise ValueError("Additional disk estimates must be non-negative integer bytes")


class InsufficientPreparationSpaceError(FatalContractError):
    """An estimated later phase exceeds free space; inputs may already be downloaded."""

    def __init__(self, provider_id: ProviderId, phase: CompilationPhase, path: Path, required: int, available: int):
        self.provider_id = provider_id
        self.phase = phase
        self.path = path
        self.required_bytes = required
        self.available_bytes = available
        super().__init__(
            f"Cannot prepare {provider_id}: {phase} estimates {required} additional bytes on {path}, "
            f"but only {available} bytes are available. Admission estimates do not reserve space."
        )


@dataclass(frozen=True, slots=True)
class CompilationResources:
    """Resolved destinations and free-space probe for one owned compilation."""

    provider_id: ProviderId
    workspace: Path
    free_space_probe: FreeSpaceProbe
    sqlite_temp: Path | None = None

    def check(self, estimate: CompilationSpaceEstimate) -> None:
        demands = [(self.workspace, estimate.workspace_bytes)]
        if estimate.sqlite_temp_bytes:
            if self.sqlite_temp is None:
                raise ValueError("SQLite temporary storage must be resolved before admission")
            demands.append((self.sqlite_temp, estimate.sqlite_temp_bytes))
        grouped: dict[int, tuple[Path, int]] = {}
        for path, additional in demands:
            if not additional:
                continue
            device = path.stat().st_dev
            existing_path, existing_bytes = grouped.get(device, (path, 0))
            rounded = ((additional + 4095) // 4096) * 4096
            grouped[device] = existing_path, existing_bytes + rounded
        for path, required in grouped.values():
            available = self.free_space_probe(path)
            if available < required:
                raise InsufficientPreparationSpaceError(self.provider_id, estimate.phase, path, required, available)


# Compact synthetic journals use about 108 bytes/unit; 160 includes allocation
# headroom. The 64 MiB term is explicit metadata headroom, not measured demand.
# Provider output/sorting allowances remain estimates; national acceptance must
# compare them with actual workspaces. These checks never reserve space.
def compiled_store_growth(phase: CompilationPhase, records: int, output_bytes: int) -> int:
    """Estimate future journal, provider-estimated output and metadata bytes."""
    metadata = 64 * 1024**2
    if phase is CompilationPhase.REPLAY:
        return metadata
    if phase is not CompilationPhase.COMPILE:
        raise ValueError("Store-growth estimates require compilation or replay phase")
    journal = 160 * records
    return journal + output_bytes + metadata


def _sqlite_temp_override() -> str | None:
    connection = sqlite3.connect(":memory:")
    try:
        row = connection.execute("PRAGMA temp_store_directory").fetchone()
        return str(row[0]) if row and row[0] else None
    finally:
        connection.close()


def _windows_temp_directory() -> str:
    import ctypes

    # The desktop Win32 VFS in SQLite 3.53.1 uses GetTempPathW, not
    # GetTempPath2W: https://sqlite.org/src/raw/src/os_win.c?ci=version-3.53.1
    function = vars(ctypes)["windll"].kernel32.GetTempPathW
    buffer = ctypes.create_unicode_buffer(32768)
    length = function(len(buffer), buffer)
    if not 0 < length < len(buffer):
        raise OSError("Cannot resolve the native Windows temporary directory")
    return buffer.value


def resolve_sqlite_temp_directory() -> Path:
    """Reconstruct default-VFS routing under an unchanged startup environment.

    Set SQLITE_TMPDIR and TMPDIR before process startup and leave them unchanged
    for the process lifetime. SQLite can cache its initialization-time environment;
    this function cannot recover that state after late changes. Such sessions are
    unsupported even when their environment stays fixed during compilation.

    Unix follows SQLite's writable-directory search. Desktop Win32 uses
    GetTempPathW, as in the reviewed SQLite 3.53.1 default VFS. Cygwin, UWP and
    custom VFS routing are not covered. SQLite global temp settings must not change
    during compilation. This function changes no globals and relocates no files.
    """
    if sys.platform == "cygwin":
        raise RuntimeError("Cannot estimate the Cygwin SQLite temporary-directory search")
    override = _sqlite_temp_override()
    if override:
        path = Path(override).resolve()
        if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
            raise OSError("Configured SQLite temporary directory is unavailable")
        return path
    if sys.platform == "win32":
        candidates = (_windows_temp_directory(),)
    elif os.name == "posix":
        candidates = (
            os.environ.get("SQLITE_TMPDIR"),
            os.environ.get("TMPDIR"),
            "/var/tmp",
            "/usr/tmp",
            "/tmp",
            str(Path.cwd()),
        )
    else:
        raise RuntimeError("Cannot estimate SQLite temporary storage for this native platform")
    for candidate in candidates:
        if candidate:
            path = Path(candidate).resolve()
            if path.is_dir() and os.access(path, os.W_OK | os.X_OK):
                return path
    raise OSError("No usable native SQLite temporary directory")
