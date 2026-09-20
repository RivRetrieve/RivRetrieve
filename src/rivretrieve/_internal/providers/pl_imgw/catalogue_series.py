"""Provider-owned catalogue source-series description mapping."""

from __future__ import annotations

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.providers.pl_imgw.series import describe_product


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    return SourceDescriptions(
        provider_id="pl_imgw",
        descriptions=tuple(describe_product(product) for product in artifact.products["product_id"]),
    )
