"""Public clear_cache recovery : FailedBulkDownloadEvidence → RetryableEmptyCache."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

import rivretrieve as rr
import rivretrieve._internal.bulk as bulk_lifecycle
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc.declaration import declaration as ca_declaration
from rivretrieve._internal.providers.pl_imgw import bulk as pl_bulk
from rivretrieve._internal.providers.pl_imgw.declaration import declaration as pl_declaration
from rivretrieve._internal.providers.registration import (
    BulkDownloadRequest,
    BulkStore,
    DownloadedBulkArtifact,
)
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import StoreRoot, validate_store


def _poland_one_month(request: BulkDownloadRequest) -> tuple[DownloadedBulkArtifact, ...]:
    name = "codz_2022_01.zip"
    target = request.destination.with_name(f"{request.destination.name}-{name}")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'publisher artifact destination already exists: "{target}"')
    url = pl_bulk.MONTHLY_URL_TEMPLATE.format(year=2022, month=1)
    request.transfer(url, target)
    item = pl_bulk.DownloadedImgw(target, url)
    return (DownloadedBulkArtifact(item.path, item.url, item.source_vintage),)


@pytest.mark.parametrize("provider_id", ("ca_eccc", "pl_imgw"))
def test_public_failed_bulk_compile_requires_explicit_clear_then_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    provider_id: str,
) -> None:
    if provider_id == "ca_eccc":
        operations = ca_declaration.observations
        valid = (Path(__file__).parents[1] / "test_data" / "ca_eccc_02GA010_2020_01_derived_input.zip").read_bytes()
        expected_pending_name = "publisher-artifact.download"
        failure_type: type[Exception] = sqlite3.DatabaseError
    else:
        declared = pl_declaration.observations
        assert isinstance(declared, BulkStore)
        operations = BulkStore(declared.config, _poland_one_month, declared.compile)
        valid = read_recording(Path(__file__).parents[1] / "test_data" / "pl_imgw_codz_2022_01.recording.json").content
        expected_pending_name = "publisher-artifact.download-codz_2022_01.zip"
        failure_type = ValueError
    assert isinstance(operations, BulkStore)

    store = StoreRoot(tmp_path / provider_id / "store")
    registry = ProviderRegistry()
    registry.register(
        provider_id,
        stub_packaged_catalogue_artifact(provider_id),
        bulk_config=operations.config,
        observation_store=store,
        bulk_operations=operations,
    )

    class SequencedClient:
        get_count = 0

        def send(self, request):
            if request.method.value == "HEAD":
                return SimpleNamespace(status_code=200, content=b"")
            type(self).get_count += 1
            content = b"not a valid publisher archive" if self.get_count == 1 else valid
            return SimpleNamespace(status_code=200, content=content)

    monkeypatch.setattr(bulk_lifecycle, "_ensure_default_providers_registered", lambda: None)
    monkeypatch.setattr(bulk_lifecycle, "_registry", registry)
    monkeypatch.setattr(bulk_lifecycle, "HttpClient", SequencedClient)

    with pytest.raises(failure_type):
        rr.download(provider_id)
    pending = Path(store).parent / expected_pending_name
    assert pending.is_file()
    preserved = pending.read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        rr.download(provider_id)
    assert pending.read_bytes() == preserved

    cleared = rr.clear_cache(provider_id)
    assert cleared.existed is True
    assert cleared.removed_paths == (pending,)
    assert cleared.bytes_freed == len(preserved)
    assert not pending.exists()

    validated = rr.download(provider_id)
    assert validated.manifest.provider_id == provider_id
    assert validate_store(store, ProviderId(provider_id)).manifest.provider_id == provider_id
    assert not tuple(Path(store).parent.glob("publisher-artifact.download*"))


def test_public_poland_multi_artifact_download_uses_real_declaration_and_compiler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    from datetime import date

    operations = pl_declaration.observations
    assert isinstance(operations, BulkStore)
    monkeypatch.setattr(pl_bulk, "FIRST_PUBLISHED_YEAR", 2022)
    names = ["codz_2022_01.zip", "codz_2022_02.zip"]
    from tests.store.test_pl_imgw_publication_public import publication

    content_by_url = publication({2022: names})
    calls = []

    class OfflineClient:
        def send(self, request):
            if request.method.value == "HEAD":
                return SimpleNamespace(status_code=200, content=b"")
            calls.append(request.url)
            return SimpleNamespace(status_code=200, content=content_by_url[request.url])

    root = StoreRoot(tmp_path / "pl_imgw" / "store")
    registry = ProviderRegistry()
    registry.register(
        "pl_imgw",
        stub_packaged_catalogue_artifact("pl_imgw"),
        bulk_config=operations.config,
        observation_store=root,
        bulk_operations=operations,
    )
    monkeypatch.setattr(bulk_lifecycle, "_ensure_default_providers_registered", lambda: None)
    monkeypatch.setattr(bulk_lifecycle, "_registry", registry)
    monkeypatch.setattr(bulk_lifecycle, "HttpClient", OfflineClient)

    result = rr.download("pl_imgw")

    assert calls == [
        pl_bulk.BASE_URL + "/",
        pl_bulk.BASE_URL + "/2022/",
        *(pl_bulk.BASE_URL + "/2022/" + name for name in names),
    ]
    assert result.manifest.source_vintage == date(2021, 12, 31)
    assert validate_store(root, ProviderId("pl_imgw")).manifest == result.manifest
    assert rr.cache_status("pl_imgw").source_vintage == date(2021, 12, 31)
    assert not tuple(Path(root).parent.glob("publisher-artifact.download*"))
