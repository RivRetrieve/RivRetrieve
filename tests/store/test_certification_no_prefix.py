from pathlib import Path

import pytest

from rivretrieve._internal.store import CertificationError, DecodedPublisherArtifact, SourceUnitCount, certify_compile
from tests.store.certification_support import artifact_and_request, rows


def test_truncated_earlier_member_prevents_later_valid_prefix_being_published(tmp_path: Path) -> None:
    artifact, request = artifact_and_request(tmp_path)

    def decode(_artifact: Path) -> DecodedPublisherArtifact:
        return DecodedPublisherArtifact(
            rows(year=1998),
            request.source_columns,
            (
                SourceUnitCount("1997.csv", 2, 1),
                SourceUnitCount("1998.csv", 1, 1),
            ),
        )

    with pytest.raises(CertificationError, match="1997.csv"):
        certify_compile(request, artifact, decode)

    assert not Path(request.destination).exists()
    assert artifact.exists()
    assert not list(tmp_path.glob(".store.staging-*"))
