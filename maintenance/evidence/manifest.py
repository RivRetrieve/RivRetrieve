"""Private acquisition facts and exact retained-member mappings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from .archives import ArchivePaths
from .index import (
    BUILTIN_PROVIDER_IDS, ArtifactRole, Collection, Digest, EvidenceError, Nonnegative,
    Record, Text, _unique_keys, safe_name,
)


class Acquisition(Record):
    """An acquisition identity is independent of bytes, packaging and release dates.

    Missing source facts use ``None``. Text preserves retained facts without
    inferring a time zone or reconstructing a request from response content.
    """

    acquisition_id: Text
    provider_ids: list[Text]
    source_context: Text | None
    request_context: Text | None
    acquired_at: Text | None
    receipt_refs: list[Text]
    limitations: list[Text]

    _identity = field_validator("acquisition_id")(safe_name)


class Artifact(Record):
    """One retained member, its role and reviewed provenance references.

    Equal hashes do not merge artifacts or acquisitions. ``derivation`` records
    known transformations or explains missing lineage; it never supplies bytes.
    """

    artifact_id: Text
    path: Text
    role: ArtifactRole
    byte_size: Nonnegative
    sha256: Digest
    acquisition_ids: list[Text]
    derived_from: list[Text]
    receipt_refs: list[Text]
    derivation: Text | None
    description: Text
    access_restrictions: Text
    limitations: list[Text]

    _identity = field_validator("artifact_id")(safe_name)


class CollectionManifest(Record):
    """Versioned private facts for a collection, excluding the manifest's own bytes."""

    schema_version: Literal[1]
    collection_id: Text
    provider_ids: list[Text]
    input_roots: dict[Text, Text]
    acquisitions: list[Acquisition]
    artifacts: list[Artifact] = Field(min_length=1)
    limitations: list[Text]

    _identity = field_validator("collection_id")(safe_name)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema version must be an integer")
        return value

    @field_validator("input_roots")
    @classmethod
    def roots(cls, value: dict[str, str]) -> dict[str, str]:
        return Collection.relative_roots(value)

    @model_validator(mode="after")
    def references(self) -> Self:
        providers = set(self.provider_ids)
        if not providers or len(providers) != len(self.provider_ids) or not providers <= set(BUILTIN_PROVIDER_IDS):
            raise ValueError("invalid manifest providers")
        acquisitions = {a.acquisition_id: a for a in self.acquisitions}
        artifacts = {a.artifact_id: a for a in self.artifacts}
        if len(acquisitions) != len(self.acquisitions) or len(artifacts) != len(self.artifacts):
            raise ValueError("duplicate retained identity")
        paths = ArchivePaths()
        member_paths = set()
        for artifact in self.artifacts:
            parts = paths.admit(artifact.path, False)
            member_paths.add(parts)
            for refs, allowed in (
                (artifact.acquisition_ids, acquisitions),
                (artifact.derived_from, artifacts),
                (artifact.receipt_refs, artifacts),
            ):
                if len(set(refs)) != len(refs) or not set(refs) <= allowed.keys():
                    raise ValueError("invalid artifact references")
            if artifact.artifact_id in artifact.derived_from or artifact.artifact_id in artifact.receipt_refs:
                raise ValueError("self-referencing artifact")
            if artifact.role in ("publisher_original", "response_recording") and not artifact.acquisition_ids:
                raise ValueError("source artifacts require an independently identified acquisition")
            if artifact.role == "derived_input" and artifact.derivation is None:
                raise ValueError("derived inputs require a known transformation or explicit lineage limitation")
            if any(artifacts[ref].role != "acquisition_receipt" for ref in artifact.receipt_refs):
                raise ValueError("receipt reference has a different role")
        if any(parts[:n] in member_paths for parts in member_paths for n in range(1, len(parts))):
            raise ValueError("member path collides with a parent file")
        for acquisition in self.acquisitions:
            if (
                not acquisition.provider_ids
                or len(set(acquisition.provider_ids)) != len(acquisition.provider_ids)
                or not set(acquisition.provider_ids) <= providers
                or len(set(acquisition.receipt_refs)) != len(acquisition.receipt_refs)
                or not set(acquisition.receipt_refs) <= artifacts.keys()
                or any(artifacts[ref].role != "acquisition_receipt" for ref in acquisition.receipt_refs)
            ):
                raise ValueError("invalid acquisition references")
        # A derived artifact cannot be its own ancestor.
        remaining = {key: set(value.derived_from) for key, value in artifacts.items()}
        while remaining:
            ready = {key for key, refs in remaining.items() if not refs}
            if not ready:
                raise ValueError("cyclic derivation references")
            remaining = {key: refs - ready for key, refs in remaining.items() if key not in ready}
        return self


