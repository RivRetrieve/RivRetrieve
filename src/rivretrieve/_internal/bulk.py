"""cache lifecycle : ProviderId × CacheRoot → StoreStatus ⊎ CacheClearResult; download : BulkProvider × CacheRoot → ValidatedStore.

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

from rivretrieve._internal.discovery import _ensure_default_providers_registered, _resolve_store_root
from rivretrieve._internal.engine import ObservationStoreConfig, ProviderConfig
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.registration import (
    BulkCompileRequest,
    BulkDownloadRequest,
    BulkStore,
)
from rivretrieve._internal.registry import _ProviderHandle, _registry
from rivretrieve._internal.store import StoreRoot, StoreStatus, ValidatedStore, store_status
from rivretrieve._internal.transport import HttpClient, HttpMethod, Transport, TransportRequest


class BulkOperationsUnavailableError(FatalContractError):
    """Raised when a bulk-only verb is applied to a publisher-payload provider."""


class BulkArtifactCleanupRefusedError(FatalContractError):
    """Raised when the pending-download namespace contains an unsafe entry."""


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
    """The paths and bytes removed by explicit cache deletion.

    Attributes
    ----------
    provider_id : ProviderId
        Provider whose cache was cleared.
    path : pathlib.Path
        Resolved observation-store path.
    existed : bool
        True if any recognized store or recovery path existed.
    bytes_freed : int
        Sum of removed file and symlink sizes, in bytes.
    removed_paths : tuple[pathlib.Path, ...]
        Store and recognized recovery inputs removed by the call.
    """

    provider_id: ProviderId
    path: Path
    existed: bool
    bytes_freed: int
    removed_paths: tuple[Path, ...]


class FreeSpaceProbe(Protocol):
    def __call__(self, path: Path) -> int: ...


ClientFactory = Callable[[], Transport]


def download(provider: str) -> ValidatedStore:
    """Explicitly download and compile one bulk provider's publisher artifact."""
    return _download(
        provider,
        free_space_probe=_available_bytes,
        client_factory=HttpClient,
        today=date.today(),
    )


def cache_status(provider: str) -> StoreStatus:
    """Report a provider's validated local store without network access."""
    provider_id, root = _cache_registration(provider)
    return store_status(root, provider_id)


def clear_cache(provider: str) -> CacheClearResult:
    """Delete the compiled observation store or accumulated live store, plus recovery inputs.

    This destructive verb also removes preserved pending publisher downloads and
    accumulated-write staging/backup directories so the next retrieval can retry.

    This explicit destructive verb removes preserved failed-compilation inputs so a
    later ``download()`` can retry. It never follows symlinks, never removes an
    unrelated sibling, and refuses a real directory in the pending-file namespace
    before deleting either the store or any pending input.
    """
    provider_id, root = _cache_registration(provider)
    path = Path(root)
    pending = _pending_download_paths(path.parent)
    store_existed = path.exists() or path.is_symlink()
    accumulated_pending = tuple(
        sorted((*path.parent.glob(f".{path.name}.pending-*"), *path.parent.glob(f".{path.name}.backup-*")))
    )
    removed_paths = *((path,) if store_existed else ()), *pending, *accumulated_pending
    bytes_freed = sum(_tree_size(item) for item in removed_paths)
    for item in removed_paths:
        if item.is_symlink() or item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    return CacheClearResult(provider_id, path, bool(removed_paths), bytes_freed, removed_paths)


def _pending_download_paths(work: Path) -> tuple[Path, ...]:
    if work.is_symlink():
        raise BulkArtifactCleanupRefusedError(f'Cannot clear symlinked pending-download namespace: "{work}"')
    if not work.is_dir():
        return ()
    base_name = "publisher-artifact.download"
    candidates = tuple(
        sorted(
            (item for item in work.iterdir() if item.name == base_name or item.name.startswith(f"{base_name}-")),
            key=lambda item: item.name.encode("utf-8"),
        )
    )
    for item in candidates:
        if item.is_symlink() or item.is_file():
            continue
        kind = "unexpected directory" if item.is_dir() else "unexpected filesystem entry"
        raise BulkArtifactCleanupRefusedError(f'Cannot clear {kind} in pending-download namespace: "{item}"')
    return candidates


def _download(
    provider: str,
    *,
    free_space_probe: FreeSpaceProbe,
    client_factory: ClientFactory,
    today: date,
) -> ValidatedStore:
    provider_id, store_config, root, operations = _bulk_registration(provider)
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
    downloaded_value = operations.download(
        BulkDownloadRequest(
            destination=artifact,
            today=today,
            probe=lambda url: client.send(TransportRequest(HttpMethod.HEAD, url)).status_code,
            transfer=lambda url, destination: _transfer(client, url, destination),
        )
    )

    downloaded = downloaded_value if isinstance(downloaded_value, tuple) else (downloaded_value,)

    from rivretrieve import __version__

    return operations.compile(
        BulkCompileRequest(
            publisher_artifacts=downloaded,
            destination=root,
            built_at=datetime.now(UTC),
            compiler_version=__version__,
        )
    )


def _transfer(client: Transport, url: str, destination: Path) -> None:
    response = client.send(TransportRequest(HttpMethod.GET, url))
    if not 200 <= response.status_code < 300:
        raise FatalContractError(f"Publisher download returned HTTP {response.status_code}: {url}")
    destination.write_bytes(response.content)


def _cache_registration(provider: str) -> tuple[ProviderId, StoreRoot]:
    if not isinstance(provider, str) or not provider:
        raise TypeError("provider must be a non-empty provider id")
    _ensure_default_providers_registered()
    handle = _registry.get(provider)
    return handle.provider_id, _resolve_store_root(provider, handle._store_root)


def _bulk_registration(provider: str) -> tuple[ProviderId, ObservationStoreConfig, StoreRoot, BulkStore]:
    if not isinstance(provider, str) or not provider:
        raise TypeError("provider must be a non-empty provider id")
    _ensure_default_providers_registered()
    handle: _ProviderHandle = _registry.get(provider)
    config: ProviderConfig | None = handle._store_config
    root = _resolve_store_root(provider, handle._store_root)
    operations = handle._bulk_operations
    if config is None or config.cache is None or config.cache.store is None or operations is None:
        raise BulkOperationsUnavailableError(
            f"Provider {provider} does not publish bulk observations; download() is available only for bulk providers."
        )
    return handle.provider_id, config.cache.store, root, operations


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
