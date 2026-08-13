"""store validation surface : StoreRoot × ProviderId → ValidatedStore ⊎ StoreRefusal."""

from rivretrieve._internal.store.validation import (
    ArtifactChecksum,
    Disposition,
    ObservationStoreRefusedError,
    PartitionIdentifier,
    PublisherArtifact,
    SourceColumn,
    SourceColumnDisposition,
    SourceSchema,
    SourceSchemaFingerprint,
    StoreManifest,
    StoreRefusal,
    StoreRefusalKind,
    StoreRoot,
    ValidatedStore,
    validate_store,
)

__all__ = [
    "ArtifactChecksum",
    "Disposition",
    "ObservationStoreRefusedError",
    "PartitionIdentifier",
    "PublisherArtifact",
    "SourceColumn",
    "SourceColumnDisposition",
    "SourceSchema",
    "SourceSchemaFingerprint",
    "StoreManifest",
    "StoreRefusal",
    "StoreRefusalKind",
    "StoreRoot",
    "ValidatedStore",
    "validate_store",
]
