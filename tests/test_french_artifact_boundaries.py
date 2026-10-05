"""Pre-split public artifacts must not acquire new publication-service identities."""

import json
import shutil
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery, export_bundle
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store import ObservationStoreRefusedError, StoreRoot, validation
from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
from tests.store.test_integrity import _resign

_ARTIFACT_ARCHIVE = Path("tests/test_data/french_combined_artifacts.tar.xz")
_BUNDLES = (
    "combined-station-selection.bundle",
    "empty-selection.bundle",
    "unrestricted-empty-selection.bundle",
    "context-only-empty-selection.bundle",
    "hydroportail-selection.bundle",
    "hubeau-daily-selection.bundle",
    "hydroportail-result-receipts-False.bundle",
    "hydroportail-result-receipts-True.bundle",
    "hubeau-daily-result-receipts-False.bundle",
    "hubeau-daily-result-receipts-True.bundle",
)


@pytest.fixture(scope="module")
def artifacts(retained_evidence_root, tmp_path_factory):
    import tarfile

    root = tmp_path_factory.mktemp("combined-french-artifacts")
    with tarfile.open(retained_evidence_root / _ARTIFACT_ARCHIVE) as archive:
        archive.extractall(root, filter="data")
    return root


def _files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _no_values(*args, **kwargs):
    pytest.fail("stale publication identity reached observation values")


@pytest.mark.parametrize("name", _BUNDLES)
@pytest.mark.derived("tests/test_data/french_combined_artifacts.tar.xz")
def test_combined_bundle_refused_before_values(name, monkeypatch, artifacts):
    path = artifacts / name
    content = path.read_bytes()
    monkeypatch.setattr(export_bundle.pl, "read_parquet", _no_values)
    with pytest.raises(ValueError, match="publication.service"):
        rr.from_bundle(content)
    assert path.read_bytes() == content


@pytest.mark.parametrize("operation", ("status", "reuse", "refresh"))
@pytest.mark.derived("tests/test_data/french_combined_artifacts.tar.xz")
def test_combined_store_refused_before_values_or_network(operation, tmp_path, monkeypatch, artifacts):
    cache = tmp_path / "cache"
    shutil.copytree(artifacts / "store", cache / "fr_hubeau/store")
    before = _files(cache)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(cache))
    monkeypatch.setattr(validation, "_open_parquet", _no_values)

    class NoNetwork:
        def send(self, request):
            pytest.fail("stale publication identity reached source transport")

    monkeypatch.setattr(discovery, "HttpClient", NoNetwork)
    with pytest.raises(ObservationStoreRefusedError, match="unsupported format revision 7"):
        if operation == "status":
            rr.cache_status("fr_hubeau")
        else:
            selection = rr.find(
                provider="fr_hubeau",
                station="1011000101",
                quantity="discharge",
                frequency="daily",
                statistic="mean",
            )
            rr.fetch(selection, start="2025-01-03", end="2025-01-03", cache=operation, on_issue="ignore")
    assert _files(cache) == before


