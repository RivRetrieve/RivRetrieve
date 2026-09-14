"""catalogue provider terms : CatalogueEvidence → VerbatimLicenseAndCitation (pure)."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.acquisition_provenance import verified_source_terms
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.issues import FatalContractError


def verified_catalogue_terms(evidence: CatalogueEvidence) -> dict[str, str]:
    """Resolve only canonical provider-field lineage, never unrelated issuer words."""
    terms: dict[str, str] = {}
    withheld = {fact for group in evidence.header.withheld_facts for fact in group.facts}
    for kind in ("license", "citation"):
        fact = f"provider.{kind}"
        if fact in withheld:
            continue
        outputs = (
            evidence.facts.filter(pl.col("name") == fact)
            .select("fact_id")
            .join(evidence.binding_facts, on="fact_id")
            .join(evidence.bindings, on="binding_id")
        )
        if outputs.is_empty():
            continue
        if outputs.height != 1:
            raise FatalContractError(f"Multiple bindings for {fact}")
        transformation_id = outputs["transformation_id"].item()
        if transformation_id is None:
            continue
        transformation = evidence.header.transformations[transformation_id]
        if transformation.kind != "derived_value":
            continue
        source_ordinals = set(
            evidence.external_inputs.filter(pl.col("binding_id") == outputs["binding_id"].item())[
                "source_ordinal"
            ].drop_nulls()
        )
        sources = tuple(
            source for ordinal, source in enumerate(evidence.header.source_records) if ordinal in source_ordinals
        )
        value = verified_source_terms(sources).get(kind)
        if value is not None:
            terms[kind] = value
    return terms
