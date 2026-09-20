"""Provider-owned catalogue source-series description mapping."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.providers.ca_eccc.series import source_description


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    return SourceDescriptions(
        provider_id="ca_eccc",
        descriptions=tuple(source_description(product) for product in artifact.products["product_id"]),
    )