def read_manifest(path: Path) -> CollectionManifest:
    """Read private metadata with a safe error; callers must not print exception chains."""
    try:
        return CollectionManifest.model_validate(json.loads(path.read_bytes(), object_pairs_hook=_unique_keys))
    except (OSError, ValueError) as error:
        raise EvidenceError("Invalid private collection manifest; review its schema, identities and references.") from error


def fingerprint(path: Path) -> tuple[int, str]:
    """Hash a supplied regular file without loading its body into memory."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def verify_members(root: Path, manifest: CollectionManifest, *, manifest_path: str | None = None) -> None:
    """Require exactly the declared regular files and byte fingerprints.

    Empty directories are packaging only. Symlinks and special files are refused.
    This checks retention, not provider claims or collection acceptance.
    """
    try:
        if root.is_symlink() or not root.is_dir():
            raise EvidenceError("Collection input must be a regular directory.")
        expected = {artifact.path: artifact for artifact in manifest.artifacts}
        paths = ArchivePaths()
        found = set()
        for member in root.rglob("*"):
            relative = member.relative_to(root).as_posix()
            if member.is_symlink() or not (member.is_dir() or member.is_file()):
                raise EvidenceError("Collection contains a link or special file.")
            paths.admit(relative, member.is_dir())
            if member.is_dir():
                continue
            if relative == manifest_path:
                continue
            artifact = expected.get(relative)
            if artifact is None or fingerprint(member) != (artifact.byte_size, artifact.sha256):
                raise EvidenceError("Retained member inventory or fingerprint differs from the private manifest.")
            found.add(relative)
        if found != expected.keys():
            raise EvidenceError("Retained member inventory or fingerprint differs from the private manifest.")
        for relative in manifest.input_roots.values():
            if not (root / relative).is_dir():
                raise EvidenceError("Collection lacks a selected input root.")
    except OSError as error:
        raise EvidenceError("Cannot verify retained files; check input access and available storage.") from error


def verify_collection(root: Path, collection: Collection) -> CollectionManifest | None:
    """Check a bound manifest and all retained members before exposing local inputs.

    Historical packages without a manifest retain their explicit historical state.
    They cannot establish acceptance under the shared manifest contract.
    """
    if collection.manifest is None:
        return None
    binding = collection.manifest
    path = root / binding.path
    try:
        if not path.is_file() or path.is_symlink() or fingerprint(path)[1] != binding.sha256:
            raise EvidenceError("Collection manifest fingerprint differs from its exact selection.")
        manifest = read_manifest(path)
        if manifest.collection_id != collection.collection_id or manifest.input_roots != collection.input_roots:
            raise EvidenceError("Collection manifest identity or input roots differ from its exact selection.")
        if binding.path in {artifact.path for artifact in manifest.artifacts}:
            raise EvidenceError("Collection manifest cannot also identify a retained artifact.")
        verify_members(root, manifest, manifest_path=binding.path)
        return manifest
    except OSError as error:
        raise EvidenceError("Cannot read the selected collection manifest.") from error
