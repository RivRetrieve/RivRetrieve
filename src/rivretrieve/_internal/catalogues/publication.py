"""catalogue metadata : AcquisitionProvenance × OriginDeclarations × CatalogueFiles → MetadataFiles (pure)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from io import BytesIO

import polars as pl

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogue_origins import OriginDeclarations
from rivretrieve._internal.catalogues.descriptor import build_catalogue_descriptor
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence, normalize_provenance
from rivretrieve._internal.catalogues.evidence_encoding import encode_catalogue_evidence


def build_catalogue_metadata(
    provenance: AcquisitionProvenance | CatalogueEvidence,
    origins: Sequence[OriginDeclarations],
    files: Mapping[str, bytes],
) -> dict[str, bytes]:
    """Encode one normalized public evidence representation and its bounded descriptor."""
    evidence = (
        normalize_provenance(
            provenance,
            stations=pl.read_parquet(BytesIO(files["stations.parquet"])),
            station_products=pl.read_parquet(BytesIO(files["station_products.parquet"])),
        )
        if isinstance(provenance, AcquisitionProvenance)
        else provenance
    )
    metadata = encode_catalogue_evidence(evidence)
    descriptor = build_catalogue_descriptor(evidence, origins, {**files, **metadata})
    metadata["croissant.json"] = (json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return metadata
