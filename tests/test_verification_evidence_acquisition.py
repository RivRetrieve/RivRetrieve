"""Credential-free boundary tests use synthetic archives, not provider-response replacements."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import shlex
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from maintenance.evidence import acquisition
from maintenance.evidence.__main__ import main
from maintenance.evidence.archives import ArchivePaths, extract_archive
from maintenance.evidence.index import Asset, EvidenceError, EvidenceIndex, read_index
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

ROOT = Path(__file__).resolve().parents[1]


def _asset(raw: bytes, *, archive_format="tar.gz", size=4, count=1, identity=101):
    return {
        "asset_id": identity,
        "name": f"collection-{identity}.{archive_format}",
        "byte_size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "archive_format": archive_format,
        "extracted_byte_size": size,
        "member_count": count,
    }


def _index(assets):
    return {
        "schema_version": 1,
        "repository": "RivRetrieve/verification-evidence",
        "providers": [
            {
                "provider_id": provider,
                "materials": [
                    {
                        "kind": "test",
                        "purpose": "Synthetic archive safety case",
                        "location": "test",
                        "access": "public",
                        "integrity": "test",
                        "limitations": ["Not source evidence"],
                    }
                ],
                "verification": [
                    {
                        "command": "do not execute this text",
                        "purpose": "test",
                        "requires_collections": [],
                        "limitations": [],
                    }
                ],
                "gaps": [],
                "collections": ["test-collection"] if provider in ("fr_hubeau", "fr_hydroportail") else [],
            }
            for provider in BUILTIN_PROVIDER_IDS
        ],
        "collections": [
            {
                "collection_id": "test-collection",
                "release_id": 42,
                "release_tag": "test-v1",
                "verification_root": ".",
                "assets": assets,
                "purpose": "Synthetic safety case",
                "limitations": ["Not source evidence"],
            }
        ],
    }


def _tar(entries=(("body.txt", b"test", tarfile.REGTYPE),), *, mode="w:gz"):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode=mode) as archive:
        for name, content, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.size = len(content)
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = "outside"
            archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def _zip(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content, kind in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (kind | 0o600) << 16
            archive.writestr(info, content)
    return stream.getvalue()


def _extract(tmp_path, raw, metadata):
    archive = tmp_path / "archive"
    archive.write_bytes(raw)
    destination = tmp_path / "content"
    destination.mkdir()
    extract_archive(archive, Asset.model_validate(metadata), destination, ArchivePaths())
    return destination


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    """Exercise real subprocess argv and byte streaming without credentials or network."""
    binary = tmp_path / "bin"
    binary.mkdir()
    program = binary / "gh"
    program.write_text(
        f"#!{sys.executable}\n" + "import json, os, sys\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['FAKE_GH_ROOT'])\n"
        "with (root / 'calls').open('a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "assert 'GH_DEBUG' not in os.environ\n"
        "assert sys.argv[1:4] == ['api', '--hostname', 'github.com']\n"
        "endpoint = sys.argv[4]\n"
        "if (root / 'fail').exists():\n"
        "    sys.stderr.write('PRIVATE_RESPONSE_SENTINEL'); sys.exit(1)\n"
        "if '/releases/assets/' in endpoint:\n"
        "    sys.stdout.buffer.write((root / endpoint.rsplit('/', 1)[1]).read_bytes())\n"
        "elif '/assets?' in endpoint:\n"
        "    page = endpoint.rsplit('=', 1)[1]\n"
        "    sys.stdout.write((root / ('page-' + page)).read_text())\n"
        "else: sys.stdout.write((root / 'release').read_text())\n"
    )
    program.chmod(0o700)
    import os

    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_GH_ROOT", str(tmp_path))
    monkeypatch.setenv("GH_DEBUG", "api")
    monkeypatch.setenv("GH_TOKEN", "synthetic-not-a-credential")

    def configure(raw=None):
        raw = _tar() if raw is None else raw
        metadata = _asset(raw)
        (tmp_path / "101").write_bytes(raw)
        (tmp_path / "release").write_text(json.dumps({"id": 42, "tag_name": "test-v1", "draft": False}))
        (tmp_path / "page-1").write_text(
            json.dumps(
                [
                    {
                        "id": 101,
                        "name": metadata["name"],
                        "size": len(raw),
                        "state": "uploaded",
                        "digest": "sha256:" + metadata["sha256"],
                    }
                ]
            )
        )
        return _index([metadata])

    return configure


def _acquire(tmp_path, index):
    return acquisition.acquire_collection(
        EvidenceIndex.model_validate(index),
        "fr_hubeau",
        "test-collection",
        tmp_path / "outside",
        source_roots=(ROOT,),
    )


def test_committed_index_matches_all_registered_providers():
    index = read_index(ROOT / "maintenance/evidence/index.json")
    assert {item.provider_id for item in index.providers} == set(BUILTIN_PROVIDER_IDS)


def test_committed_full_checks_require_their_published_collections():
    """Private-body checks must not appear executable with public inputs alone."""
    index = read_index(ROOT / "maintenance/evidence/index.json")
    providers = {entry.provider_id: entry for entry in index.providers}
    full = {}
    for provider_id in ("ba_fhmzbih", "fr_hubeau", "fr_hydroportail", "th_thaiwater"):
        checks = providers[provider_id].verification
        full[provider_id] = [check for check in checks if "--evidence-root" in shlex.split(check.command)]
        assert full[provider_id]
        assert all(check.requires_collections for check in full[provider_id])

    # The mixed historical France verifier uses one shared acquisition, not two copies.
    assert full["fr_hubeau"][0].requires_collections == full["fr_hydroportail"][0].requires_collections
    thai_checks = providers["th_thaiwater"].verification
    regression = next(
        check
        for check in thai_checks
        if shlex.split(check.command)[3:]
        == ["tests/test_thaiwater_governing_evidence.py", "tests/test_thaiwater_source_outcomes.py", "-q"]
    )
    assert regression.requires_collections == full["th_thaiwater"][0].requires_collections
    assert thai_checks.index(full["th_thaiwater"][0]) < thai_checks.index(regression)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update(schema_version=True),
        lambda x: x.update(schema_version=2),
        lambda x: x.update(repository="unreviewed/repository"),
        lambda x: x.update(extra="PRIVATE_RESPONSE_SENTINEL"),
        lambda x: x["providers"].pop(),
        lambda x: x["providers"].append(copy.deepcopy(x["providers"][0])),
        lambda x: x["providers"][0].update(provider_id="unknown"),
        lambda x: x["providers"][0].update(collections=["missing"]),
        lambda x: x["providers"][0].update(collections=["test-collection", "test-collection"]),
        lambda x: x["providers"][0]["verification"][0].update(requires_collections=["test-collection"]),
        lambda x: x["collections"].append(copy.deepcopy(x["collections"][0])),
        lambda x: x["collections"][0].update(release_id=True),
        lambda x: x["collections"][0].update(release_tag="latest"),
        lambda x: x["collections"][0].update(collection_id="../escape"),
        lambda x: x["collections"][0]["assets"][0].update(asset_id="101"),
        lambda x: x["collections"][0]["assets"][0].update(byte_size=2**31),
        lambda x: x["collections"][0]["assets"][0].update(byte_size=True),
        lambda x: x["collections"][0]["assets"][0].update(sha256="invalid"),
        lambda x: x["collections"][0]["assets"][0].update(name="../archive.tar.gz"),
        lambda x: x["collections"][0]["assets"][0].update(archive_format="zip"),
        lambda x: x["collections"][0]["assets"].append(copy.deepcopy(x["collections"][0]["assets"][0])),
    ],
)
def test_index_rejects_invalid_identities_and_references(mutation):
    value = _index([_asset(_tar())])
    mutation(value)
    with pytest.raises(ValidationError):
        EvidenceIndex.model_validate(value)


def test_duplicate_json_keys_rejected_without_echoing_values(tmp_path, capsys):
    path = tmp_path / "index.json"
    path.write_text('{"schema_version":1,"schema_version":"PRIVATE_RESPONSE_SENTINEL"}')
    assert main(["validate", "--index", str(path)]) == 1
    output = capsys.readouterr()
    assert "PRIVATE_RESPONSE_SENTINEL" not in output.err
    assert "Invalid evidence index" in output.err


@pytest.mark.parametrize("kind", ["tar.gz", "tar.xz", "zip"])
def test_extract_regular_files_and_directories(tmp_path, kind):
    entries = [("bodies/", b"", tarfile.DIRTYPE), ("bodies/body.txt", b"test", tarfile.REGTYPE)]
    if kind == "zip":
        raw = _zip([("bodies/", b"", stat.S_IFDIR), ("bodies/body.txt", b"test", stat.S_IFREG)])
    else:
        raw = _tar(entries, mode="w:gz" if kind == "tar.gz" else "w:xz")
    result = _extract(tmp_path, raw, _asset(raw, archive_format=kind, count=2))
    assert (result / "bodies/body.txt").read_bytes() == b"test"
    assert stat.S_IMODE((result / "bodies/body.txt").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "C:/windows",
        "a\\b",
        "a/../b",
        "a//b",
        "./body",
        "a/./b",
        "NUL.txt",
        "a.",
        "a ",
        "a:b",
        "a\nb",
    ],
)
@pytest.mark.parametrize("kind", ["tar.gz", "zip"])
def test_reject_unsafe_archive_paths(tmp_path, name, kind):
    raw = _tar([(name, b"test", tarfile.REGTYPE)]) if kind == "tar.gz" else _zip([(name, b"test", stat.S_IFREG)])
    with pytest.raises(EvidenceError, match="unsafe path"):
        _extract(tmp_path, raw, _asset(raw, archive_format=kind))
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_tar_rejects_links_and_special_files(tmp_path, kind):
    raw = _tar([("link", b"", kind)])
    with pytest.raises(EvidenceError, match="link or special"):
        _extract(tmp_path, raw, _asset(raw, size=0))


def test_zip_rejects_symlinks(tmp_path):
    raw = _zip([("link", b"test", stat.S_IFLNK)])
    with pytest.raises(EvidenceError, match="link, special"):
        _extract(tmp_path, raw, _asset(raw, archive_format="zip"))


@pytest.mark.parametrize("names", [("same", "same"), ("Body", "body"), ("A/one", "a/two"), ("é", "é")])
def test_duplicate_and_portable_aliases_fail(tmp_path, names):
    raw = _tar([(name, b"test", tarfile.REGTYPE) for name in names])
    with pytest.raises(EvidenceError, match="duplicate|aliased"):
        _extract(tmp_path, raw, _asset(raw, count=2, size=8))


@pytest.mark.parametrize(("size", "count"), [(3, 1), (5, 1), (4, 2)])
def test_exact_extraction_totals_are_required(tmp_path, size, count):
    raw = _tar()
    with pytest.raises(EvidenceError, match="limits|totals"):
        _extract(tmp_path, raw, _asset(raw, size=size, count=count))


def test_authenticated_exact_asset_download_and_no_overwrite(tmp_path, fake_gh):
    value = fake_gh()
    result = _acquire(tmp_path, value)
    assert (result / "body.txt").read_bytes() == b"test"
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    assert len(calls) == 3
    assert calls[-1][3:] == [
        "repos/RivRetrieve/verification-evidence/releases/assets/101",
        "-H",
        "Accept: application/octet-stream",
    ]
    with pytest.raises(EvidenceError, match="already exists"):
        _acquire(tmp_path, value)
    assert (result / "body.txt").read_bytes() == b"test"
    assert not list((tmp_path / "outside").glob(".evidence-*"))


@pytest.mark.parametrize("replacement", [b"bad", b"bad" * 1000])
def test_integrity_failure_precedes_archive_open(tmp_path, fake_gh, monkeypatch, replacement):
    value = fake_gh()
    (tmp_path / "101").write_bytes(replacement)
    monkeypatch.setattr(acquisition, "extract_archive", lambda *a: pytest.fail("opened unverified bytes"))
    with pytest.raises(EvidenceError, match="size|SHA-256"):
        _acquire(tmp_path, value)
    assert list((tmp_path / "outside").iterdir()) == []


def test_all_assets_verified_before_any_extraction(tmp_path, fake_gh, monkeypatch):
    value = fake_gh()
    second = dict(value["collections"][0]["assets"][0], asset_id=102, name="second.tar.gz")
    value["collections"][0]["assets"].append(second)
    records = json.loads((tmp_path / "page-1").read_text())
    records.append(dict(records[0], id=102, name="second.tar.gz"))
    (tmp_path / "page-1").write_text(json.dumps(records))
    (tmp_path / "102").write_bytes(b"not the reviewed bytes")
    monkeypatch.setattr(acquisition, "extract_archive", lambda *a: pytest.fail("opened before all assets verified"))
    with pytest.raises(EvidenceError):
        _acquire(tmp_path, value)
    assert list((tmp_path / "outside").iterdir()) == []


@pytest.mark.parametrize(
    ("file", "field", "wrong"),
    [
        ("release", "id", 43),
        ("release", "tag_name", "test-v2"),
        ("release", "draft", True),
        ("page-1", "id", 102),
        ("page-1", "name", "replacement.tar.gz"),
        ("page-1", "size", 1),
        ("page-1", "digest", "sha256:" + "0" * 64),
        ("page-1", "state", "new"),
    ],
)
def test_release_and_asset_identity_must_match(tmp_path, fake_gh, file, field, wrong):
    value = fake_gh()
    record = json.loads((tmp_path / file).read_text())
    (record[0] if isinstance(record, list) else record)[field] = wrong
    (tmp_path / file).write_text(json.dumps(record))
    with pytest.raises(EvidenceError):
        _acquire(tmp_path, value)
    assert "/releases/assets/" not in (tmp_path / "calls").read_text()


def test_assets_paginated_without_downloading_other_provider_assets(tmp_path, fake_gh):
    value = fake_gh()
    selected = json.loads((tmp_path / "page-1").read_text())
    (tmp_path / "page-1").write_text(json.dumps([{"id": i + 1000} for i in range(100)]))
    (tmp_path / "page-2").write_text(json.dumps(selected))
    _acquire(tmp_path, value)
    calls = (tmp_path / "calls").read_text()
    assert "page=2" in calls
    assert calls.count("/releases/assets/") == 1


def test_unselected_provider_cannot_download(tmp_path, fake_gh):
    value = fake_gh()
    with pytest.raises(EvidenceError, match="does not list"):
        acquisition.acquire_collection(
            EvidenceIndex.model_validate(value),
            "ba_fhmzbih",
            "test-collection",
            tmp_path / "outside",
            source_roots=(ROOT,),
        )
    assert not (tmp_path / "calls").exists()


def test_source_checkout_and_symlink_alias_are_rejected(tmp_path, fake_gh):
    value = EvidenceIndex.model_validate(fake_gh())
    alias = tmp_path / "alias"
    alias.symlink_to(ROOT, target_is_directory=True)
    for destination in (ROOT / "evidence", alias / "evidence"):
        with pytest.raises(EvidenceError, match="outside all source"):
            acquisition.acquire_collection(value, "fr_hubeau", "test-collection", destination, source_roots=(ROOT,))
    assert not (tmp_path / "calls").exists()


def test_other_git_checkout_is_rejected(tmp_path, fake_gh):
    value = EvidenceIndex.model_validate(fake_gh())
    other = tmp_path / "other-checkout"
    other.mkdir()
    (other / ".git").write_text("gitdir: some-worktree")
    with pytest.raises(EvidenceError, match="outside all source"):
        acquisition.acquire_collection(value, "fr_hubeau", "test-collection", other / "data", source_roots=(ROOT,))


def test_cli_failure_suppresses_private_gh_output(tmp_path, fake_gh, capsys):
    value = fake_gh()
    (tmp_path / "fail").touch()
    index = tmp_path / "index.json"
    index.write_text(json.dumps(value))
    code = main(
        [
            "fetch",
            "--index",
            str(index),
            "--provider",
            "fr_hubeau",
            "--collection",
            "test-collection",
            "--destination",
            str(tmp_path / "outside"),
        ]
    )
    assert code == 1
    output = capsys.readouterr()
    assert "PRIVATE_RESPONSE_SENTINEL" not in output.err + output.out
    assert "synthetic-not-a-credential" not in output.err + output.out
    assert "gh authentication" in output.err


def test_failed_archive_never_publishes_partial_evidence(tmp_path, fake_gh):
    raw = _tar([("../PRIVATE_RESPONSE_SENTINEL", b"test", tarfile.REGTYPE)])
    value = fake_gh(raw)
    with pytest.raises(EvidenceError, match="unsafe path") as caught:
        _acquire(tmp_path, value)
    assert "PRIVATE_RESPONSE_SENTINEL" not in str(caught.value)
    assert list((tmp_path / "outside").iterdir()) == []


@pytest.mark.parametrize("root", ["../escape", "/absolute", "a/../b", "a//b", "a\\b", ""])
def test_index_verification_root_must_be_relative(root):
    value = _index([_asset(_tar())])
    value["collections"][0]["verification_root"] = root
    with pytest.raises(ValidationError):
        EvidenceIndex.model_validate(value)


def test_same_size_digest_failure_never_extracts(tmp_path, fake_gh, monkeypatch):
    value = fake_gh()
    original = (tmp_path / "101").read_bytes()
    (tmp_path / "101").write_bytes(bytes([original[0] ^ 1]) + original[1:])
    monkeypatch.setattr(acquisition, "extract_archive", lambda *a: pytest.fail("opened wrong digest"))
    with pytest.raises(EvidenceError, match="SHA-256"):
        _acquire(tmp_path, value)
    assert list((tmp_path / "outside").iterdir()) == []


def test_cross_asset_duplicate_paths_rejected(tmp_path, fake_gh):
    value = fake_gh()
    value["collections"][0]["assets"].append(
        dict(value["collections"][0]["assets"][0], asset_id=102, name="second.tar.gz")
    )
    records = json.loads((tmp_path / "page-1").read_text())
    records.append(dict(records[0], id=102, name="second.tar.gz"))
    (tmp_path / "page-1").write_text(json.dumps(records))
    (tmp_path / "102").write_bytes((tmp_path / "101").read_bytes())
    with pytest.raises(EvidenceError, match="duplicate"):
        _acquire(tmp_path, value)
    assert list((tmp_path / "outside").iterdir()) == []


def test_missing_verification_root_rejects_collection(tmp_path, fake_gh):
    value = fake_gh()
    value["collections"][0]["verification_root"] = "acquisition"
    with pytest.raises(EvidenceError, match="verification root"):
        _acquire(tmp_path, value)
    assert list((tmp_path / "outside").iterdir()) == []


def test_preexisting_dangling_symlink_never_changed(tmp_path, fake_gh):
    value = fake_gh()
    target = tmp_path / "outside" / "test-collection"
    target.parent.mkdir()
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(EvidenceError, match="already exists"):
        _acquire(tmp_path, value)
    assert target.is_symlink()
    assert not (tmp_path / "calls").exists()


def test_cli_success_reports_identity_and_root_without_response_content(tmp_path, fake_gh, capsys):
    raw = _tar([("acquisition/body.txt", b"test", tarfile.REGTYPE)])
    value = fake_gh(raw)
    value["collections"][0]["verification_root"] = "acquisition"
    index = tmp_path / "index.json"
    index.write_text(json.dumps(value))
    assert (
        main(
            [
                "fetch",
                "--index",
                str(index),
                "--provider",
                "fr_hydroportail",
                "--collection",
                "test-collection",
                "--destination",
                str(tmp_path / "outside"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "collection_id": "test-collection",
        "release_id": 42,
        "verification_root": "acquisition",
        "asset_ids": [101],
        "sha256": [hashlib.sha256(raw).hexdigest()],
    }
    assert (tmp_path / "outside/test-collection/acquisition/body.txt").read_bytes() == b"test"


def test_zero_credentials_offline_validation(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(acquisition, "_metadata", lambda *a: pytest.fail("offline validation accessed GitHub"))
    assert main(["validate", "--index", str(ROOT / "maintenance/evidence/index.json")]) == 0
    assert json.loads(capsys.readouterr().out)["providers"] == 14


@pytest.mark.parametrize("metadata_size", [1024, 65537])
def test_tar_extension_metadata_is_bounded_before_allocation(tmp_path, metadata_size):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        info = tarfile.TarInfo("body.txt")
        info.size = 4
        info.pax_headers = {"comment": "x" * metadata_size}
        archive.addfile(info, io.BytesIO(b"test"))
    raw = stream.getvalue()
    if metadata_size < 65536:
        assert (_extract(tmp_path, raw, _asset(raw)) / "body.txt").read_bytes() == b"test"
    else:
        with pytest.raises(EvidenceError, match="metadata exceeds"):
            _extract(tmp_path, raw, _asset(raw))


def test_zip_directory_count_checked_before_library_allocation(tmp_path, monkeypatch):
    raw = _zip([("one", b"test", stat.S_IFREG), ("two", b"test", stat.S_IFREG)])
    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: pytest.fail("parsed unbounded directory"))
    with pytest.raises(EvidenceError, match="directory exceeds"):
        _extract(tmp_path, raw, _asset(raw, archive_format="zip"))


@pytest.mark.parametrize("kind", [tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK])
def test_gnu_extension_metadata_is_rejected_before_read(tmp_path, kind):
    raw = _tar([("extension", b"x" * 65537, kind), ("body.txt", b"test", tarfile.REGTYPE)])
    with pytest.raises(EvidenceError, match="metadata exceeds"):
        _extract(tmp_path, raw, _asset(raw))


@pytest.mark.parametrize("change", ["oversized", "split", "zip64", "inconsistent"])
def test_zip_directory_preflight_rejects_unsafe_end_metadata(tmp_path, monkeypatch, change):
    import struct

    raw = _zip([("body.txt", b"test", stat.S_IFREG)])
    start = raw.rfind(b"PK\x05\x06")
    fields = list(struct.unpack("<4s4H2LH", raw[start : start + 22]))
    if change == "oversized":
        fields[5] = 65537
    elif change == "split":
        fields[1] = 1
    elif change == "inconsistent":
        fields[6] = len(raw)
    if change == "zip64":
        raw = raw[:start] + b"PK\x06\x07" + bytes(16) + raw[start:]
    else:
        raw = raw[:start] + struct.pack("<4s4H2LH", *fields) + raw[start + 22 :]
    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: pytest.fail("parsed unsafe directory"))
    with pytest.raises(EvidenceError, match="directory exceeds"):
        _extract(tmp_path, raw, _asset(raw, archive_format="zip"))
