"""Provider-owned catalogue source-series description mapping."""

from __future__ import annotations

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.providers.ca_eccc.bulk import source_series


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    descriptions = []
    for product in artifact.products["product_id"]:
        cell = source_series("catalogue-template", product)
        descriptions.append(
            SourceDescription(
                product_id=product,
                native_coordinate=cell.identity.namespace.partition(":")[2],
                identity_key=(cell.identity.namespace, cell.identity.published_id),
                identity=cell.identity,
                facts=cell.facts,
            )
        )
    return SourceDescriptions(provider_id="ca_eccc", descriptions=tuple(descriptions))
