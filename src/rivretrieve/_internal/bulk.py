"""bulk lifecycle : BulkProvider × CacheRoot → CompiledStoreStatus.

This composition root owns consent, paths, disk admission and the download/compile
sequence. Provider modules retain only publisher-specific transfer and decoding.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from rivretrieve._internal.discovery import _ensure_default_providers_registered
from rivretrieve._internal.engine import ObservationStoreConfig, ProviderConfig
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.registry import _ProviderHandle, _registry
from rivretrieve._internal.store import StoreRoot, StoreStatus, ValidatedStore, store_status
from rivretrieve._internal.transport import HttpClient, HttpMethod, TransportRequest


class BulkOperationsUnavailableError(FatalContractError):
    """Raised when a bulk-only verb is applied to a publisher-payload provider."""


class InsufficientDiskSpaceError(FatalContractError):
    """A pre-download refusal carrying both sides of the space comparison."""

    def __init__(self, provider_id: ProviderId, required_bytes: int, available_bytes: int) -> None:
        self.provider_id = provider_id
        self.required_bytes = required_bytes
        self.available_bytes = available_bytes
        super().__init__(
            f"Cannot download {provider_id}: compile requires {required_bytes} bytes free, "
            f"but only {available_bytes} bytes are available. No download was started."
        )


@dataclass(frozen=True, slots=True)
class CacheClearResult:
    provider_id: ProviderId
    path: Path
    existed: bool
    bytes_freed: int


class FreeSpaceProbe(Protocol):
    def __call__(self, path: Path) -> int: ...


ClientFactory = Callable[[], HttpClient]


def download(provider: str) -> ValidatedStore:
    """Explicitly download and compile one bulk provider's publisher artifact."""
    return _download(
        provider,
        free_space_probe=_available_bytes,
        client_factory=HttpClient,
        today=date.today(),
    )


def cache_status(provider: str) -> StoreStatus:
    """Report the validated local store for a bulk provider without network access."""
    provider_id, _config, root = _bulk_registration(provider)
    return store_status(root, provider_id)


def clear_cache(provider: str) -> CacheClearResult:
    """Delete a bulk provider's compiled store and report the exact loss."""
    provider_id, _config, root = _bulk_registration(provider)
    path = Path(root)
    existed = path.exists() or path.is_symlink()
    bytes_freed = _tree_size(path) if existed else 0
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
    return CacheClearResult(provider_id, path, existed, bytes_freed)


def _download(
    provider: str,
    *,
    free_space_probe: FreeSpaceProbe,
    client_factory: ClientFactory,
    today: date,
) -> ValidatedStore:
    provider_id, store_config, root = _bulk_registration(provider)
    # This is deliberately the first effectful operation. In particular the cache
    # directory and HTTP client do not exist until admission succeeds.
    probe_path = _nearest_existing_parent(Path(root))
    available = free_space_probe(probe_path)
    required = store_config.required_free_bytes
    if available < required:
        raise InsufficientDiskSpaceError(provider_id, required, available)

    work = Path(root).parent
    work.mkdir(parents=True, exist_ok=True)
    artifact = work / "publisher-artifact.download"
    client = client_factory()
    if provider_id == "ca_eccc":
        return _download_ca_eccc(artifact, root, client, today)
    if provider_id == "pl_imgw":
        return _download_pl_imgw(artifact, root, client, today)
    raise AssertionError(f"registered bulk provider has no composition-root wiring: {provider_id}")


def _download_ca_eccc(artifact: Path, root: StoreRoot, client: HttpClient, today: date) -> ValidatedStore:
    from rivretrieve import __version__
    from rivretrieve._internal.providers.ca_eccc.bulk import HydatCompileRequest, compile, download

    downloaded = download(
        artifact,
        today=today,
        probe=lambda url: client.send(TransportRequest(HttpMethod.HEAD, url)).status_code,
        transfer=lambda url, destination: _transfer(client, url, destination),
    )
    return compile(
        HydatCompileRequest(
            publisher_artifact=downloaded.path,
            destination=root,
            publisher_url=downloaded.url,
            source_vintage=downloaded.source_vintage,
            built_at=datetime.now(UTC),
            compiler_version=__version__,
        )
    )


def _download_pl_imgw(artifact: Path, root: StoreRoot, client: HttpClient, today: date) -> ValidatedStore:
    from rivretrieve import __version__
    from rivretrieve._internal.providers.pl_imgw.bulk import ImgwCompileRequest, compile, download

    downloaded = download(
        artifact,
        year=today.year,
        source_vintage=today,
        transfer=lambda url, destination: _transfer(client, url, destination),
    )
    return compile(
        ImgwCompileRequest(
            publisher_artifact=downloaded.path,
            destination=root,
            publisher_url=downloaded.url,
            source_vintage=downloaded.source_vintage,
            built_at=datetime.now(UTC),
            compiler_version=__version__,
        )
    )


def _transfer(client: HttpClient, url: str, destination: Path) -> None:
    response = client.send(TransportRequest(HttpMethod.GET, url))
    if not 200 <= response.status_code < 300:
        raise FatalContractError(f"Publisher download returned HTTP {response.status_code}: {url}")
    destination.write_bytes(response.content)


def _bulk_registration(provider: str) -> tuple[ProviderId, ObservationStoreConfig, StoreRoot]:
    if not isinstance(provider, str) or not provider:
        raise TypeError("provider must be a non-empty provider id")
    _ensure_default_providers_registered()
    handle: _ProviderHandle = _registry.get(provider)
    config: ProviderConfig | None = handle._store_config
    root = handle._store_root
    if config is None or config.cache is None or config.cache.store is None or root is None:
        raise BulkOperationsUnavailableError(
            f"Provider {provider} does not publish bulk observations; "
            "download(), cache_status() and clear_cache() are available only for bulk providers."
        )
    return handle.provider_id, config.cache.store, root


def _available_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise FileNotFoundError(f"no existing parent for cache path {path}")
        candidate = parent
    return candidate


def _tree_size(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    return sum(item.lstat().st_size for item in path.rglob("*") if item.is_file() or item.is_symlink())
