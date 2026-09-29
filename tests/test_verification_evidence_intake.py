"""Synthetic archive mechanics; these tests do not certify provider evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from maintenance.evidence import publication
from maintenance.evidence.__main__ import main
from maintenance.evidence.acquisition import acquire_collection
from maintenance.evidence.index import EvidenceError, EvidenceIndex
from maintenance.evidence.intake import check_prepared, prepare_collection
from maintenance.evidence.manifest import read_manifest
from tests.test_verification_evidence_acquisition import _index

ROOT = Path(__file__).resolve().parents[1]


def _manifest():
    return {
        "schema_version": 1,
        "collection_id": "test-collection",
        "provider_ids": ["fr_hubeau", "fr_hydroportail"],
        "input_roots": {"verification": "."},
        "acquisitions": [
            {
                "acquisition_id": identity,
                "source_acquisition_id": None,
                "provider_ids": ["fr_hubeau"],
                "source_context": None,
                "request_context": None,
                "acquired_at": None,
                "receipt_refs": [],
                "limitations": ["Original event facts unavailable"],
            }
            for identity in ("event-a", "event-b")
        ],
        "artifacts": [
            {
                "artifact_id": identity,
                "path": identity + ".txt",
                "role": "response_recording",
                "byte_size": 4,
                "sha256": hashlib.sha256(b"test").hexdigest(),
                "acquisition_ids": [event],
                "derived_from": [],
                "receipt_refs": [],
                "derivation": None,
                "description": "Synthetic file",
                "access_restrictions": "Synthetic only",
                "limitations": [],
            }
            for identity, event in (("body-a", "event-a"), ("body-b", "event-b"))
        ],
        "limitations": ["Synthetic mechanics only"],
    }


def _inputs(tmp_path, manifest=None):
    value = _manifest() if manifest is None else manifest
    source = tmp_path / "source"
    source.mkdir()
    for artifact in value["artifacts"]:
        path = source / artifact["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    return source, path


def _prepare(tmp_path):
    source, manifest = _inputs(tmp_path)
    package = prepare_collection(manifest, source, tmp_path / "prepared", source_roots=(ROOT,), max_asset_bytes=4)
    return source, manifest, package


def test_intake_preserves_equal_bytes_and_independent_unknown_acquisitions(tmp_path):
    source, manifest, package = _prepare(tmp_path)
    staging = tmp_path / "extracted"
    staging.mkdir()
    record = check_prepared(package, staging)
    retained = read_manifest(staging / record.manifest.path)
    assert len(retained.acquisitions) == len(retained.artifacts) == 2
    assert {a.acquisition_id for a in retained.acquisitions} == {"event-a", "event-b"}
    assert all(a.source_acquisition_id is None and a.acquired_at is None for a in retained.acquisitions)
    assert len({a.sha256 for a in retained.artifacts}) == 1
    assert len(record.assets) == 3  # manifest plus two deliberately split files
    assert {path.name: path.read_bytes() for path in source.iterdir()} == {
        "body-a.txt": b"test",
        "body-b.txt": b"test",
    }
    with pytest.raises(EvidenceError, match="already exists"):
        prepare_collection(manifest, source, tmp_path / "prepared", source_roots=(ROOT,))


@pytest.mark.parametrize(
    "change", ["missing", "extra", "changed", "symlink", "alias", "unsafe", "reference", "receipt", "cycle", "boolean"]
)
def test_intake_rejects_inventory_and_private_reference_failures_safely(tmp_path, change, capsys):
    source, manifest = _inputs(tmp_path)
    value = json.loads(manifest.read_text())
    if change == "missing":
        (source / "body-a.txt").unlink()
    elif change == "extra":
        (source / "PRIVATE_SENTINEL").write_bytes(b"test")
    elif change == "changed":
        (source / "body-a.txt").write_bytes(b"FAIL")
    elif change == "symlink":
        (source / "body-a.txt").unlink()
        (source / "body-a.txt").symlink_to(source / "body-b.txt")
    elif change == "alias":
        value["artifacts"][1]["path"] = "BODY-A.txt"
    elif change == "unsafe":
        value["artifacts"][0]["path"] = "../PRIVATE_SENTINEL"
    elif change == "reference":
        value["artifacts"][0]["acquisition_ids"] = ["PRIVATE_SENTINEL"]
    elif change == "receipt":
        value["artifacts"][0]["receipt_refs"] = ["body-b"]
    elif change == "cycle":
        value["artifacts"][0]["derived_from"] = ["body-b"]
        value["artifacts"][1]["derived_from"] = ["body-a"]
    else:
        value["schema_version"] = True
    manifest.write_text(json.dumps(value))
    assert (
        main(
            ["intake", "--manifest", str(manifest), "--source", str(source), "--destination", str(tmp_path / "output")]
        )
        == 1
    )
    output = capsys.readouterr()
    assert "PRIVATE_SENTINEL" not in output.out + output.err
    assert str(tmp_path) not in output.out + output.err
    assert not (tmp_path / "output/test-collection").exists()


def test_private_manifest_errors_suppress_validation_context(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"secret": "PRIVATE_SENTINEL"}')
    with pytest.raises(EvidenceError) as caught:
        read_manifest(path)
    import traceback

    assert "PRIVATE_SENTINEL" not in "".join(traceback.format_exception(caught.value))


def test_derived_artifacts_require_explicit_lineage_limits(tmp_path):
    value = _manifest()
    value["artifacts"][0].update(role="derived_input", acquisition_ids=[], derivation="Original input is unavailable")
    source, manifest = _inputs(tmp_path, value)
    prepare_collection(manifest, source, tmp_path / "out", source_roots=(ROOT,))
    value["artifacts"][0]["derivation"] = None
    manifest.write_text(json.dumps(value))
    with pytest.raises(EvidenceError):
        read_manifest(manifest)


def test_prepared_corruption_is_rejected_before_extraction(tmp_path, monkeypatch):
    _, _, package = _prepare(tmp_path)
    asset = next(package.glob("members-*.tar.gz"))
    asset.write_bytes(b"PRIVATE_SENTINEL")
    monkeypatch.setattr(
        "maintenance.evidence.intake.extract_archive", lambda *a: pytest.fail("unverified archive opened")
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(EvidenceError):
        check_prepared(package, staging)
    assert list(staging.iterdir()) == []


class FakePublication:
    def __init__(self, monkeypatch):
        self.private = True
        self.release = None
        self.assets = []
        self.bodies = {}
        self.fail_upload = False
        self.calls = []
        monkeypatch.setattr(publication, "_metadata", self.metadata)
        monkeypatch.setattr("maintenance.evidence.acquisition._metadata", self.metadata)
        monkeypatch.setattr(publication, "_upload", self.upload)
        monkeypatch.setattr(publication, "download_asset", self.download)
        monkeypatch.setattr("maintenance.evidence.acquisition.download_asset", self.download)

    def metadata(self, endpoint, *, method="GET", payload=None):
        self.calls.append((endpoint, method))
        if endpoint == "repos/RivRetrieve/verification-evidence":
            return {"full_name": "RivRetrieve/verification-evidence", "private": self.private}
        if "/assets?" in endpoint:
            return self.assets
        if "releases?" in endpoint:
            return [] if self.release is None else [self.release]
        if method == "POST":
            self.release = {"id": 42, **payload, "immutable": False}
        elif method == "PATCH":
            self.release.update(payload)
        return copy.deepcopy(self.release)

    def upload(self, release_id, source, name):
        if self.fail_upload:
            raise EvidenceError("Asset publication failed; inspect the private draft.")
        raw = source.read_bytes()
        record = {
            "id": 100 + len(self.assets),
            "name": name,
            "size": len(raw),
            "state": "uploaded",
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
        self.assets.append(record)
        self.bodies[record["id"]] = raw
        return record

    def download(self, repository, asset, destination):
        raw = self.bodies[asset.asset_id]
        assert len(raw) == asset.byte_size and hashlib.sha256(raw).hexdigest() == asset.sha256
        destination.write_bytes(raw)


def _publish(tmp_path, package):
    return publication.publish_collection(
        package,
        "test-v1",
        tmp_path / "publication",
        purpose="Synthetic test",
        limitations=["Not provider evidence"],
        source_roots=(ROOT,),
    )


def test_publication_captures_exact_pins_and_shared_selected_inputs(tmp_path, monkeypatch):
    _, _, package = _prepare(tmp_path)
    remote = FakePublication(monkeypatch)
    result = _publish(tmp_path, package)
    assert result.acceptance == "not_evaluated" and result.immutable is False
    assert remote.release["draft"] is False
    assert (tmp_path / "publication/publication.json").is_file()
    index = _index([])
    index["collections"] = [result.collection.model_dump(mode="json")]
    inputs = acquire_collection(
        EvidenceIndex.model_validate(index),
        "fr_hydroportail",
        "test-collection",
        tmp_path / "download",
        source_roots=(ROOT,),
    )
    assert inputs.input_roots["verification"] == tmp_path / "download/test-collection"
    assert (inputs.input_roots["verification"] / "body-a.txt").read_bytes() == b"test"
    with pytest.raises(EvidenceError, match="already exists"):
        _publish(tmp_path, package)


def test_publication_refuses_public_repository_without_remote_write(tmp_path, monkeypatch):
    _, _, package = _prepare(tmp_path)
    remote = FakePublication(monkeypatch)
    remote.private = False
    with pytest.raises(EvidenceError, match="private evidence repository"):
        _publish(tmp_path, package)
    assert all(method == "GET" for _, method in remote.calls)
    assert remote.release is None


def test_partial_publication_remains_draft_with_recorded_identity(tmp_path, monkeypatch):
    _, _, package = _prepare(tmp_path)
    remote = FakePublication(monkeypatch)
    remote.fail_upload = True
    with pytest.raises(EvidenceError):
        _publish(tmp_path, package)
    assert remote.release["draft"] is True
    assert json.loads((tmp_path / "publication/release.json").read_text())["release_id"] == 42
    assert not (tmp_path / "publication/publication.json").exists()


def test_existing_release_is_not_replaced(tmp_path, monkeypatch):
    _, _, package = _prepare(tmp_path)
    remote = FakePublication(monkeypatch)
    remote.release = {"id": 41, "tag_name": "test-v1", "name": "previous", "draft": True}
    with pytest.raises(EvidenceError, match="already exists"):
        _publish(tmp_path, package)
    assert all(method == "GET" for _, method in remote.calls)


def test_selected_provider_binding_must_match_private_manifest(tmp_path, monkeypatch):
    _, _, package = _prepare(tmp_path)
    FakePublication(monkeypatch)
    result = _publish(tmp_path, package)
    index = _index([])
    index["collections"] = [result.collection.model_dump(mode="json")]
    next(p for p in index["providers"] if p["provider_id"] == "fr_hydroportail")["collections"] = []
    with pytest.raises(EvidenceError, match="providers differ"):
        acquire_collection(
            EvidenceIndex.model_validate(index),
            "fr_hubeau",
            "test-collection",
            tmp_path / "download",
            source_roots=(ROOT,),
        )
    assert not (tmp_path / "download/test-collection").exists()


def test_circular_receipt_lineage_is_rejected(tmp_path):
    value = _manifest()
    for artifact in value["artifacts"]:
        artifact["role"] = "acquisition_receipt"
    value["artifacts"][0]["receipt_refs"] = ["body-b"]
    value["artifacts"][1]["receipt_refs"] = ["body-a"]
    _, manifest = _inputs(tmp_path, value)
    with pytest.raises(EvidenceError):
        read_manifest(manifest)


def test_acquisition_receipt_must_resolve_to_receipt_role(tmp_path):
    value = _manifest()
    value["acquisitions"][0]["receipt_refs"] = ["body-a"]
    _, manifest = _inputs(tmp_path, value)
    with pytest.raises(EvidenceError):
        read_manifest(manifest)


def test_publication_upload_uses_fixed_private_endpoint_and_suppresses_errors(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    source = tmp_path / "PRIVATE_SENTINEL"
    source.write_bytes(b"test")
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(stdout=b'{"id":101}')

    monkeypatch.setattr(publication.subprocess, "run", run)
    assert publication._upload(42, source, "members.tar.gz") == {"id": 101}
    command, options = commands[0]
    assert command[:4] == ["gh", "api", "--hostname", "github.com"]
    assert (
        command[4]
        == "https://uploads.github.com/repos/RivRetrieve/verification-evidence/releases/42/assets?name=members.tar.gz"
    )
    assert command[-2:] == ["--input", str(source)]
    assert options["capture_output"] and "GH_DEBUG" not in options["env"]

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "PRIVATE_SENTINEL", stderr=b"PRIVATE_SENTINEL")

    monkeypatch.setattr(publication.subprocess, "run", fail)
    with pytest.raises(EvidenceError) as caught:
        publication._upload(42, source, "members.tar.gz")
    import traceback

    assert "PRIVATE_SENTINEL" not in "".join(traceback.format_exception(caught.value))


def test_publication_integrity_failure_never_publishes(tmp_path, monkeypatch):
    _, _, package = _prepare(tmp_path)
    remote = FakePublication(monkeypatch)

    def corrupt_download(*args):
        raise EvidenceError("Downloaded bytes differ from their pin.")

    monkeypatch.setattr(publication, "download_asset", corrupt_download)
    with pytest.raises(EvidenceError):
        _publish(tmp_path, package)
    assert remote.release["draft"] is True
    assert not any(method == "PATCH" for _, method in remote.calls)


def test_visibility_rechecked_before_upload_and_publication(tmp_path, monkeypatch):
    _, _, package = _prepare(tmp_path)
    remote = FakePublication(monkeypatch)
    upload = remote.upload

    def change_visibility(*args):
        result = upload(*args)
        remote.private = False
        return result

    monkeypatch.setattr(publication, "_upload", change_visibility)
    with pytest.raises(EvidenceError, match="private evidence repository"):
        _publish(tmp_path, package)
    assert remote.release["draft"] is True
    assert len(remote.assets) == 1


def test_manifest_member_fingerprint_and_identity_are_required(tmp_path):
    from maintenance.evidence.index import Collection
    from maintenance.evidence.manifest import verify_collection

    _, _, package = _prepare(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    record = check_prepared(package, staging)
    selected = Collection(
        collection_id=record.collection_id,
        release_id=42,
        release_tag="test-v1",
        input_roots=record.input_roots,
        manifest=record.manifest,
        assets=[dict(asset.model_dump(), asset_id=100 + n) for n, asset in enumerate(record.assets)],
        purpose="Synthetic",
        limitations=[],
    )
    assert verify_collection(staging, selected) is not None
    wrong_identity = selected.model_copy(update={"collection_id": "different"})
    with pytest.raises(EvidenceError, match="identity"):
        verify_collection(staging, wrong_identity)
    (staging / "body-a.txt").write_bytes(b"FAIL")
    with pytest.raises(EvidenceError, match="fingerprint"):
        verify_collection(staging, selected)
    (staging / record.manifest.path).write_bytes(b"PRIVATE_SENTINEL")
    with pytest.raises(EvidenceError, match="fingerprint"):
        verify_collection(staging, selected)


def test_archive_api_errors_do_not_expose_private_exception_chains(tmp_path, monkeypatch):
    import traceback

    from maintenance.evidence import archives
    from maintenance.evidence.index import Asset
    from tests.test_verification_evidence_acquisition import _asset, _tar

    def private_error(*args, **kwargs):
        raise OSError("PRIVATE_SENTINEL")

    monkeypatch.setattr(archives.gzip, "open", private_error)
    raw = _tar()
    with pytest.raises(EvidenceError) as caught:
        archives.extract_archive(
            tmp_path / "input", Asset.model_validate(_asset(raw)), tmp_path, archives.ArchivePaths()
        )
    assert "PRIVATE_SENTINEL" not in "".join(traceback.format_exception(caught.value))
