"""Exact baseline exports must not restore retired configuration-derived facts."""

import hashlib
import json
import shutil
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.store.validation import ObservationStoreRefusedError

DATA = Path("tests/test_data")
OLD_STORE = DATA / "boundary_stores/fr_hubeau_retired_facts"
OLD_BUNDLE = DATA / "bundles/fr_hubeau_retired_facts_v1.bundle"
RECORDING = DATA / "fr_hubeau_1011000101_QmnJ_padded.recording.json"


def _selection():
    selection = rr.find(
        provider="fr_hubeau", station="1011000101", quantity="discharge", frequency="daily", statistic="mean"
    )
    assert selection.series
    assert all(facts.frequency.value == "daily" for series in selection.series for facts in series.facts)
    return rr.pick(selection, series_id=[series.series_id for series in selection.series])


def _copy_cache(retained_evidence_root, monkeypatch, tmp_path):
    path = tmp_path / "fr_hubeau/store"
    shutil.copytree(retained_evidence_root / OLD_STORE, path)
    (path / "attestation.json").unlink()
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    return path


def _snapshot(path):
    return {str(item.relative_to(path)): item.read_bytes() for item in path.rglob("*") if item.is_file()}


def test_retired_artifacts_are_exact_actual_baseline_outputs(retained_evidence_root):
    attestation = json.loads((retained_evidence_root / OLD_STORE / "attestation.json").read_text())
    assert attestation["producer_revision"] == "0954c479032dc33685342f6c97ecf6adb981499d"
    for name, digest in attestation["files"].items():
        assert hashlib.sha256((retained_evidence_root / DATA / name).read_bytes()).hexdigest() == digest
    manifest = json.loads((retained_evidence_root / OLD_STORE / "manifest.json").read_text())
    assert manifest["format_version"] == 6
    assert manifest["series"][0]["facts"][0]["frequency"]["value"] == "irregular"
    assert sum(manifest["partition_row_counts"].values()) == 282
    with ZipFile(retained_evidence_root / OLD_BUNDLE) as archive:
        exported = json.loads(archive.read("manifest.json"))
    assert exported["version"] == 1
    assert exported["series"][0]["facts"][0]["frequency"]["value"] == "irregular"


@pytest.mark.parametrize("mode", ["reuse", "refresh"])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_public_fetch_refuses_actual_old_facts_cache_without_deleting_it(
    retained_evidence_root, monkeypatch, tmp_path, mode, policy
):
    path = _copy_cache(retained_evidence_root, monkeypatch, tmp_path)
    before = _snapshot(path)

    requests = []

    class NoNetwork(ReplayTransport):
        def _resolve(self, request):
            requests.append(request)
            raise AssertionError("old format refusal must precede acquisition")

    monkeypatch.setattr(discovery, "HttpClient", lambda: NoNetwork(()))
    with pytest.raises(ObservationStoreRefusedError, match="unsupported format revision 6"):
        rr.fetch(_selection(), start="2025-01-03", end="2025-01-03", cache=mode, on_issue=policy)
    assert not requests
    assert _snapshot(path) == before


def test_old_bundle_refusal_preserves_original_bytes_and_precedes_scientific_decode(retained_evidence_root):
    original = (retained_evidence_root / OLD_BUNDLE).read_bytes()
    with pytest.raises(ValueError, match="Unsupported source-series bundle format version"):
        rr.from_bundle(original)
    assert (retained_evidence_root / OLD_BUNDLE).read_bytes() == original


def test_explicit_bypass_and_cleanup_refetch_produce_only_current_facts(retained_evidence_root, monkeypatch, tmp_path):
    path = _copy_cache(retained_evidence_root, monkeypatch, tmp_path)
    before = _snapshot(path)
    recording = read_recording(retained_evidence_root / RECORDING)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = _selection()
    bypassed = rr.fetch(selection, start="2025-01-03", end="2025-01-03", cache="bypass", on_issue="ignore")
    assert bypassed.data.height == 1
    assert all(facts.frequency.value == "daily" for series in bypassed.source_series for facts in series.facts)
    assert _snapshot(path) == before
    rr.clear_cache("fr_hubeau")
    refreshed = rr.fetch(selection, start="2025-01-03", end="2025-01-03", cache="refresh", on_issue="ignore")
    assert all(facts.frequency.value == "daily" for series in refreshed.source_series for facts in series.facts)
    assert json.loads((path / "manifest.json").read_text())["format_version"] == 8
    exported = rr.to_bundle(refreshed)
    with ZipFile(BytesIO(exported)) as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == 2
    restored = rr.from_bundle(exported)
    assert restored.source_series == refreshed.source_series
