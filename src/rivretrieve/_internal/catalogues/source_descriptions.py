"""Build explicit catalogue descriptions from established facts and declarations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import polars as pl

from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.provider_series import SeriesMapping
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    known,
    stable_id,
)

if TYPE_CHECKING:
    from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
    from rivretrieve._internal.engine import ProviderConfig


def generic_source_descriptions(
    artifact: PackagedCatalogArtifact,
    config: ProviderConfig | None,
    *,
    mappings: Mapping[str, SeriesMapping] | None = None,
) -> SourceDescriptions:
    """Keep existing declared physical meaning; do not classify from product names."""
    from rivretrieve._internal.engine import Daily

    provider = str(artifact.provider_info["provider_id"])
    evidence = artifact.acquisition_provenance
    withheld = set() if evidence is None else {name for group in evidence.header.withheld_facts for name in group.facts}
    absent = set()
    if evidence is not None:
        for index, transform in enumerate(evidence.header.transformations):
            if transform.kind == "absence_marker":
                ids = evidence.bindings.filter(pl.col("transformation_id") == index).select("binding_id")
                absent.update(
                    ids.join(evidence.binding_facts, on="binding_id").join(evidence.facts, on="fact_id")["name"]
                )

    def fact(value: str | None, name: str) -> EvidenceFact:
        ref = f"catalogue:{provider}:{name}"
        if name in withheld or evidence is None:
            return EvidenceFact(evidence=(ref,))
        if value is None or value in ("unknown", "provider_defined"):
            return EvidenceFact(
                state=EvidenceState.SOURCE_SILENT if name in absent else EvidenceState.NOT_ESTABLISHED, evidence=(ref,)
            )
        return known(value, ref)

    result = []
    for row in artifact.products.iter_rows(named=True):
        product = row["product_id"]
        declared = config.products.get(product) if config is not None else None
        mapping = mappings.get(product) if mappings is not None else None
        unit = mapping.source_unit if mapping is not None else declared.unit.value if declared is not None else None
        quantity = row["observed_property"]
        # The catalogue uses the established water_temperature quantity spelling.
        quantity = "temperature" if quantity == "water_temperature" else quantity
        frequency = fact(row["frequency"], "product.frequency")
        daily = frequency.value == "daily"
        day = EvidenceFact()
        anchor = EvidenceFact()
        label = None
        if declared is not None and isinstance(declared.semantics, Daily):
            label = declared.semantics.label_time.value
            anchor = known(label, f"mapping:{provider}:{product}:label_time")
            value = declared.semantics.day_definition.value
            if value != "unknown":
                day = known(value, f"mapping:{provider}:{product}:day_definition")
        zone = config.zone.value if config is not None else "unknown"
        unit_definition = mapping.source_unit_definition if mapping is not None else None
        unit_evidence = () if unit_definition is None else unit_definition.evidence
        facts = PhysicalFacts(
            facts_id=stable_id(provider, product, unit),
            quantity=fact(quantity, "product.observed_property"),
            source_unit=EvidenceFact(
                value=unit,
                state=EvidenceState.KNOWN,
                evidence=(f"mapping:{provider}:{product}:native_unit", *unit_evidence),
            )
            if unit
            else EvidenceFact(),
            source_unit_definition=unit_definition,
            normalized_unit=mapping.normalized_unit if mapping is not None else unit,
            frequency=frequency,
            statistic=fact(row["statistic"], "product.statistic"),
            temporal_support=fact(row["period_type"], "product.period_type"),
            day_definition=day,
            timestamp_anchor=anchor,
            time_zone=known(zone, f"mapping:{provider}:time_zone") if zone != "unknown" else EvidenceFact(),
            clipping_axis=ClippingAxis.CALENDAR_DATE if daily else ClippingAxis.SOURCE_TIMESTAMP,
            label_time=label,
        )
        facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
        result.append(
            SourceDescription(
                product_id=product,
                native_coordinate=row["native_id"],
                identity=SourceIdentity(
                    namespace=mapping.namespace if mapping is not None else f"{provider}/{product}",
                    published_id=mapping.published_id if mapping is not None else None,
                    origin="mapping",
                    evidence=(f"catalogue:{provider}:product.native_id",),
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id=provider, descriptions=tuple(result))


def content_identified_descriptions(descriptions: SourceDescriptions) -> SourceDescriptions:
    """Identify each physical-fact record by its complete content, including evidence."""
    return descriptions.model_copy(
        update={
            "descriptions": tuple(
                item.model_copy(
                    update={
                        "facts": tuple(
                            facts.model_copy(
                                update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))}
                            )
                            for facts in item.facts
                        )
                    }
                )
                for item in descriptions.descriptions
            )
        }
    )


def build_source_descriptions(
    artifact: PackagedCatalogArtifact,
    config: ProviderConfig | None,
    *,
    mappings: Mapping[str, SeriesMapping] | None = None,
) -> SourceDescriptions:
    return content_identified_descriptions(generic_source_descriptions(artifact, config, mappings=mappings))
