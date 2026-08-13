from pathlib import Path

import pytest

from rivretrieve._internal.store import (
    CertificationError,
    DecodedPublisherArtifact,
    SourceColumn,
    SourceUnitCount,
    certify_compile,
)
from tests.store.certification_support import artifact_and_request, rows


def test_undeclared_source_column_preserves_previous_store_and_artifact(tmp_path: Path) -> None:
    artifact, request = artifact_and_request(tmp_path)
    destination = Path(request.destination)
    destination.mkdir()
    sentinel = destination / "previous-store"
    sentinel.write_text("unchanged")
    observed = (*request.source_columns, SourceColumn("surprise", "text"))

    def decode(_artifact: Path) -> DecodedPublisherArtifact:
        return DecodedPublisherArtifact(rows(), observed, (SourceUnitCount("1998.csv", 1, 1),))

    with pytest.raises(CertificationError, match=r"undeclared=\['surprise'\]"):
        certify_compile(request, artifact, decode)

    assert sentinel.read_text() == "unchanged"
    assert artifact.exists()
    assert not list(tmp_path.glob(".store.staging-*"))
