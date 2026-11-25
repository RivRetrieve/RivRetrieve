"""Source-series catalogue descriptions for Chile DGA historical discharge."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.providers.cl_dga.series import SERIES_MAPPINGS


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    """Describe packaged Chile DGA historical products using established physical facts."""
    descriptions = []
    for row in artifact.products.iter_rows(named=True):
        product_id = row["product_id"]
        mapping = SERIES_MAPPINGS[product_id]
        descriptions.append(
            SourceDescription(
                product_id=product_id,
                native_coordinate=row["native_id"],
                identity=mapping.identity(),
                facts=(mapping.physical_facts(),),
            )
        )
    return SourceDescriptions(provider_id="cl_dga", descriptions=tuple(descriptions))
