"""NRFA product identity and documented physical quantities for discovery."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.providers.uk_nrfa.series import (
    API_HELP_URL as API_HELP,
)
from rivretrieve._internal.providers.uk_nrfa.series import (
    PRODUCT_IDS,
    product_facts,
    series_identity,
)


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    facts = product_facts()
    return SourceDescriptions(
        provider_id="uk_nrfa",
        descriptions=tuple(
            SourceDescription(
                product_id=product,
                native_coordinate=product,
                identity=series_identity(
                    product,
                    origin="mapping",
                    description="NRFA API data-type; station associations are advertised in data-summary",
                ),
                facts=(facts[product],),
            )
            for product in artifact.products["product_id"]
        ),
    )


__all__ = ("API_HELP", "PRODUCT_IDS", "describe_catalogue", "product_facts")
