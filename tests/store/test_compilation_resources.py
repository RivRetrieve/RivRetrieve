"""Admission uses additional growth and the filesystems that receive it."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store.resources import (
    CompilationPhase,
    CompilationResources,
    CompilationSpaceEstimate,
    InsufficientPreparationSpaceError,
    compiled_store_growth,
    resolve_sqlite_temp_directory,
)


def test_compile_and_replay_estimate_only_future_growth() -> None:
    # Journal=160*10; the provider supplies its output estimate separately.
    assert compiled_store_growth(CompilationPhase.COMPILE, 10, 720) == 64 * 1024**2 + 2320
    assert compiled_store_growth(CompilationPhase.REPLAY, 10, 720) == 64 * 1024**2
    assert compiled_store_growth(CompilationPhase.COMPILE, 20, 1440) == 64 * 1024**2 + 4640


@pytest.mark.parametrize("same_device", [False, True])
def test_workspace_and_native_sort_demands_group_by_device(tmp_path, monkeypatch, same_device) -> None:
    workspace = tmp_path / "workspace"
    native = tmp_path / "native"
    workspace.mkdir()
    native.mkdir()
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path in (workspace, native):
            return SimpleNamespace(st_dev=1 if same_device or path == workspace else 2)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    probed = []

    def free(path):
        probed.append(path)
        return 12288 if same_device else (4096 if path == workspace else 8192)

    resources = CompilationResources(ProviderId("ca_eccc"), workspace, free, native)
    resources.check(CompilationSpaceEstimate(CompilationPhase.COMPILE, 1, 4097))
    assert probed == ([workspace] if same_device else [workspace, native])


def test_later_refusal_reports_phase_and_preserves_inputs(tmp_path) -> None:
    original = tmp_path / "publisher.zip"
    original.write_bytes(b"source")
    resources = CompilationResources(ProviderId("pl_imgw"), tmp_path, lambda _: 4095)
    with pytest.raises(InsufficientPreparationSpaceError) as caught:
        resources.check(CompilationSpaceEstimate(CompilationPhase.REPLAY, 1))
    assert caught.value.required_bytes == 4096
    assert caught.value.available_bytes == 4095
    assert "replay" in str(caught.value)
    assert "No download was started" not in str(caught.value)
    assert original.read_bytes() == b"source"


def test_sqlite_directory_policy_prioritizes_sqlite_over_python_temp(tmp_path, monkeypatch) -> None:
    from rivretrieve._internal.store import resources

    native = tmp_path / "sqlite"
    python_temp = tmp_path / "python"
    native.mkdir()
    python_temp.mkdir()
    monkeypatch.setenv("SQLITE_TMPDIR", str(native))
    monkeypatch.setenv("TMPDIR", str(python_temp))
    monkeypatch.setattr(resources, "_sqlite_temp_override", lambda: None)
    monkeypatch.setattr(resources.sys, "platform", "linux")
    assert resolve_sqlite_temp_directory() == native
    monkeypatch.setattr(resources, "_sqlite_temp_override", lambda: str(python_temp))
    assert resolve_sqlite_temp_directory() == python_temp


def test_windows_temp_resolution_uses_native_backend(tmp_path, monkeypatch) -> None:
    from rivretrieve._internal.store import resources

    monkeypatch.setattr(resources.sys, "platform", "win32")
    monkeypatch.setattr(resources, "_sqlite_temp_override", lambda: None)
    monkeypatch.setattr(resources, "_windows_temp_directory", lambda: str(tmp_path))
    assert resolve_sqlite_temp_directory() == tmp_path


def test_imgw_admission_uses_census_and_maximum_active_year(tmp_path) -> None:
    import zipfile

    from rivretrieve._internal.providers.pl_imgw import bulk

    sources = (
        ("codz_2022.zip", "1;S;R;2022;01;01;100;1;2;11\r\n1;S;R;2022;03;01;100;1;2;1\r\n"),
        ("codz_2023.zip", "1;S;R;2023;01;01;100;1;2;11\r\n"),
    )
    paths = []
    expanded = sum(len(body.encode()) for _, body in sources)
    for name, body in sources:
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(path.stem + ".csv", body)
        paths.append(path)
    estimates = []
    resources = SimpleNamespace(check=estimates.append)
    for phase in (CompilationPhase.COMPILE, CompilationPhase.REPLAY):
        bulk.decode_imgw_batches(tuple(paths), resources=resources, phase=phase)
    # Calendar 2022 has two records and both archives can contribute to it.
    sort_growth = (3 * (1024 * 2 + expanded) + 1) // 2
    assert estimates == [
        CompilationSpaceEstimate(CompilationPhase.COMPILE, 64 * 1024**2 + 160 * 3 + 24 * 9 + sort_growth),
        CompilationSpaceEstimate(CompilationPhase.REPLAY, 64 * 1024**2 + sort_growth),
    ]


@pytest.mark.parametrize("zipped", [False, True])
def test_hydat_admission_reuses_month_census_and_accounts_native_sort(tmp_path, zipped) -> None:
    import zipfile

    from rivretrieve._internal.providers.ca_eccc import bulk
    from tests.store.test_ca_eccc_streaming import _representative_hydat

    database = tmp_path / "Hydat.sqlite3"
    _representative_hydat(database)
    expanded = database.stat().st_size
    artifact = database
    extraction = 0
    if zipped:
        artifact = tmp_path / "Hydat.zip"
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.write(database, database.name)
        extraction = expanded
    estimates = []
    resources = SimpleNamespace(check=estimates.append)
    for phase in (CompilationPhase.COMPILE, CompilationPhase.REPLAY):
        bulk.decode_hydat_batches(artifact, resources=resources, phase=phase)
    full = [item for item in estimates if item.phase is not CompilationPhase.EXTRACTION]
    assert full == [
        CompilationSpaceEstimate(
            CompilationPhase.COMPILE,
            extraction + 64 * 1024**2 + 160 * 10 + max(24 * 304, (expanded + 1) // 2),
            (3 * expanded + 1) // 2,
        ),
        CompilationSpaceEstimate(CompilationPhase.REPLAY, extraction + 64 * 1024**2, (3 * expanded + 1) // 2),
    ]
    assert [item.workspace_bytes for item in estimates if item.phase is CompilationPhase.EXTRACTION] == (
        [expanded, expanded] if zipped else []
    )


def test_late_imgw_sort_disk_failure_preserves_prior_and_external_original(tmp_path, monkeypatch) -> None:
    import errno
    import sqlite3

    from rivretrieve._internal.store.lifecycle import StoreTransactionError
    from tests.store.test_pl_imgw_multi_artifact import _compile_declared, _tiny_artifact

    root = tmp_path / "store"
    first = _tiny_artifact(tmp_path, "codz_2022_03.zip", b"1;S;R;2022;03;01;100;1;2;1\r\n")
    _compile_declared((first,), root)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    artifact = _tiny_artifact(tmp_path, "codz_2022_03.zip", b"1;S;R;2022;03;01;100;3;4;1\r\n")
    original_bytes = artifact.path.read_bytes()
    connect = sqlite3.connect
    inserted = []

    class Connection(sqlite3.Connection):
        def executemany(self, sql, parameters):
            result = super().executemany(sql, parameters)
            if sql.startswith("INSERT INTO rows"):
                inserted.append(True)
                raise OSError(errno.ENOSPC, "synthetic late disk failure")
            return result

    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connect(*args, factory=Connection, **kwargs))
    with pytest.raises((OSError, StoreTransactionError)) as caught:
        _compile_declared((artifact,), root)
    error = caught.value.original if isinstance(caught.value, StoreTransactionError) else caught.value
    assert isinstance(error, OSError) and error.errno == errno.ENOSPC
    assert inserted
    assert artifact.path.read_bytes() == original_bytes
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_unix_directory_policy_falls_back_from_unavailable_override(tmp_path, monkeypatch) -> None:
    from rivretrieve._internal.store import resources

    monkeypatch.setattr(resources.sys, "platform", "linux")
    monkeypatch.delenv("SQLITE_TMPDIR", raising=False)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(resources, "_sqlite_temp_override", lambda: str(tmp_path / "absent"))
    assert resolve_sqlite_temp_directory() == tmp_path


def test_hydat_checks_exact_extraction_before_creating_payload(tmp_path, monkeypatch) -> None:
    import zipfile

    from rivretrieve._internal.providers.ca_eccc import bulk
    from tests.store.test_ca_eccc_streaming import _representative_hydat

    database = tmp_path / "Hydat.sqlite3"
    _representative_hydat(database)
    artifact = tmp_path / "Hydat.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.write(database, database.name)
    original = artifact.read_bytes()
    resources = CompilationResources(ProviderId("ca_eccc"), tmp_path, lambda _: 0, tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Extraction must not start after failed admission")

    monkeypatch.setattr(bulk.tempfile, "TemporaryDirectory", forbidden)
    with pytest.raises(InsufficientPreparationSpaceError) as caught:
        bulk.decode_hydat_batches(artifact, resources=resources)
    assert caught.value.phase is CompilationPhase.EXTRACTION
    assert caught.value.required_bytes >= database.stat().st_size
    assert artifact.read_bytes() == original


def test_unix_directory_policy_skips_unavailable_directories(tmp_path, monkeypatch) -> None:
    from rivretrieve._internal.store import resources

    sqlite_dir = tmp_path / "sqlite"
    python_dir = tmp_path / "python"
    fallback = Path("/var/tmp").resolve()
    usable = {sqlite_dir, python_dir, fallback}
    checked = []
    monkeypatch.setattr(resources.sys, "platform", "linux")
    monkeypatch.setattr(resources, "_sqlite_temp_override", lambda: None)
    monkeypatch.setenv("SQLITE_TMPDIR", str(sqlite_dir))
    monkeypatch.setenv("TMPDIR", str(python_dir))
    monkeypatch.setattr(Path, "is_dir", lambda path: path in usable)

    def access(path, mode):
        checked.append(path)
        return path == fallback

    monkeypatch.setattr(resources.os, "access", access)
    assert resolve_sqlite_temp_directory() == fallback
    assert checked == [sqlite_dir, python_dir, fallback]


def test_native_sqlite_temp_resolution_refuses_cygwin(monkeypatch) -> None:
    from rivretrieve._internal.store import resources

    monkeypatch.setattr(resources.sys, "platform", "cygwin")
    with pytest.raises(RuntimeError, match="Cygwin"):
        resolve_sqlite_temp_directory()


@pytest.mark.parametrize(("expanded", "additional"), [(300, 2878), (2092, 10942)])
def test_imgw_estimate_includes_excess_source_width(tmp_path, expanded, additional) -> None:
    import zipfile

    from rivretrieve._internal.providers.pl_imgw import bulk

    base = "1;;R;2022;03;01;100;1;2;1\r\n"
    body = base.replace(";;", ";" + "S" * (expanded - len(base)) + ";")
    assert len(body.encode()) == expanded
    path = tmp_path / "codz_2022_03.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", body)
    estimates = []
    bulk.decode_imgw_batches(path, resources=SimpleNamespace(check=estimates.append))
    # One record, three output rows. Includes journal, excess-width output,
    # maintained ordering and metadata. Expected numbers are worked by hand.
    assert estimates == [CompilationSpaceEstimate(CompilationPhase.COMPILE, 64 * 1024**2 + additional)]


def test_sqlite_resolution_in_process_with_startup_temp_environment(tmp_path) -> None:
    import os
    import subprocess
    import sys

    if os.name != "posix":
        pytest.skip("This startup-environment control exercises the Unix directory policy")
    native = tmp_path / "native"
    fallback = tmp_path / "fallback"
    native.mkdir()
    fallback.mkdir()
    code = """
import os
import sqlite3
from pathlib import Path
from rivretrieve._internal.store.resources import resolve_sqlite_temp_directory
connection = sqlite3.connect(":memory:")
connection.close()
assert resolve_sqlite_temp_directory() == Path(os.environ["SQLITE_TMPDIR"])
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={**os.environ, "SQLITE_TMPDIR": str(native), "TMPDIR": str(fallback)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
