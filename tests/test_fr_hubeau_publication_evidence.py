"""Official publication documents retain exact source identities and limited role claims."""

import hashlib
import json
from pathlib import Path

import pytest

_TEST_DATA = Path(__file__).parent / "test_data"
_MANIFEST = json.loads((_TEST_DATA / "fr_official_publication_manifest.json").read_text())


@pytest.mark.parametrize("entry", _MANIFEST["source_documents"], ids=lambda entry: entry["scope"])
def test_official_publication_document_is_exact_retained_body(retained_evidence_root, entry: dict) -> None:
    acquisition = entry["acquisition"]
    material = acquisition["material"]
    body = (retained_evidence_root / entry["repository_path"]).read_bytes()
    assert len(body) == material["byte_count"]
    assert hashlib.sha256(body).hexdigest() == material["sha256"]
    assert entry["retained_source"] == material["filename"]
    assert acquisition["http_status"] == 200
    assert acquisition["retrieved_at_start"].startswith("2026-09-13T")
    assert entry["limitation"] == (
        "Publication/platform responsibility does not establish original authorship of each historical measurement."
    )


def test_dataset_author_credit_is_not_resolved_by_platform_publication() -> None:
    assert _MANIFEST["citation_interpretation_limit"] == (
        "The requested dataset-author credit is not resolved by naming a platform publisher."
    )
