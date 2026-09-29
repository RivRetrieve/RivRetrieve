"""Authenticated GitHub release access and integrity-gated evidence extraction."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .archives import ArchivePaths, extract_archive
from .index import Asset, Collection, EvidenceError, EvidenceIndex
from .manifest import verify_collection


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("GH_DEBUG", None)
    environment.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    return environment


def _command(endpoint: str) -> list[str]:
    return ["gh", "api", "--hostname", "github.com", endpoint]


type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None


def _metadata(endpoint: str, *, method: str = "GET", payload: dict[str, JsonValue] | None = None) -> JsonValue:
    try:
        command = _command(endpoint)
        if method != "GET":
            command += ["--method", method, "--input", "-"]
        result = subprocess.run(
            command,
            input=json.dumps(payload).encode() if payload is not None else None,
            capture_output=True,
            check=True,
            timeout=60,
            env=_environment(),
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise EvidenceError(
            "GitHub metadata unavailable. Check gh authentication and organization access, then retry the exact release."
        ) from None


def check_release(repository: str, collection: Collection, *, draft: bool = False, exact_assets: bool = False) -> None:
    """Confirm release ID, tag and asset membership through authenticated GitHub API calls."""
    prefix = f"repos/{repository}/releases/{collection.release_id}"
    release = _metadata(prefix)
    if (
        not isinstance(release, dict)
        or type(release.get("id")) is not int
        or release.get("id") != collection.release_id
        or release.get("tag_name") != collection.release_tag
        or release.get("draft") is not draft
    ):
        raise EvidenceError("Release identity differs from the index; review the pinned release before continuing.")
    expected = {asset.asset_id: asset for asset in collection.assets}
    seen: set[int] = set()
    for page in range(1, 12):
        records = _metadata(f"{prefix}/assets?per_page=100&page={page}")
        if not isinstance(records, list) or len(records) > 100 or (page == 11 and records):
            raise EvidenceError("Release asset listing is invalid; review the pinned release.")
        for record in records:
            identity = record.get("id") if isinstance(record, dict) else None
            if not isinstance(record, dict) or type(identity) is not int or identity in seen:
                raise EvidenceError("Release asset identities are invalid; review the pinned release.")
            seen.add(identity)
            asset = expected.get(identity)
            if asset is not None and (
                record.get("name") != asset.name
                or type(record.get("size")) is not int
                or record.get("size") != asset.byte_size
                or record.get("state") != "uploaded"
                or record.get("digest") not in (None, f"sha256:{asset.sha256}")
            ):
                raise EvidenceError("Release asset metadata differs from the index; do not use replacement bytes.")
        if len(records) < 100:
            break
    if (exact_assets and expected.keys() != seen) or not expected.keys() <= seen:
        raise EvidenceError("Pinned asset is missing from its release; ask an evidence maintainer to investigate.")


def download_asset(repository: str, asset: Asset, destination: Path) -> None:
    """Stream one exact asset ID, cap its bytes, then verify size and SHA-256.

    Raw GitHub errors and response bodies are never forwarded to the console.
    The caller owns the temporary destination and removes it on failure.
    """
    digest = hashlib.sha256()
    size = 0
    try:
        with (
            destination.open("xb") as output,
            subprocess.Popen(
                [
                    *_command(f"repos/{repository}/releases/assets/{asset.asset_id}"),
                    "-H",
                    "Accept: application/octet-stream",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=_environment(),
            ) as process,
        ):
            timer = threading.Timer(300, process.kill)
            timer.daemon = True
            timer.start()
            try:
                assert process.stdout is not None
                while block := process.stdout.read(min(1024 * 1024, asset.byte_size - size + 1)):
                    size += len(block)
                    if size > asset.byte_size:
                        raise EvidenceError("Downloaded asset exceeds its pinned size; reject these bytes.")
                    digest.update(block)
                    output.write(block)
                if process.wait() != 0:
                    raise EvidenceError("Asset download failed. Check gh authentication and access, then retry.")
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                    process.wait()
        if size != asset.byte_size or digest.hexdigest() != asset.sha256:
            raise EvidenceError("Downloaded size or SHA-256 differs from the index; reject these bytes.")
    except (OSError, subprocess.SubprocessError):
        raise EvidenceError("Asset download failed. Check gh installation, access and available disk space.") from None


def _external_destination(destination: Path, source_roots: tuple[Path, ...]) -> Path:
    try:
        resolved = destination.expanduser().resolve()
        if any(resolved.is_relative_to(root.resolve()) for root in source_roots):
            raise EvidenceError("Choose an evidence destination outside all source checkouts.")
        if any((parent / ".git").exists() for parent in (resolved, *resolved.parents)):
            raise EvidenceError("Choose an evidence destination outside all source checkouts.")
        return resolved
    except OSError:
        raise EvidenceError("Cannot resolve a safe evidence destination.") from None


@dataclass(frozen=True)
class SelectedInputs:
    """Verified local working copy and explicitly named consumer directories.

    Paths refer to the new external working copy. Integrity and manifest checks do
    not certify source claims. Consumers receive these resolved paths and need no
    archive credentials or cache discovery.
    """

    collection: Collection
    root: Path
    input_roots: Mapping[str, Path]


def acquire_collection(
    index: EvidenceIndex,
    provider_id: str,
    collection_id: str,
    destination: Path,
    *,
    source_roots: tuple[Path, ...],
) -> SelectedInputs:
    """Download only a provider's selected collection and publish a new external directory.

    Existing evidence is never reused or replaced. Every compressed asset passes
    its size and digest check before any archive is opened. Failed staging is
    removed; original collections and pre-existing destinations remain unchanged.
    """
    provider = next((item for item in index.providers if item.provider_id == provider_id), None)
    if provider is None or collection_id not in provider.collections:
        raise EvidenceError(
            "Provider does not list that collection; select an exact reviewed collection from the index."
        )
    collection = next(item for item in index.collections if item.collection_id == collection_id)
    root = _external_destination(destination, source_roots)
    target = root / collection.collection_id
    if target.exists() or target.is_symlink():
        raise EvidenceError(
            "Evidence destination already exists; choose a new location. Existing bytes were not changed."
        )
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        check_release(index.repository, collection)
        with tempfile.TemporaryDirectory(prefix=".evidence-", dir=root) as temporary:
            staging = Path(temporary)
            unpacked = staging / "content"
            unpacked.mkdir(mode=0o700)
            for asset in collection.assets:
                download_asset(index.repository, asset, staging / str(asset.asset_id))
            paths = ArchivePaths()
            for asset in collection.assets:
                extract_archive(staging / str(asset.asset_id), asset, unpacked, paths)
            if any(not (unpacked / relative).is_dir() for relative in collection.input_roots.values()):
                raise EvidenceError("Collection lacks an indexed input root; review the archive layout.")
            manifest = verify_collection(unpacked, collection)
            expected_providers = {item.provider_id for item in index.providers if collection_id in item.collections}
            if manifest is not None and set(manifest.provider_ids) != expected_providers:
                raise EvidenceError("Collection manifest providers differ from the explicit index selection.")
            # mkdir reserves a new final name atomically. Never replace a pre-existing directory.
            target.mkdir(mode=0o700)
            try:
                os.replace(unpacked, target)
            except OSError:
                target.rmdir()
                raise
        return SelectedInputs(
            collection,
            target,
            MappingProxyType({name: target / relative for name, relative in collection.input_roots.items()}),
        )
    except OSError:
        raise EvidenceError(
            "Cannot create evidence safely; check destination permissions, free space and existing paths."
        ) from None
