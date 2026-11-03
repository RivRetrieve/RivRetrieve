"""Publisher field definitions for BoM catalogue-only discovery."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.providers.au_bom.generate_catalogue import PRODUCT_DEFINITIONS
from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, known

EVIDENCE = "https://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices&request=getrequestinfo&format=html&desc=getall"

_BY_PRODUCT_ID = {d.product_id: d for d in PRODUCT_DEFINITIONS}


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    descriptions = []
    for row in artifact.products.iter_rows(named=True):
        product_id = row["product_id"]
        definition = _BY_PRODUCT_ID[product_id]
        facts = PhysicalFacts(
            facts_id=product_id,
            quantity=known(definition.quantity, EVIDENCE),
            source_unit=known(row["unit"], EVIDENCE),
            normalized_unit=row["unit"],
            frequency=known(definition.frequency, EVIDENCE),
            statistic=known(definition.statistic, EVIDENCE),
        )
        descriptions.append(
            SourceDescription(
                product_id=product_id,
                native_coordinate=row["native_id"],
                identity=SourceIdentity(
                    namespace=f"au_bom/{definition.timeseries_list_kind}",
                    origin="response",
                    description=(
                        f"KiWIS getTimeseriesList, parametertype_name filter for {definition.observed_property}, "
                        f"ts_name={definition.native_id}"
                    ),
                    evidence=(EVIDENCE,),
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id="au_bom", descriptions=tuple(descriptions))
