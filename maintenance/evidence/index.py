"""Validate the reviewed provider inventory and immutable collection locators."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

Text = Annotated[str, Field(min_length=1)]
Positive = Annotated[int, Field(gt=0)]
Nonnegative = Annotated[int, Field(ge=0)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ArtifactRole = Literal[
    "publisher_original", "response_recording", "derived_input", "authored_interpretation",
    "authored_declaration", "research_context", "runtime_product", "acquisition_receipt",
]


class EvidenceError(ValueError):
    """Evidence cannot be used safely; the message excludes private response content."""


def safe_name(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", value) or value.endswith("."):
        raise ValueError("expected a plain portable name")
    return value


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Asset(Record):
    """Pinned compressed bytes and exact extraction limits.

    ``member_count`` includes explicit directories. ``extracted_byte_size`` is
    the sum of regular-file sizes, in bytes. No archive paths are published here.
    """

    asset_id: Positive
    name: Text
    byte_size: Annotated[int, Field(gt=0, lt=2**31)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    archive_format: Literal["tar.gz", "tar.xz", "zip"]
    extracted_byte_size: Nonnegative
    member_count: Positive

    _name = field_validator("name")(safe_name)

    @model_validator(mode="after")
    def archive_suffix(self) -> Self:
        if not self.name.endswith("." + self.archive_format):
            raise ValueError("asset name and archive format differ")
        return self


class ManifestBinding(Record):
    path: Text
    sha256: Digest

    @field_validator("path")
    @classmethod
    def member_path(cls, value: str) -> str:
        for part in value.split("/"):
            safe_name(part)
        return value


class Collection(Record):
    collection_id: Text
    release_id: Positive
    release_tag: Text
    input_roots: dict[Text, Text]
    manifest: ManifestBinding | None
    assets: Annotated[list[Asset], Field(min_length=1, max_length=1000)]
    purpose: Text
    limitations: list[Text]

    _identity = field_validator("collection_id")(safe_name)

    @field_validator("input_roots")
    @classmethod
    def relative_roots(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("explicit input roots required")
        for name, root in value.items():
            safe_name(name)
            if root != ".":
                for part in root.split("/"):
                    safe_name(part)
        return value

    @field_validator("release_tag")
    @classmethod
    def exact_tag(cls, value: str) -> str:
        if value.strip() != value or value.lower() == "latest" or any(ord(c) < 32 for c in value):
            raise ValueError("an exact release tag is required")
        return value

    @model_validator(mode="after")
    def unique_assets(self) -> Self:
        if len({a.asset_id for a in self.assets}) != len(self.assets):
            raise ValueError("duplicate asset identity")
        if len({a.name.casefold() for a in self.assets}) != len(self.assets):
            raise ValueError("duplicate asset name")
        return self


class Material(Record):
    """A safe location-level account; mixed locations require artifact-level review."""

    roles: list[ArtifactRole]
    classification: Literal["unreviewed", "mixed", "reviewed"]
    purpose: Text
    location: Text
    access: Text
    integrity: Text
    limitations: list[Text]


class Verification(Record):
    """A readable maintainer command; acquisition never executes this text."""

    command: Text
    purpose: Text
    requires_collections: list[Text]
    limitations: list[Text]


class ProviderEvidence(Record):
    provider_id: Text
    materials: Annotated[list[Material], Field(min_length=1)]
    verification: Annotated[list[Verification], Field(min_length=1)]
    gaps: list[Text]
    collections: list[Text]


class EvidenceIndex(Record):
    schema_version: Literal[2]
    repository: Literal["RivRetrieve/verification-evidence"]
    providers: list[ProviderEvidence]
    collections: list[Collection]

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema version must be an integer")
        return value

    @model_validator(mode="after")
    def references(self) -> Self:
        ids = [p.provider_id for p in self.providers]
        if len(set(ids)) != len(ids) or set(ids) != set(BUILTIN_PROVIDER_IDS):
            raise ValueError("provider inventory must match the complete built-in registry")
        collections = {c.collection_id: c for c in self.collections}
        if len(collections) != len(self.collections):
            raise ValueError("duplicate collection identity")
        assets: set[int] = set()
        releases: dict[int, str] = {}
        for collection in self.collections:
            if collection.release_id in releases and releases[collection.release_id] != collection.release_tag:
                raise ValueError("release identity has conflicting tags")
            releases[collection.release_id] = collection.release_tag
            for asset in collection.assets:
                if asset.asset_id in assets:
                    raise ValueError("asset belongs to more than one collection; share the collection instead")
                assets.add(asset.asset_id)
        used: set[str] = set()
        for provider in self.providers:
            refs = provider.collections
            if len(set(refs)) != len(refs) or not set(refs) <= collections.keys():
                raise ValueError("invalid provider collection references")
            used.update(refs)
            for check in provider.verification:
                needed = check.requires_collections
                if len(set(needed)) != len(needed) or not set(needed) <= set(refs):
                    raise ValueError("invalid verification collection references")
        if used != collections.keys():
            raise ValueError("collection has no provider")
        return self


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("Index contains duplicate JSON keys; correct the reviewed index.")
        result[key] = value
    return result


def read_index(path: Path) -> EvidenceIndex:
    """Read strict JSON metadata without echoing invalid inputs in errors."""
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=_unique_keys)
        return EvidenceIndex.model_validate(value)
    except (OSError, ValueError, ValidationError) as error:
        raise EvidenceError("Invalid evidence index; check its schema, identities and references.") from error
