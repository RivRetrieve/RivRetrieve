"""Non-destructive packaging and retained-member equivalence checks."""

from __future__ import annotations

import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from .acquisition import _external_destination
from .archives import ArchivePaths, extract_archive
from .index import ArchiveAsset, Collection, EvidenceError, ManifestBinding, Record, Text, _unique_keys, safe_name
from .manifest import fingerprint, read_manifest, verify_members

MANIFEST_NAME = "collection-manifest.json"
PREPARATION_NAME = "preparation.json"


class PreparedCollection(Record):
    """Private preparation record; no release or acceptance identity is invented."""

    schema_version: Literal[1]
    collection_id: Text
    provider_ids: list[Text]
    input_roots: dict[Text, Text]
    manifest: ManifestBinding
    assets: list[ArchiveAsset] = Field(min_length=1, max_length=1000)

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
    def unique_assets(self) -> Self:
        if len({asset.name.casefold() for asset in self.assets}) != len(self.assets):
            raise ValueError("duplicate prepared asset")
        if self.manifest.path != MANIFEST_NAME:
            raise ValueError("unexpected manifest path")
        return self


def _write_private(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as output:
        path.chmod(0o600)
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _pack(source: Path, destination: Path, names: list[str]) -> ArchiveAsset:
    expanded = 0
    with tarfile.open(destination, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        destination.chmod(0o600)
        for name in names:
            path = source / name
            if path.is_symlink() or not path.is_file():
                raise EvidenceError("Input changed during packaging; retain it and review the preparation.")
            info = tarfile.TarInfo(name)
            info.size = path.stat().st_size
            info.mode = 0o600
            with path.open("rb") as body:
                archive.addfile(info, body)
            expanded += info.size
    size, digest = fingerprint(destination)
    return ArchiveAsset(
        name=destination.name,
        byte_size=size,
        sha256=digest,
        archive_format="tar.gz",
        extracted_byte_size=expanded,
        member_count=len(names),
    )


def check_prepared(prepared: Path, staging: Path) -> PreparedCollection:
    """Recheck every packaged asset and retained member without publishing anything.

    ``staging`` must be a new empty private directory. All compressed assets pass
    fingerprints before extraction. This establishes packaging equivalence only.
    """
    try:
        record = PreparedCollection.model_validate(
            json.loads((prepared / PREPARATION_NAME).read_bytes(), object_pairs_hook=_unique_keys)
        )
        expected = {PREPARATION_NAME, *(asset.name for asset in record.assets)}
        if prepared.is_symlink() or {path.name for path in prepared.iterdir()} != expected:
            raise EvidenceError("Prepared collection has unexpected files.")
        for name in expected:
            path = prepared / name
            if path.is_symlink() or not path.is_file():
                raise EvidenceError("Prepared collection contains a link or special file.")
        for asset in record.assets:
            if fingerprint(prepared / asset.name) != (asset.byte_size, asset.sha256):
                raise EvidenceError("Prepared asset fingerprint differs from its preparation record.")
        paths = ArchivePaths()
        for asset in record.assets:
            extract_archive(prepared / asset.name, asset, staging, paths)
        manifest_file = staging / record.manifest.path
        if fingerprint(manifest_file)[1] != record.manifest.sha256:
            raise EvidenceError("Prepared manifest fingerprint differs from its preparation record.")
        manifest = read_manifest(manifest_file)
        if (
            manifest.collection_id != record.collection_id
            or manifest.provider_ids != record.provider_ids
            or manifest.input_roots != record.input_roots
            or record.manifest.path in {artifact.path for artifact in manifest.artifacts}
        ):
            raise EvidenceError("Prepared manifest identity differs from its preparation record.")
        verify_members(staging, manifest, manifest_path=record.manifest.path)
        return record
    except (OSError, ValueError, tarfile.TarError):
        raise EvidenceError("Prepared collection failed integrity or manifest validation.") from None


def prepare_collection(
    manifest_path: Path,
    source: Path,
    destination: Path,
    *,
    source_roots: tuple[Path, ...],
    max_asset_bytes: int = 256 * 1024 * 1024,
) -> Path:
    """Inventory supplied files and publish a new immutable-selection-ready package.

    Source files are read, never changed or deleted. The private manifest must
    describe every file. Packaging is split at file boundaries using an expanded
    byte target; each compressed asset must still fit GitHub's 2 GiB limit.
    The returned directory contains a private preparation record and archives.
    """
    try:
        if max_asset_bytes <= 0:
            raise EvidenceError("A positive packaging byte target is required.")
        manifest = read_manifest(manifest_path)
        if MANIFEST_NAME in {artifact.path for artifact in manifest.artifacts}:
            raise EvidenceError("The reserved collection manifest path collides with a retained artifact.")
        root = _external_destination(destination, source_roots)
        source = source.expanduser().absolute()
        if root.is_relative_to(source.resolve()) or source.resolve().is_relative_to(root):
            raise EvidenceError("Preparation destination must be separate from its retained source directory.")
        verify_members(source, manifest)
        target = root / manifest.collection_id
        if target.exists() or target.is_symlink():
            raise EvidenceError("Preparation destination already exists; existing bytes were not changed.")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix=".intake-", dir=root) as temporary:
            staging = Path(temporary)
            package = staging / "package"
            package.mkdir(mode=0o700)
            metadata = staging / "metadata"
            metadata.mkdir(mode=0o700)
            _write_private(metadata / MANIFEST_NAME, manifest.model_dump(mode="json"))
            assets = [_pack(metadata, package / "manifest.tar.gz", [MANIFEST_NAME])]
            names: list[str] = []
            expanded = 0
            for artifact in manifest.artifacts:
                if names and expanded + artifact.byte_size > max_asset_bytes:
                    assets.append(_pack(source, package / f"members-{len(assets):04d}.tar.gz", names))
                    names, expanded = [], 0
                names.append(artifact.path)
                expanded += artifact.byte_size
            if names:
                assets.append(_pack(source, package / f"members-{len(assets):04d}.tar.gz", names))
            record = PreparedCollection(
                schema_version=1,
                collection_id=manifest.collection_id,
                provider_ids=manifest.provider_ids,
                input_roots=manifest.input_roots,
                manifest=ManifestBinding(path=MANIFEST_NAME, sha256=fingerprint(metadata / MANIFEST_NAME)[1]),
                assets=assets,
            )
            _write_private(package / PREPARATION_NAME, record.model_dump(mode="json"))
            extracted = staging / "verified"
            extracted.mkdir(mode=0o700)
            check_prepared(package, extracted)
            # Reserve the final name atomically; an existing collection is never replaced.
            target.mkdir(mode=0o700)
            try:
                os.replace(package, target)
            except OSError:
                target.rmdir()
                raise
        return target
    except EvidenceError:
        raise
    except (OSError, ValueError, tarfile.TarError):
        raise EvidenceError("Collection intake failed; retained source files were not changed.") from None
