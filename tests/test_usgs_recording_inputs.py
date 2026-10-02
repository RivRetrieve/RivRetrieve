"""Synthetic checks for explicit replay input selection, without archive access."""

import hashlib
import json

import pytest

from tests.usgs_modern_recordings import ModernReplay, body, manifest


def test_replay_requires_manifests_in_supplied_root(tmp_path):
    with pytest.raises(FileNotFoundError, match="recording manifests are required"):
        manifest(tmp_path)
    with pytest.raises(FileNotFoundError, match="recording manifests are required"):
        ModernReplay("authored", evidence_root=tmp_path)


def test_replay_reads_and_validates_only_explicit_inputs(tmp_path):
    directory = tmp_path / "tests/test_data/usgs_modern"
    directory.mkdir(parents=True)
    content = b'{"authored":true}'
    entry = {
        "name": "authored",
        "file": "authored.body",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "original_url": "https://example.org/items?f=json",
    }
    (directory / "authored-manifest.jsonl").write_text(json.dumps(entry) + "\n")
    path = directory / "authored.body"
    path.write_bytes(content)
    assert manifest(tmp_path) == {"authored": entry}
    assert body("authored", tmp_path) == content
    replay = ModernReplay("authored", evidence_root=tmp_path)
    assert len(replay.entries) == 1
    path.write_bytes(b"changed")
    with pytest.raises(AssertionError):
        body("authored", tmp_path)
