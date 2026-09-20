"""Provider-owned catalogue source-series description mapping."""

from __future__ import annotations

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_descriptions import generic_source_descriptions
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.engine import ProviderConfig
from rivretrieve._internal.primitives import ProductId


def describe_catalogue(artifact: PackagedCatalogArtifact, *, config: ProviderConfig) -> SourceDescriptions:
    provider = "br_ana"
    if artifact.products.is_empty():
        return SourceDescriptions(provider_id=provider, descriptions=())
    generic = generic_source_descriptions(artifact, config)
    from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, BrAnaSourceCoordinates
    from rivretrieve._internal.providers.br_ana.series import describe_series

    if config is None:
        raise ValueError("ANA descriptions require explicit native source coordinates")
    descriptions = []
    for item in generic.descriptions:
        coordinates = config.products[ProductId(item.product_id)].coordinates.value
        if not isinstance(coordinates, BrAnaDailySourceCoordinates | BrAnaSourceCoordinates):
            raise ValueError("ANA description has invalid native coordinates")
        series = describe_series("catalogue-template", item.product_id, coordinates, origin="catalogue")
        field = coordinates.field_prefix if isinstance(coordinates, BrAnaDailySourceCoordinates) else coordinates.field
        ref = "catalogue:br_ana:" + (
            "source.ana.conventional_daily_definitions"
            if isinstance(coordinates, BrAnaDailySourceCoordinates)
            else "source.ana.adopted_field_units_measurement_time"
        )
        facts = series.facts[0]
        facts = facts.model_copy(
            update={
                name: getattr(facts, name).model_copy(update={"evidence": (ref,)})
                for name in ("quantity", "source_unit", "frequency", "statistic", "timestamp_anchor")
                if getattr(facts, name).evidence
            }
        )
        descriptions.append(
            SourceDescription(
                product_id=item.product_id,
                identity_key=(series.identity.namespace, field, series.identity.published_id),
                native_coordinate=item.native_coordinate,
                identity=series.identity.model_copy(update={"evidence": ("catalogue:br_ana:product.native_id",)}),
                variant=series.variant,
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id=provider, descriptions=tuple(descriptions))
