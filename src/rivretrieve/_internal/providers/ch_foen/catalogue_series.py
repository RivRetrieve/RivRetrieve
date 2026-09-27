"""Provider-owned catalogue source-series description mapping."""

from __future__ import annotations

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    provider = "ch_foen"
    if artifact.products.is_empty():
        return SourceDescriptions(provider_id=provider, descriptions=())
    from rivretrieve._internal.providers.ch_foen.series import field_series

    descriptions = []
    for field in ("flow", "flow_ls", "height", "height_abs", "temperature"):
        item = field_series("catalogue-template", field, origin="catalogue")
        ref = "catalogue:ch_foen:source.product.native_physics"
        facts = item.facts[0]
        updates = {
            name: getattr(facts, name).model_copy(update={"evidence": (ref,)})
            for name in ("quantity", "source_unit", "vertical_reference")
            if getattr(facts, name).value is not None
        }
        descriptions.append(
            SourceDescription(
                product_id=item.product_id,
                identity_key=("field", field),
                native_coordinate=field,
                identity=item.identity.model_copy(update={"evidence": ("catalogue:ch_foen:source.product.native_id",)}),
                variant=item.variant,
                facts=(facts.model_copy(update=updates),),
            )
        )
    return SourceDescriptions(provider_id=provider, descriptions=tuple(descriptions))
