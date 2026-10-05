"""Local seals bind published bytes without reading observations during inspection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store import StoreRoot, compile_store, integrity, validate_store
from rivretrieve._internal.store.validation import ObservationStoreRefusedError
from tests.store.certification_support import artifact_and_request, rows


def _compiled(tmp_path: Path):
    _, request = artifact_and_request(tmp_path)
    compile_store(request, rows())
    return request.destination, request.provider_id


def _resign(root: Path) -> None:
    """Update unrelated byte controls so a negative case reaches its semantic rule."""
    raw = json.loads((root / "integrity.json").read_text())
    for name, record in raw["files"].items():
        path = root / name
        item = path.stat()
        record.update(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            device=item.st_dev,
            inode=item.st_ino,
            size=item.st_size,
            mtime_ns=item.st_mtime_ns,
            ctime_ns=item.st_ctime_ns,
        )
    contents = {name: {"sha256": item["sha256"], "size": item["size"]} for name, item in raw["files"].items()}
    raw["generation_id"] = hashlib.sha256(
        json.dumps(
            {"version": 1, "provider_id": raw["provider_id"], "files": contents},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    del raw["seal_sha256"]
    raw["seal_sha256"] = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    (root / "integrity.json").write_text(json.dumps(raw))


def test_inspection_opens_no_observation_bytes_and_audit_counts(tmp_path, monkeypatch):
    root, provider = _compiled(tmp_path)
    expected = integrity.audit_store(root, provider)
    original = integrity._digest

    def metadata_only(path):
        assert path.name == "manifest.json"
        return original(path)

    monkeypatch.setattr(integrity, "_digest", metadata_only)
    monkeypatch.setattr(
        "rivretrieve._internal.store.validation._open_parquet",
        lambda path: pytest.fail("inspection decoded observations"),
    )
    sealed = integrity.inspect_integrity(root, provider)
    assert expected.generation_id == sealed.generation_id
    assert expected.partitions_checked == 1
    assert expected.rows_checked == 1
    assert expected.bytes_checked == sum(item.size for item in sealed.files.values())


@pytest.mark.parametrize(
    "defect", ["metadata", "numeric", "replacement", "extra", "symlink", "directory_symlink", "seal"]
)
def test_closed_generation_refuses_mutation(tmp_path, defect):
    root, provider = _compiled(tmp_path)
    part = next(root.rglob("*.parquet"))
    if defect == "metadata":
        (root / "manifest.json").write_bytes((root / "manifest.json").read_bytes() + b" ")
    elif defect == "numeric":
        pl.read_parquet(part).with_columns(pl.lit(99.0).alias("value")).write_parquet(part)
        # The old semantic validator accepts this validly encoded numeric change.
        validate_store(root, provider)
    elif defect == "replacement":
        content = part.read_bytes()
        part.unlink()
        part.write_bytes(content)
    elif defect == "extra":
        (root / "unexpected.txt").write_text("unlisted")
    elif defect == "symlink":
        target = tmp_path / "outside.parquet"
        part.rename(target)
        part.symlink_to(target)
    elif defect == "directory_symlink":
        directory = part.parent
        target = tmp_path / "outside"
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
    else:
        seal = root / "integrity.json"
        raw = json.loads(seal.read_text())
        raw["files"]["manifest.json"]["sha256"] = "0" * 64
        seal.write_text(json.dumps(raw))
    with pytest.raises(ObservationStoreRefusedError, match="integrity"):
        integrity.inspect_integrity(root, provider)


def test_restored_mtime_corruption_cannot_be_inherited_or_repaired(tmp_path):
    root, provider = _compiled(tmp_path)
    sealed = integrity.inspect_integrity(root, provider)
    identifier, part = next(iter(sealed.store.partition_files.items()))
    before = part.stat()
    data = bytearray(part.read_bytes())
    data[len(data) // 2] ^= 1
    part.write_bytes(data)
    os.utime(part, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ObservationStoreRefusedError, match="digest"):
        integrity.link_partition(sealed, identifier, tmp_path / "candidate" / part.name)
    with pytest.raises(ObservationStoreRefusedError, match="digest"):
        integrity.audit_store(root, provider)


def test_selected_verification_rechecks_generation_and_hashes(tmp_path):
    root, provider = _compiled(tmp_path)
    sealed = integrity.inspect_integrity(root, provider)
    integrity.verify_files(sealed, sealed.store.partition_files)
    path = next(root.rglob("*.parquet"))
    pl.read_parquet(path).with_columns(pl.lit(42.0).alias("value")).write_parquet(path)
    _resign(root)
    with pytest.raises(ObservationStoreRefusedError, match="generation_changed"):
        integrity.verify_files(sealed, sealed.store.partition_files)


def test_owned_link_unlink_transitions_keep_generation_and_digest(tmp_path, monkeypatch):
    root, provider = _compiled(tmp_path)
    sealed = integrity.inspect_integrity(root, provider)
    identifier, part = next(iter(sealed.store.partition_files.items()))
    link = tmp_path / "linked" / part.name
    monkeypatch.setattr(integrity, "_digest", lambda path: pytest.fail("owned link read bytes"))
    reused = integrity.link_partition(sealed, identifier, link)
    assert reused.identity.sha256 == next(
        item.sha256 for name, item in sealed.files.items() if name.endswith(".parquet")
    )
    updated = integrity.refresh_witnesses(sealed)
    link.unlink()
    updated = integrity.refresh_witnesses(updated)
    assert updated.generation_id == sealed.generation_id
    assert updated.files[part.relative_to(root).as_posix()].sha256 == reused.identity.sha256


def test_interrupted_link_transition_is_repaired_against_original_digest(tmp_path):
    root, provider = _compiled(tmp_path)
    sealed = integrity.inspect_integrity(root, provider)
    identifier, part = next(iter(sealed.store.partition_files.items()))
    integrity.link_partition(sealed, identifier, tmp_path / "linked" / part.name)
    # Cheap inspection keeps the original ctime witness but does not read bytes.
    inspected = integrity.inspect_integrity(root, provider)
    assert inspected.files == sealed.files
    audited = integrity.audit_store(root, provider)
    repaired = integrity.refresh_witnesses(inspected)
    assert repaired.generation_id == audited.generation_id == sealed.generation_id
    assert integrity.inspect_integrity(root, provider).generation_id == sealed.generation_id


def test_semantic_link_refusal_after_unrelated_digest_controls_updated(tmp_path):
    root, provider = _compiled(tmp_path)
    path = next(root.rglob("*.parquet"))
    pl.read_parquet(path).with_columns(pl.lit("missing-fact").alias("facts_id")).write_parquet(path)
    _resign(root)
    # Metadata alone cannot inspect observation fact links.
    integrity.inspect_integrity(root, provider)
    with pytest.raises(ObservationStoreRefusedError, match="partition.facts"):
        integrity.audit_store(root, provider)


def test_unsealed_semantic_fixture_is_not_a_published_generation(tmp_path):
    fixture = Path("tests/test_data/source_series_store_conformance/accumulated/valid_empty")
    root = StoreRoot(tmp_path / "store")
    shutil.copytree(fixture, root)
    provider = ProviderId("fixture_live")
    validate_store(root, provider)
    with pytest.raises(ObservationStoreRefusedError, match="integrity.seal"):
        integrity.inspect_integrity(root, provider)
    integrity.seal_store(root, provider)
    integrity.audit_store(root, provider)


def test_ctime_only_inspection_is_cheap_and_writer_checks_original_digest(tmp_path, monkeypatch):
    root, provider = _compiled(tmp_path)
    sealed = integrity.inspect_integrity(root, provider)
    identifier, part = next(iter(sealed.store.partition_files.items()))
    before = part.stat()
    content = bytearray(part.read_bytes())
    content[len(content) // 2] ^= 1
    part.write_bytes(content)
    os.utime(part, ns=(before.st_atime_ns, before.st_mtime_ns))
    original = integrity._digest

    def metadata_only(path):
        assert path.name == "manifest.json"
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(integrity, "_digest", metadata_only)
        inspected = integrity.inspect_integrity(root, provider)
        assert inspected.files == sealed.files
    with pytest.raises(ObservationStoreRefusedError, match="digest"):
        integrity.link_partition(inspected, identifier, tmp_path / "candidate" / part.name)


def test_inventory_link_semantic_rule_after_resigning_metadata(tmp_path):
    root, provider = _compiled(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    raw["inventories"][0]["members"] = ["missing-series"]
    path.write_text(json.dumps(raw))
    _resign(root)
    with pytest.raises(ObservationStoreRefusedError, match="inventory.member"):
        integrity.audit_store(root, provider)


def test_unlisted_pending_seal_does_not_change_committed_identity(tmp_path):
    root, provider = _compiled(tmp_path)
    generation = integrity.inspect_integrity(root, provider).generation_id
    pending = root / ".integrity.pending"
    pending.write_text("partial new seal")
    with pytest.raises(ObservationStoreRefusedError, match="unlisted_or_unsafe"):
        integrity.inspect_integrity(root, provider)
    # Explicit recovery owns this exact entry; audit never deletes it.
    with pytest.raises(ObservationStoreRefusedError, match="unlisted_or_unsafe"):
        integrity.audit_store(root, provider)
    assert pending.read_text() == "partial new seal"
    pending.unlink()
    assert integrity.audit_store(root, provider).generation_id == generation


def test_incremental_seal_refuses_removed_support_without_reading_old_rows(tmp_path, monkeypatch):
    fixture = Path("tests/test_data/source_series_store_conformance/accumulated/valid_native_rows")
    root = StoreRoot(tmp_path / "old")
    shutil.copytree(fixture, root)
    provider = ProviderId("fixture_live")
    previous = integrity.seal_store(root, provider)
    candidate = StoreRoot(tmp_path / "candidate")
    candidate.mkdir()
    raw = json.loads((root / "manifest.json").read_text())
    raw["coverage"] = []
    (candidate / "manifest.json").write_text(json.dumps(raw))
    reused = {
        identifier: integrity.link_partition(previous, identifier, candidate / path.relative_to(root))
        for identifier, path in previous.store.partition_files.items()
    }
    monkeypatch.setattr(
        "rivretrieve._internal.store.validation._open_parquet", lambda path: pytest.fail("unchanged partition decoded")
    )
    with pytest.raises(ObservationStoreRefusedError, match="reuse_coverage"):
        integrity.seal_store(candidate, provider, previous=previous, reused=reused)


def test_incremental_metadata_only_seal_reuses_original_digests(tmp_path, monkeypatch):
    fixture = Path("tests/test_data/source_series_store_conformance/accumulated/valid_native_rows")
    root = StoreRoot(tmp_path / "old")
    shutil.copytree(fixture, root)
    provider = ProviderId("fixture_live")
    previous = integrity.seal_store(root, provider)
    candidate = StoreRoot(tmp_path / "candidate")
    candidate.mkdir()
    raw = json.loads((root / "manifest.json").read_text())
    raw["built_at"] = "2026-10-05T10:00:00.000000Z"
    (candidate / "manifest.json").write_text(json.dumps(raw))
    reused = {
        identifier: integrity.link_partition(previous, identifier, candidate / path.relative_to(root))
        for identifier, path in previous.store.partition_files.items()
    }
    original = integrity._digest

    def metadata_only(path):
        assert path.name == "manifest.json"
        return original(path)

    monkeypatch.setattr(integrity, "_digest", metadata_only)
    monkeypatch.setattr(
        "rivretrieve._internal.store.validation._open_parquet", lambda path: pytest.fail("unchanged partition decoded")
    )
    sealed = integrity.seal_store(candidate, provider, previous=previous, reused=reused)
    assert sealed.generation_id != previous.generation_id
    for name, identity in sealed.files.items():
        if name.endswith(".parquet"):
            assert identity.sha256 == previous.files[name].sha256
            assert identity.inode == previous.files[name].inode


def test_explicit_recovery_inspection_ignores_only_regular_pending_seal(tmp_path):
    root, provider = _compiled(tmp_path)
    generation = integrity.inspect_integrity(root, provider).generation_id
    pending = root / ".integrity.pending"
    pending.write_text("partial new seal")
    assert integrity.inspect_integrity(root, provider, allow_pending=True).generation_id == generation
    assert integrity.audit_store(root, provider, allow_pending=True).generation_id == generation
    assert pending.read_text() == "partial new seal"
    pending.unlink()
    external = tmp_path / "outside.json"
    external.write_text("do not open")
    pending.symlink_to(external)
    with pytest.raises(ObservationStoreRefusedError, match="unsafe"):
        integrity.inspect_integrity(root, provider, allow_pending=True)
    assert external.read_text() == "do not open"


def test_incremental_seal_cannot_relabel_unchanged_row_acquisition(tmp_path):
    fixture = Path("tests/test_data/source_series_store_conformance/accumulated/valid_native_rows")
    root = StoreRoot(tmp_path / "old")
    shutil.copytree(fixture, root)
    provider = ProviderId("fixture_live")
    previous = integrity.seal_store(root, provider)
    candidate = StoreRoot(tmp_path / "candidate")
    candidate.mkdir()
    raw = json.loads((root / "manifest.json").read_text())
    for record in raw["coverage"]:
        record["retrieved_at"] = "2026-10-05T00:00:00.000000Z"
    for outcome in raw["outcomes"]:
        outcome["retrieved_at"] = "2026-10-05T00:00:00.000000Z"
    (candidate / "manifest.json").write_text(json.dumps(raw))
    reused = {
        identifier: integrity.link_partition(previous, identifier, candidate / path.relative_to(root))
        for identifier, path in previous.store.partition_files.items()
    }
    with pytest.raises(ObservationStoreRefusedError, match="reuse_acquisition"):
        integrity.seal_store(candidate, provider, previous=previous, reused=reused)


def _linked_live_store(tmp_path):
    fixture = Path("tests/test_data/source_series_store_conformance/accumulated/valid_native_rows")
    root = StoreRoot(tmp_path / "store")
    shutil.copytree(fixture, root)
    raw = json.loads((root / "manifest.json").read_text())
    raw["source_calls"] = [
        {"call_id": "attempt-one", "acquisition_id": "acquisition", "url": "https://example.invalid/observations"},
        {"call_id": "attempt-two", "acquisition_id": "acquisition", "url": "https://example.invalid/observations"},
    ]
    raw["outcomes"][0]["calls"] = ["acquisition", "attempt-one", "attempt-two"]
    # Use a valid compiled snapshot carrier, with explicit local dependencies.
    compiled_path = tmp_path / "compiled"
    compiled_path.mkdir()
    compiled, _ = _compiled(compiled_path)
    snapshot = json.loads((compiled / "manifest.json").read_text())["inventories"][0]
    snapshot.update(
        snapshot_id="inventory",
        members=[raw["series"][0]["series_id"]],
        member_facts=[],
        evidence=[
            "untyped source description",
            "https://example.invalid/evidence",
            "source-call:acquisition",
            "source-call:attempt-one",
            "retrieval-outcome:" + raw["outcomes"][0]["outcome_id"],
        ],
    )
    raw["inventories"] = [snapshot]
    (root / "manifest.json").write_text(json.dumps(raw))
    provider = ProviderId("fixture_live")
    integrity.seal_store(root, provider)
    return root, provider


def test_evidence_links_accept_retry_aliases_and_untyped_source_evidence(tmp_path):
    root, provider = _linked_live_store(tmp_path)
    assert integrity.audit_store(root, provider).rows_checked > 0


@pytest.mark.parametrize(
    "defect,rule",
    [
        ("missing_attempt", "outcome.calls"),
        ("missing_all_calls", "outcome.calls"),
        ("bad_call_id", "source_call.identity"),
        ("missing_inventory", "inventory.source_inventory"),
        ("missing_inventory_call", "inventory.source_call"),
        ("missing_outcome", "inventory.retrieval_outcome"),
    ],
)
def test_audit_rejects_dangling_acquisition_links_after_resigning(tmp_path, defect, rule):
    root, provider = _linked_live_store(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    if defect == "missing_attempt":
        raw["source_calls"].pop()
    elif defect == "missing_all_calls":
        raw["source_calls"] = []
    elif defect == "bad_call_id":
        raw["source_calls"][0]["call_id"] = 42
    elif defect == "missing_inventory":
        raw["inventories"][0]["evidence"].append("source-inventory:missing")
    elif defect == "missing_inventory_call":
        raw["inventories"][0]["evidence"].append("source-call:missing")
    else:
        raw["inventories"][0]["evidence"].append("retrieval-outcome:missing")
    path.write_text(json.dumps(raw))
    _resign(root)
    with pytest.raises(ObservationStoreRefusedError, match=rule):
        integrity.audit_store(root, provider)


def test_metadata_only_inventory_call_dependency_is_checked(tmp_path):
    root, provider = _linked_live_store(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    raw["outcomes"] = []
    raw["coverage"] = []
    raw["partition_row_counts"] = {}
    raw["inventories"][0]["evidence"] = [
        item for item in raw["inventories"][0]["evidence"] if not item.startswith("retrieval-outcome:")
    ]
    for directory in root.glob("product=*"):
        shutil.rmtree(directory)
    path.write_text(json.dumps(raw))
    integrity.seal_store(root, provider)
    raw["source_calls"] = []
    path.write_text(json.dumps(raw))
    _resign(root)
    with pytest.raises(ObservationStoreRefusedError, match="inventory.source_call"):
        integrity.audit_store(root, provider)


def _store_with_supporting_failure(tmp_path):
    root, provider = _linked_live_store(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    original = dict(raw["outcomes"][0])
    original.update(
        outcome_id="original-failure", status="failed", reason="original source failure", calls=["support-only-attempt"]
    )
    raw["source_calls"].append({"call_id": "support-only-attempt", "acquisition_id": "support-only-acquisition"})
    raw["supporting_outcomes"] = [original]
    raw["inventories"][0]["evidence"].append("retrieval-outcome:original-failure")
    path.write_text(json.dumps(raw))
    integrity.seal_store(root, provider)
    return root, provider


def test_supporting_failure_is_internal_and_preserved_by_witness_refresh(tmp_path):
    root, provider = _store_with_supporting_failure(tmp_path)
    sealed = integrity.inspect_integrity(root, provider)
    assert [item.outcome_id for item in sealed.supporting_outcomes] == ["original-failure"]
    assert all(item.outcome_id != "original-failure" for item in sealed.store.manifest.outcomes)
    assert not hasattr(sealed.store.manifest, "supporting_outcomes")
    refreshed = integrity.refresh_witnesses(sealed)
    assert refreshed.supporting_outcomes == sealed.supporting_outcomes
    assert integrity.audit_store(root, provider).generation_id == sealed.generation_id


@pytest.mark.parametrize(
    "defect,rule",
    [
        ("calls", "outcome.calls"),
        ("conflict", "outcome.identity"),
        ("unreferenced", "supporting_outcome.unreferenced"),
        ("coverage", "coverage.outcome"),
    ],
)
def test_support_only_outcomes_cannot_bypass_links_or_authorize_rows(tmp_path, defect, rule):
    root, provider = _store_with_supporting_failure(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    if defect == "calls":
        raw["supporting_outcomes"][0]["calls"] = ["missing-call"]
    elif defect == "conflict":
        raw["supporting_outcomes"][0]["outcome_id"] = raw["outcomes"][0]["outcome_id"]
    elif defect == "unreferenced":
        raw["inventories"][0]["evidence"].remove("retrieval-outcome:original-failure")
    else:
        raw["supporting_outcomes"].append(raw["outcomes"].pop())
    path.write_text(json.dumps(raw))
    _resign(root)
    with pytest.raises(ObservationStoreRefusedError, match=rule):
        integrity.audit_store(root, provider)


@pytest.mark.parametrize("reference", ["original-failure", "missing-outcome", None, 42])
def test_active_issue_cannot_reference_support_only_or_missing_outcome(tmp_path, reference):
    root, provider = _store_with_supporting_failure(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    raw["issues"] = [
        {
            "severity": "error",
            "code": "source.request_failed",
            "message": "source failure",
            "details": {"outcome_id": reference},
        }
    ]
    path.write_text(json.dumps(raw))
    _resign(root)
    with pytest.raises(ObservationStoreRefusedError, match="issue.outcome"):
        integrity.audit_store(root, provider)


def test_issue_current_pointer_and_original_trace_have_distinct_roles(tmp_path):
    root, provider = _store_with_supporting_failure(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    raw["issues"] = [
        {
            "severity": "info",
            "code": "source.note",
            "message": "source note",
            "details": {"outcome_id": raw["outcomes"][0]["outcome_id"], "original_outcome_id": "unretained-original"},
        },
        {"severity": "info", "code": "source.note", "message": "unscoped source note"},
    ]
    path.write_text(json.dumps(raw))
    integrity.seal_store(root, provider)
    integrity.audit_store(root, provider)


@pytest.mark.parametrize(
    "references",
    [[], ["support-only-acquisition"], ["missing"], ["acquisition", "acquisition"], [42], None, "acquisition"],
)
def test_active_issue_acquisitions_require_unique_current_ids(tmp_path, references):
    root, provider = _store_with_supporting_failure(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    raw["issues"] = [
        {
            "severity": "info",
            "code": "source.native_quality",
            "message": "source code preserved",
            "details": {"acquisition_ids": references, "native_code": "Q"},
        }
    ]
    path.write_text(json.dumps(raw))
    _resign(root)
    with pytest.raises(ObservationStoreRefusedError, match="issue.acquisitions"):
        integrity.audit_store(root, provider)


def test_issue_acquisition_aliases_resolve_from_active_retry_calls(tmp_path):
    root, provider = _store_with_supporting_failure(tmp_path)
    path = root / "manifest.json"
    raw = json.loads(path.read_text())
    # Only the concrete attempt is in the outcome. Acquisition and retry aliases
    # belong to that same actual retrieval and may support the source note.
    raw["outcomes"][0]["calls"] = ["attempt-one"]
    raw["issues"] = [
        {
            "severity": "info",
            "code": "source.native_quality",
            "message": "source code preserved",
            "details": {
                "outcome_id": raw["outcomes"][0]["outcome_id"],
                "acquisition_ids": ["acquisition", "attempt-two"],
                "native_code": "Q",
            },
        }
    ]
    path.write_text(json.dumps(raw))
    integrity.seal_store(root, provider)
    integrity.audit_store(root, provider)


@pytest.mark.parametrize("state", [None, False, "unexpected"])
def test_storage_issue_context_marker_requires_known_state(tmp_path, state):
    root, provider = _linked_live_store(tmp_path)
    manifest = root / "manifest.json"
    raw = json.loads(manifest.read_text())
    raw["issues"] = [
        {
            "severity": "info",
            "code": "source.authored",
            "message": "Authored note",
            "details": {"acquisition_ids": ["acquisition"], "_source_details_state": state},
        }
    ]
    manifest.write_text(json.dumps(raw))
    _resign(root)
    with pytest.raises(ObservationStoreRefusedError, match="issue.context"):
        integrity.audit_store(root, provider)
