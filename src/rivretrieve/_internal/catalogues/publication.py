"""catalogue metadata : AcquisitionProvenance × OriginDeclarations × CatalogueFiles → MetadataFiles (pure)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
    from rivretrieve._internal.engine import ProviderConfig
    from rivretrieve._internal.provider_series import SeriesMapping

import polars as pl

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogue_origins import OriginDeclarations
from rivretrieve._internal.catalogues.descriptor import build_catalogue_descriptor
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence, normalize_provenance
from rivretrieve._internal.catalogues.evidence_encoding import encode_catalogue_evidence
from rivretrieve._internal.catalogues.schemas import CATALOGUE_SERIES_CLAIMS_SCHEMA
from rivretrieve._internal.catalogues.source_series import SourceDescriptions


def build_catalogue_metadata(
    provenance: AcquisitionProvenance | CatalogueEvidence,
    origins: Sequence[OriginDeclarations],
    files: Mapping[str, bytes],
    *,
    source_descriptions: SourceDescriptions | None = None,
    source_config: ProviderConfig | None = None,
    source_describer: Callable[[PackagedCatalogArtifact], SourceDescriptions] | None = None,
    source_mappings: Mapping[str, SeriesMapping] | None = None,
    catalogue_claims: pl.DataFrame | None = None,
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
    if source_descriptions is None:
        from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
        from rivretrieve._internal.catalogues.source_descriptions import (
            build_source_descriptions,
            content_identified_descriptions,
        )

        artifact = packaged_catalogue_artifact_from_components(
            json.loads(files["provider.json"]),
            pl.read_parquet(BytesIO(files["products.parquet"])),
            pl.read_parquet(BytesIO(files["stations.parquet"])),
            pl.read_parquet(BytesIO(files["station_products.parquet"])),
            acquisition_provenance=evidence,
            withheld_rows_already_applied=True,
        )
        if source_describer is not None:
            source_descriptions = content_identified_descriptions(source_describer(artifact))
        else:
            if artifact.products.height and source_config is None:
                raise ValueError("Catalogue publication requires explicit source_config or source_describer")
            source_descriptions = build_source_descriptions(artifact, source_config, mappings=source_mappings)
    if source_descriptions.provider_id != evidence.header.provider_id:
        raise ValueError("Source descriptions provider does not match catalogue evidence")
    metadata["source_series.json"] = (source_descriptions.model_dump_json() + "\n").encode()
    metadata["format.json"] = b'{"catalogue_format_version":2}\n'
    claims = (
        catalogue_claims
        if catalogue_claims is not None
        else pl.DataFrame(schema=CATALOGUE_SERIES_CLAIMS_SCHEMA.polars_schema)
    )
    buffer = BytesIO()
    claims.write_parquet(buffer, compression="zstd", statistics=True)
    metadata["series_claims.parquet"] = buffer.getvalue()
    descriptor = build_catalogue_descriptor(evidence, origins, {**files, **metadata})
    metadata["croissant.json"] = (json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return metadata
