from __future__ import annotations

from pathlib import Path

import pytest

from rivretrieve._internal.store import certify_store, validate_store
from rivretrieve._internal.store.lifecycle import StorePostCommitCleanupError, recover_store
from tests.store.certification_support import artifact_and_request, complete, rows


def test_artifact_deletion_failure_keeps_new_committed_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    with pytest.raises(StorePostCommitCleanupError) as caught:
        certify_store(request, artifact, lambda _: complete(rows()))

    assert isinstance(caught.value.original, PermissionError)
    assert caught.value.committed_path == destination
    assert artifact in caught.value.residue_paths
    assert not sentinel.exists()
    validate_store(request.destination, request.provider_id)
    recover_store(destination, lambda path: validate_store(path, request.provider_id))
    assert artifact.is_file()
    assert not list(tmp_path.glob(".store.staging-*"))
    assert not list(tmp_path.glob(".store.previous-*"))
