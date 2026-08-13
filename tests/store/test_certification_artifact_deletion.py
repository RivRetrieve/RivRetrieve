from __future__ import annotations

from pathlib import Path

import pytest

from rivretrieve._internal.store import certify_store
from tests.store.certification_support import artifact_and_request, complete, rows


def test_artifact_deletion_failure_restores_previous_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact, request = artifact_and_request(tmp_path)
    destination = Path(request.destination)
    destination.mkdir()
    sentinel = destination / "previous-store"
    sentinel.write_text("unchanged", encoding="utf-8")
    real_unlink = Path.unlink

    def fail_artifact_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == artifact:
            raise PermissionError("publisher artifact is read-only")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_artifact_unlink)

    with pytest.raises(PermissionError, match="read-only"):
        certify_store(request, artifact, lambda _: complete(rows()))

    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    assert artifact.is_file()
    assert not list(tmp_path.glob(".store.staging-*"))
    assert not list(tmp_path.glob(".store.previous-*"))