@pytest.mark.derived("tests/test_data/french_combined_artifacts.tar.xz")
def test_fixture_bytes_match_baseline_attestation(artifacts):
    import hashlib

    attestation = json.loads((artifacts / "attestation.json").read_text())
    for name in (*_BUNDLES, "capture.py", "capture_unrestricted_empty.py", "capture_context_only_empty.py"):
        content = (artifacts / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == attestation["files"][name]["sha256"]
    for name, content in _files(artifacts / "store").items():
        assert hashlib.sha256(content).hexdigest() == attestation["files"]["cache/fr_hubeau/store/" + name]["sha256"]


@pytest.mark.recorded("tests/test_data/fr_hubeau_1011000101_QmnJ_padded.recording.json")
def test_service_specific_daily_store_and_bundles_round_trip(retained_evidence_root, tmp_path, monkeypatch):
    from io import BytesIO
    from zipfile import ZipFile

    from polars.testing import assert_frame_equal

    from rivretrieve._internal.recordings import ReplayTransport

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recording = retained_evidence_root / "tests/test_data/fr_hubeau_1011000101_QmnJ_padded.recording.json"
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="fr_hubeau",
        station="1011000101",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
    )
    result = rr.fetch(selection, start="2025-01-03", end="2025-01-03", cache="reuse", on_issue="raise")
    assert result.data.height > 0
    manifest = json.loads((tmp_path / "fr_hubeau/store/manifest.json").read_text())
    assert manifest["format_version"] == 8
    assert manifest["publication_service"] == "hubeau"
    assert rr.cache_status("fr_hubeau").exists
    for value in (selection, result):
        content = rr.to_bundle(value)
        with ZipFile(BytesIO(content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == 2
        assert manifest["publication_service"] == "hubeau"
        restored = rr.from_bundle(content)
        assert_frame_equal(rr.series(restored), rr.series(value))
    assert_frame_equal(rr.from_bundle(rr.to_bundle(result)).data, result.data)

    class NoNetwork:
        def send(self, request):
            pytest.fail("service-specific covered store unexpectedly reached network")

    monkeypatch.setattr(discovery, "HttpClient", NoNetwork)
    concrete = rr.pick(selection, series_id=result.data["series_id"][0], on_issue="ignore")
    repeated = rr.fetch(concrete, start="2025-01-03", end="2025-01-03", cache="reuse", on_issue="raise")
    assert_frame_equal(repeated.data, result.data)


@pytest.mark.derived("tests/test_data/french_combined_artifacts.tar.xz")
def test_context_only_empty_bundle_has_no_direct_french_identity(artifacts):
    from io import BytesIO
    from zipfile import ZipFile

    with ZipFile(BytesIO((artifacts / "context-only-empty-selection.bundle").read_bytes())) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["scope"]["provider_ids"] == []
    assert all(item["provider_id"] != "fr_hubeau" for item in manifest["series"])
    assert all(item["provider_id"] != "fr_hubeau" for item in manifest["locations"])
    assert all("fr_hubeau" not in item["scope"]["provider_ids"] for item in manifest["inventories"])
    assert any(item["header"]["provider_id"] == "fr_hubeau" for item in manifest["catalogue_evidence"])


def test_current_context_only_empty_bundle_round_trip():
    selection = rr.find(station="07374000", quantity="temperature", statistic="max")
    assert not selection.scope.provider_ids
    assert not selection.series
    assert all(item.provider_id != "fr_hubeau" for item in selection.known_series)
    assert any(item.header.provider_id == "fr_hubeau" for item in selection.acquisition_provenance)
    restored = rr.from_bundle(rr.to_bundle(selection))
    assert restored.scope == selection.scope
    assert restored.known_series == selection.known_series
    assert tuple(item.model_dump_json() for item in restored.acquisition_provenance) == tuple(
        item.model_dump_json() for item in selection.acquisition_provenance
    )


@pytest.mark.parametrize("operation", ("status", "reuse", "refresh"))
def test_current_store_revision_still_refuses_retired_publication_service(operation, tmp_path, monkeypatch):
    # Author a current generation, then change only its publication identity.
    # Re-sign this synthetic carrier so the semantic gate, not byte integrity, refuses.
    cache = tmp_path / "cache"
    target = cache / "fr_hubeau/store"
    accumulate(StoreRoot(target), ProviderId("fr_hubeau"), StoreUpdate((), (), (), ()))
    path = target / "manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["publication_service"]
    path.write_text(json.dumps(manifest))
    _resign(target)
    before = _files(cache)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(cache))
    monkeypatch.setattr(validation, "_open_parquet", _no_values)

    class NoNetwork:
        def send(self, request):
            pytest.fail("retired publication identity reached source transport")

    monkeypatch.setattr(discovery, "HttpClient", NoNetwork)
    with pytest.raises(ObservationStoreRefusedError, match="publication.service") as caught:
        if operation == "status":
            rr.cache_status("fr_hubeau")
        else:
            selection = rr.find(
                provider="fr_hubeau", station="1011000101", quantity="discharge", frequency="daily", statistic="mean"
            )
            rr.fetch(selection, start="2025-01-03", end="2025-01-03", cache=operation, on_issue="ignore")
    assert caught.value.refusal.kind is validation.StoreRefusalKind.INCOMPATIBLE
    assert caught.value.refusal.defect == "publication_service:expected hubeau"
    assert _files(cache) == before
