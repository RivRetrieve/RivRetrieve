"""Private GitHub publication without implicit acceptance or consumer selection."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from .acquisition import (
    JsonValue,
    _command,
    _environment,
    _external_destination,
    _metadata,
    check_release,
    download_asset,
)
from .index import Asset, Collection, EvidenceError, Positive, Record
from .intake import PreparedCollection, _write_private, check_prepared

REPOSITORY = "RivRetrieve/verification-evidence"


class Publication(Record):
    """Exact uploaded identities; publication alone is not evidence acceptance."""

    schema_version: Literal[1]
    repository: Literal["RivRetrieve/verification-evidence"]
    collection: Collection
    immutable: bool | None
    acceptance: Literal["not_evaluated"]


def _private_repository() -> None:
    repository = _metadata(f"repos/{REPOSITORY}")
    if (
        not isinstance(repository, dict)
        or repository.get("full_name") != REPOSITORY
        or repository.get("private") is not True
    ):
        raise EvidenceError(
            "Publication requires the exact private evidence repository; no material was authorized for public upload."
        )


def _unused_release(collection_id: str, tag: str) -> None:
    for page in range(1, 12):
        releases = _metadata(f"repos/{REPOSITORY}/releases?per_page=100&page={page}")
        if not isinstance(releases, list) or len(releases) > 100 or (page == 11 and releases):
            raise EvidenceError("Cannot establish a new release identity safely.")
        for release in releases:
            if not isinstance(release, dict):
                raise EvidenceError("Cannot establish a new release identity safely.")
            if release.get("tag_name") == tag or release.get("name") == collection_id:
                raise EvidenceError(
                    "Release tag or collection identity already exists; existing releases were not changed."
                )
        if len(releases) < 100:
            return


def _release_identity(value: JsonValue, tag: str, *, draft: bool) -> int:
    identity = value.get("id") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or type(identity) is not int
        or identity <= 0
        or value.get("tag_name") != tag
        or value.get("draft") is not draft
    ):
        raise EvidenceError(
            "GitHub returned an unexpected publication identity; inspect the private release without retrying blindly."
        )
    return identity


def _upload(release_id: Positive, source: Path, name: str) -> dict:
    # Capture both streams. gh and GitHub errors can include private asset paths.
    try:
        result = subprocess.run(
            [
                *_command(f"https://uploads.github.com/repos/{REPOSITORY}/releases/{release_id}/assets?name={name}"),
                "--method",
                "POST",
                "-H",
                "Content-Type: application/octet-stream",
                "--input",
                str(source),
            ],
            capture_output=True,
            check=True,
            timeout=600,
            env=_environment(),
        )
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise EvidenceError("Asset upload returned invalid metadata; inspect the private draft.")
        return value
    except (OSError, subprocess.SubprocessError, ValueError):
        raise EvidenceError(
            "Asset publication failed; inspect the private draft. No existing release was overwritten."
        ) from None


def _pin(
    record: PreparedCollection, values: list[dict], release_id: int, tag: str, purpose: str, limitations: list[str]
) -> Collection:
    assets = []
    for expected, value in zip(record.assets, values, strict=True):
        if (
            type(value.get("id")) is not int
            or value["id"] <= 0
            or value.get("name") != expected.name
            or type(value.get("size")) is not int
            or value["size"] != expected.byte_size
            or value.get("state") != "uploaded"
            or value.get("digest") not in (None, "sha256:" + expected.sha256)
        ):
            raise EvidenceError("Uploaded asset metadata differs from the prepared bytes; inspect the private draft.")
        assets.append(Asset(**expected.model_dump(), asset_id=value["id"]))
    return Collection(
        collection_id=record.collection_id,
        release_id=release_id,
        release_tag=tag,
        input_roots=record.input_roots,
        manifest=record.manifest,
        assets=assets,
        purpose=purpose,
        limitations=limitations,
    )


def publish_collection(
    prepared: Path,
    release_tag: str,
    output: Path,
    *,
    purpose: str,
    limitations: list[str],
    source_roots: tuple[Path, ...],
) -> Publication:
    """Create a new draft, verify every upload, then publish its exact selection.

    The output is a new private directory containing a draft selection and, after
    success, ``publication.json``. No accepted collection or consumer index is
    changed. Failures leave a draft unless GitHub already completed publication;
    inspect the recorded release identity before retrying. Existing releases and
    files are never deleted or overwritten.
    """
    try:
        Collection.exact_tag(release_tag)
        if not purpose.strip() or any(not value.strip() for value in limitations):
            raise EvidenceError("Public purpose and limitations must be explicitly reviewed nonempty text.")
        target = _external_destination(output, source_roots)
        if target.exists() or target.is_symlink():
            raise EvidenceError("Publication output already exists; existing records were not changed.")
        if target.is_relative_to(prepared.resolve()) or prepared.resolve().is_relative_to(target):
            raise EvidenceError("Publication output must be separate from the prepared collection.")
        # All bytes and private references are validated before any remote write.
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix=".publication-", dir=target.parent) as temporary:
            staging = Path(temporary)
            extracted = staging / "verified"
            extracted.mkdir(mode=0o700)
            record = check_prepared(prepared, extracted)
            _private_repository()
            _unused_release(record.collection_id, release_tag)
            target.mkdir(mode=0o700)
            # Create only. Never update a release found by tag.
            release = _metadata(
                f"repos/{REPOSITORY}/releases",
                method="POST",
                payload={
                    "tag_name": release_tag,
                    "name": record.collection_id,
                    "draft": True,
                    "body": "Retained source archive. Publication does not establish acceptance or select consumer inputs.",
                },
            )
            release_id = _release_identity(release, release_tag, draft=True)
            _write_private(
                target / "release.json",
                {"repository": REPOSITORY, "release_id": release_id, "release_tag": release_tag},
            )
            uploaded = []
            for asset in record.assets:
                _private_repository()
                uploaded.append(_upload(release_id, prepared / asset.name, asset.name))
            selection = _pin(record, uploaded, release_id, release_tag, purpose, limitations)
            check_release(REPOSITORY, selection, draft=True, exact_assets=True)
            # GitHub may omit its digest. Download every exact asset to prove bytes.
            for asset in selection.assets:
                download_asset(REPOSITORY, asset, staging / str(asset.asset_id))
            _write_private(target / "draft-selection.json", selection.model_dump(mode="json"))
            _private_repository()
            published = _metadata(f"repos/{REPOSITORY}/releases/{release_id}", method="PATCH", payload={"draft": False})
            if _release_identity(published, release_tag, draft=False) != release_id:
                raise EvidenceError(
                    "Published release identity differs from its recorded draft; inspect the private release."
                )
            check_release(REPOSITORY, selection, exact_assets=True)
            immutable = published.get("immutable") if isinstance(published, dict) else None
            if type(immutable) is not bool:
                immutable = None
            result = Publication(
                schema_version=1,
                repository=REPOSITORY,
                collection=selection,
                immutable=immutable,
                acceptance="not_evaluated",
            )
            _write_private(target / "publication.json", result.model_dump(mode="json"))
            return result
    except EvidenceError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError):
        raise EvidenceError(
            "Publication did not complete cleanly; inspect the private output and draft before retrying."
        ) from None
