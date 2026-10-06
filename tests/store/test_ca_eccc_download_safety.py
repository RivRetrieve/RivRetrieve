"""HYDAT release discovery preserves certified stores and artifact targets."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal import bulk as lifecycle
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc.bulk import HYDAT_URL_TEMPLATE
from rivretrieve._internal.providers.ca_eccc.declaration import declaration
from rivretrieve._internal.providers.registration import BulkStore
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import StoreRoot, validate_store
from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest
from tests.store.test_ca_eccc_provenance import _hydat


def url(vintage):
    return HYDAT_URL_TEMPLATE.format(vintage=vintage.strftime("%Y%m%d"))


@pytest.fixture
def public_hydat(tmp_path, monkeypatch, stub_packaged_catalogue_artifact):
    operations = declaration.observations
    assert isinstance(operations, BulkStore)
    root = StoreRoot(tmp_path / "ca_eccc" / "store")
    registry = ProviderRegistry()
    registry.register(
        "ca_eccc",
        stub_packaged_catalogue_artifact("ca_eccc"),
        bulk_config=operations.config,
        observation_store=root,
        bulk_operations=operations,
    )
    responses = {}
    calls = []

    class OfflineClient:
        def send(self, request):
            calls.append((request.method.value, request.url))
            response = responses[request.url]
            if isinstance(response, Exception):
                raise response
            if isinstance(response, int):
                return SimpleNamespace(status_code=response, content=b"")
            return SimpleNamespace(status_code=200, content=response)

    class Clock(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 22)

    monkeypatch.setattr(lifecycle, "_ensure_default_providers_registered", lambda: None)
    monkeypatch.setattr(lifecycle, "_registry", registry)
    monkeypatch.setattr(lifecycle, "HttpClient", OfflineClient)
    monkeypatch.setattr(lifecycle, "date", Clock)
    monkeypatch.setattr(lifecycle, "_available_bytes", lambda path: 100_000_000_000)
    artifact = tmp_path / "source.sqlite3"
    _hydat(artifact)
    return root, responses, calls, artifact


def store_bytes(root):
    return {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}


def test_public_hydat_older_fallback_preserves_certified_store(public_hydat):
    root, responses, calls, artifact = public_hydat
    current = url(date(2026, 9, 22))
    older = url(date(2026, 9, 21))
    responses[current] = artifact.read_bytes()
    original = rr.download("ca_eccc")
    before = store_bytes(root)
    responses.update({current: 404, older: artifact.read_bytes()})
    calls.clear()

    with pytest.raises(ValueError, match="regress.*2026-09-22.*2026-09-21"):
        rr.download("ca_eccc")

    assert calls == [("HEAD", current), ("HEAD", older)]
    assert store_bytes(root) == before
    assert validate_store(root, ProviderId("ca_eccc")).manifest == original.manifest
    assert rr.cache_status("ca_eccc").source_vintage == date(2026, 9, 22)
    assert not tuple(Path(root).parent.glob("publisher-artifact.download*"))


@pytest.mark.parametrize("original_vintage", [date(2026, 9, 21), date(2026, 9, 22)])
def test_public_hydat_same_or_newer_release_can_have_fewer_rows(public_hydat, original_vintage):
    # Two compilations are needed to distinguish a vintage guard from a row-count guard.
    import sqlite3

    root, responses, calls, artifact = public_hydat
    current = url(date(2026, 9, 22))
    older = url(date(2026, 9, 21))
    responses.update({current: 404, older: artifact.read_bytes()})
    responses[url(original_vintage)] = artifact.read_bytes()
    original = rr.download("ca_eccc")
    assert original.manifest.source_vintage == original_vintage
    with sqlite3.connect(artifact) as connection:
        connection.execute("DELETE FROM DLY_LEVELS")
    responses[current] = artifact.read_bytes()
    calls.clear()

    result = rr.download("ca_eccc")

    assert calls == [("HEAD", current), ("GET", current)]
    assert result.manifest.source_vintage == date(2026, 9, 22)
    assert sum(dict(result.manifest.partition_row_counts).values()) == 31
    assert sum(dict(original.manifest.partition_row_counts).values()) == 62
    rows = pl.read_parquet(list(Path(root).rglob("*.parquet")), hive_partitioning=False)
    assert rows.height == 31
    assert validate_store(root, ProviderId("ca_eccc")).manifest == result.manifest
    assert not tuple(Path(root).parent.glob("publisher-artifact.download*"))


@pytest.mark.parametrize("status", [403, 302, 500])
def test_public_hydat_unexpected_head_status_stops_with_reason(public_hydat, status):
    root, responses, calls, _artifact = public_hydat
    current = url(date(2026, 9, 22))
    responses[current] = status

    with pytest.raises(OSError, match=f"HTTP {status}.*{current}"):
        rr.download("ca_eccc")

    assert calls == [("HEAD", current)]
    assert not Path(root).exists()
    assert not tuple(Path(root).parent.glob("publisher-artifact.download*"))


@pytest.mark.parametrize("existing_target", [False, True])
def test_public_hydat_refuses_artifact_symlink_before_network(public_hydat, tmp_path, existing_target):
    root, _responses, calls, _artifact = public_hydat
    Path(root).parent.mkdir(parents=True)
    external = tmp_path / "outside-artifact"
    if existing_target:
        external.write_bytes(b"keep")
    target = Path(root).parent / "publisher-artifact.download"
    target.symlink_to(external)

    with pytest.raises(FileExistsError, match="already exists"):
        rr.download("ca_eccc")

    assert calls == []
    assert target.is_symlink()
    assert external.exists() is existing_target
    if existing_target:
        assert external.read_bytes() == b"keep"
    assert not Path(root).exists()


def test_public_hydat_transport_failure_keeps_retry_identity(public_hydat):
    _root, responses, calls, _artifact = public_hydat
    current = url(date(2026, 9, 22))
    failure = TransportFailure(
        TransportRequest(HttpMethod.HEAD, current),
        TransportFailureReason.RETRY_EXHAUSTED,
        3,
        status_code=503,
    )
    responses[current] = failure

    with pytest.raises(TransportFailure) as caught:
        rr.download("ca_eccc")

    assert caught.value is failure
    assert calls == [("HEAD", current)]


@pytest.mark.parametrize("refusal_phase", ["compilation", "certification replay"])
def test_public_post_transfer_admission_uses_resolved_probe(public_hydat, monkeypatch, refusal_phase) -> None:
    from datetime import date

    import rivretrieve as rr
    from rivretrieve._internal import bulk
    from rivretrieve._internal.store.lifecycle import StoreTransactionError
    from rivretrieve._internal.store.resources import CompilationPhase, InsufficientPreparationSpaceError

    root, responses, calls, artifact = public_hydat
    publisher = url(date(2026, 9, 22))
    responses[publisher] = artifact.read_bytes()
    rr.download("ca_eccc")
    before = store_bytes(root)
    calls.clear()
    probed = []

    def free(path):
        probed.append(path)
        # Source and native temp share this test filesystem: one check per phase.
        allowed = 1 if refusal_phase == "compilation" else 2
        return 10**12 if len(probed) <= allowed else 0

    monkeypatch.setattr(bulk, "_available_bytes", free)
    from rivretrieve._internal.providers.ca_eccc import bulk as hydat_bulk

    monkeypatch.setattr(hydat_bulk, "resolve_sqlite_temp_directory", lambda: Path(root).parent)
    with pytest.raises((InsufficientPreparationSpaceError, StoreTransactionError)) as caught:
        rr.download("ca_eccc")
    error = caught.value.original if isinstance(caught.value, StoreTransactionError) else caught.value
    assert isinstance(error, InsufficientPreparationSpaceError)
    assert error.phase is CompilationPhase(refusal_phase)
    assert "No download was started" not in str(error)
    assert calls == [("HEAD", publisher), ("GET", publisher)]
    assert len(probed) == (2 if refusal_phase == "compilation" else 3)
    assert probed[-1].name.startswith(".store.workspace-")
    assert store_bytes(root) == before
    assert artifact.exists()
