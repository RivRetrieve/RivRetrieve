"""bulk dispatch : RegisteredBulkDeclaration × EngineInputs → ValidatedStore."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import cast

from rivretrieve._internal import bulk
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.providers.ca_eccc.config import config
from rivretrieve._internal.providers.registration import (
    BulkCompileRequest,
    BulkDownloadRequest,
    BulkStore,
    DownloadedBulkArtifact,
)
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import StoreRoot, ValidatedStore


def test_registered_bulk_declaration_drives_download_without_central_id_wiring(
    tmp_path: Path,
    monkeypatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    provider_id = "xx_bulk"
    compiled = cast(ValidatedStore, object())
    calls: list[str] = []

    def declared_download(request: BulkDownloadRequest) -> DownloadedBulkArtifact:
        calls.append("download")
        request.transfer("https://publisher.example/archive", request.destination)
        return DownloadedBulkArtifact(request.destination, "https://publisher.example/archive", request.today)

    def declared_compile(request: BulkCompileRequest) -> ValidatedStore:
        calls.append("compile")
        assert request.publisher_artifact.read_bytes() == b"publisher"
        assert request.destination == StoreRoot(tmp_path / provider_id / "store")
        return compiled

    operations = BulkStore(config=config, download=declared_download, compile=declared_compile)
    registry = ProviderRegistry()
    registry.register(
        provider_id,
        stub_packaged_catalogue_artifact(provider_id),
        bulk_config=config,
        observation_store=StoreRoot(tmp_path / provider_id / "store"),
        bulk_operations=operations,
    )

    class FakeClient:
        def send(self, request):
            assert request.url == "https://publisher.example/archive"
            return type("Response", (), {"status_code": 200, "content": b"publisher"})()

    monkeypatch.setattr(bulk, "_ensure_default_providers_registered", lambda: None)
    monkeypatch.setattr(bulk, "_registry", registry)
    result = bulk._download(
        provider_id,
        free_space_probe=lambda path: 10_000_000_000,
        client_factory=FakeClient,
        today=date(2026, 8, 19),
    )

    assert result is compiled
    assert calls == ["download", "compile"]
