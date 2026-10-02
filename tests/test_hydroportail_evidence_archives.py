"""Lossless HydroPortail source evidence retains every captured byte."""

import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath

import pytest

EVIDENCE = Path(__file__).parent / "test_data/fr_hydroportail_variants"
MANIFEST = json.loads((EVIDENCE / "evidence-archives.json").read_text())


@pytest.mark.parametrize("identity", MANIFEST["archives"], ids=lambda item: item["path"])
@pytest.mark.recorded("tests/test_data/fr_hydroportail_variants")
def test_evidence_archive_preserves_original_members(retained_evidence_root, identity):
    path = retained_evidence_root / "tests/test_data/fr_hydroportail_variants" / identity["path"]
    content = path.read_bytes()
    assert len(content) == identity["bytes"]
    assert hashlib.sha256(content).hexdigest() == identity["sha256"]
    expected = {member["name"]: member for member in identity["members"]}
    with tarfile.open(path, "r:xz") as archive:
        members = archive.getmembers()
        assert len(members) == len(expected)
        assert set(archive.getnames()) == set(expected)
        assert sum(member.size for member in members) == identity["original_bytes"]
        for member in members:
            name = PurePosixPath(member.name)
            assert member.isfile() and not member.issym() and not member.islnk()
            assert not name.is_absolute() and len(name.parts) == 1 and ".." not in name.parts
            source = archive.extractfile(member)
            assert source is not None
            body = source.read()
            assert len(body) == expected[member.name]["bytes"]
            assert hashlib.sha256(body).hexdigest() == expected[member.name]["sha256"]
