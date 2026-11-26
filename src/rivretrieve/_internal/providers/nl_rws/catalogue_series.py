"""Publisher field definitions for nl_rws catalogue-only discovery."""

from __future__ import annotations

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.providers.nl_rws.series import (
    ADMITTED_PRODUCT_KEY_TO_ID,
    CATALOGUS_EVIDENCE,
    PRODUCT_BY_ID,
    PRODUCT_DEFINITIONS,
    ProductDefinition,
    build_physical_facts,
)
from rivretrieve._internal.source_series import SourceIdentity

__all__ = [
    "ADMITTED_PRODUCT_KEY_TO_ID",
    "PRODUCT_BY_ID",
    "PRODUCT_DEFINITIONS",
    "ProductDefinition",
    "describe_catalogue",
]


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    """Build catalogue-tier source descriptions for nl_rws offline discovery.

    Catalogue metadata carries no ``Tijdstip`` offsets, so ``time_zone`` stays
    ``not_established`` here; runtime responses establish explicit offsets in
    ``series.py``. Unestablished product semantics (NVT cadence/statistic,
    GEM24H day anchor, and PLAATSLR vertical-reference category) remain
    ``not_established``.
    """
    descriptions: list[SourceDescription] = []
    for row in artifact.products.iter_rows(named=True):
        product_id = str(row["product_id"])
        definition = PRODUCT_BY_ID[product_id]
        facts = build_physical_facts(definition, time_zone_offset=None, facts_id=product_id)
        descriptions.append(
            SourceDescription(
                product_id=product_id,
                native_coordinate=row["native_id"],
                identity=SourceIdentity(
                    namespace=f"nl_rws/{product_id}",
                    origin="catalogue",
                    description=(
                        "Rijkswaterstaat DDAPI 2.0 AquoMetadata physical/aggregation product "
                        "(Compartiment=OW, ProcesType=meting, Groepering=''); distinct "
                        "WaardeBepalingsMethode series are separated at retrieval/parse time"
                    ),
                    evidence=(CATALOGUS_EVIDENCE,),
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id="nl_rws", descriptions=tuple(descriptions))
