from pathlib import Path

import pytest

from rivretrieve._internal.store import (
    NativeStoreMaterialization,
    SourceColumn,
    SourceUnitCount,
    StoreCertificationError,
    certify_store,
)
from tests.store.certification_support import artifact_and_request, rows


def test_undeclared_source_column_preserves_previous_store_and_artifact(tmp_path: Path) -> None:
    artifact, request = artifact_and_request(tmp_path)
    destination = Path(request.destination)
    destination.mkdir()
    sentinel = destination / "previous-store"
    sentinel.write_text("unchanged")
    observed = (*request.source_columns, SourceColumn("surprise", "text"))

    def decode(_artifact: Path) -> NativeStoreMaterialization:
        return NativeStoreMaterialization(rows(), observed, (SourceUnitCount("1998.csv", 1, 1),))

    with pytest.raises(StoreCertificationError, match=r"undeclared=\['surprise'\]"):
        certify_store(request, artifact, decode)

    assert sentinel.read_text() == "unchanged"
    assert artifact.exists()
    assert not list(tmp_path.glob(".store.staging-*"))
