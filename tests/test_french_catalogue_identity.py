"""Superseded combined catalogues cannot acquire HubEau-only meaning."""

from pathlib import Path

import pytest

from rivretrieve._internal.catalogues import artifact


def test_combined_catalogue_refused_before_observation_metadata(monkeypatch):
    path = Path(__file__).parent / "test_data/french_combined_catalogue"
    before = {file.name: file.read_bytes() for file in path.iterdir()}

    def forbidden(*args, **kwargs):
        pytest.fail("old combined catalogue reached Parquet decoding")

    monkeypatch.setattr(artifact.pl, "read_parquet", forbidden)
    with pytest.raises(artifact.CorruptCatalogArtifactError, match="publication service"):
        artifact.load_packaged_catalogue_artifact(path)
    assert {file.name: file.read_bytes() for file in path.iterdir()} == before


def test_other_provider_catalogue_keeps_existing_format():
    path = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/usgs_nwis/catalogue"
    loaded = artifact.load_packaged_catalogue_artifact(path)
    assert loaded.provider_info["provider_id"] == "usgs_nwis"


def test_combined_catalogue_is_authenticated_baseline():
    import hashlib
    import json

    data = Path(__file__).parent / "test_data"
    identity = json.loads((data / "french_combined_catalogue.identity.json").read_text())
    assert identity["capture"]["producer_revision"] == "fd55eee9d32a278b895bc61487452d43564eaed4"
    for name, expected in identity["files"].items():
        content = (data / "french_combined_catalogue" / name).read_bytes()
        assert len(content) == expected["byte_count"]
        assert hashlib.sha256(content).hexdigest() == expected["sha256"]
