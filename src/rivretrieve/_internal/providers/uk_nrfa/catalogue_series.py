"""NRFA product identity and documented physical quantities for discovery."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, known

PRODUCT_IDS = (
    "gdf",
    "ndf",
    "gmf",
    "nmf",
    "gauging-flow",
    "gauging-stage",
    "amax-flow",
    "amax-stage",
    "pot-flow",
    "pot-stage",
)
API_HELP = "https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html"


def product_facts() -> dict[str, PhysicalFacts]:
    return {
        product: PhysicalFacts(
            facts_id=product,
            quantity=known("stage" if product.endswith("stage") else "discharge", API_HELP),
            source_unit=known("m" if product.endswith("stage") else "m3/s", API_HELP),
            normalized_unit="m" if product.endswith("stage") else "m3/s",
        )
        for product in PRODUCT_IDS
    }


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    facts = product_facts()
    return SourceDescriptions(
        provider_id="uk_nrfa",
        descriptions=tuple(
            SourceDescription(
                product_id=product,
                native_coordinate=product,
                identity=SourceIdentity(
                    namespace="uk_nrfa/data-type",
                    origin="mapping",
                    description="NRFA API data-type; station associations are advertised in data-summary",
                    evidence=(API_HELP,),
                ),
                facts=(facts[product],),
            )
            for product in artifact.products["product_id"]
        ),
    )
