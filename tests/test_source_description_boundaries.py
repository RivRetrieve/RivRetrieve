"""Source description boundaries do not infer facts or bypass explicit mappings."""

from pathlib import Path

import pytest


def test_explicit_mapping_set_cannot_fall_back_to_product_table_claims():
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.source_descriptions import build_source_descriptions
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.lt_lhmt.config import SERIES_MAPPINGS, config

    artifact = load_packaged_catalogue_artifact(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/lt_lhmt/catalogue"
    )
    with pytest.raises(FatalContractError, match="explicit source mapping"):
        build_source_descriptions(
            artifact, config(), mappings={"stage_daily_mean": SERIES_MAPPINGS["stage_daily_mean"]}
        )


def test_withheld_catalogue_fact_cannot_be_reinstated_by_mapping():
    from dataclasses import replace

    from rivretrieve._internal.acquisition_provenance import WithheldFact
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.source_descriptions import build_source_descriptions
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.lt_lhmt.config import SERIES_MAPPINGS, config

    artifact = load_packaged_catalogue_artifact(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/lt_lhmt/catalogue"
    )
    evidence = artifact.acquisition_provenance
    withheld = WithheldFact(
        fact_group="unestablished_period", facts=("product.period_type",), reason="no_acquisition_record_established"
    )
    changed = replace(
        artifact,
        acquisition_provenance=evidence.model_copy(
            update={"header": evidence.header.model_copy(update={"withheld_facts": (withheld,)})}
        ),
    )
    with pytest.raises(FatalContractError, match="withheld"):
        build_source_descriptions(changed, config(), mappings=SERIES_MAPPINGS)


def test_generic_daily_label_does_not_establish_interval_anchor():
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.source_descriptions import build_source_descriptions
    from rivretrieve._internal.providers.lt_lhmt.config import config

    artifact = load_packaged_catalogue_artifact(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/lt_lhmt/catalogue"
    )
    descriptions = build_source_descriptions(artifact, config())
    for description in descriptions.descriptions:
        for facts in description.facts:
            assert facts.timestamp_anchor.value is None
            assert facts.day_definition.value is None
            assert facts.label_time == "00:00"


def test_independent_publisher_definitions_do_not_infer_from_unknown_product_cells():
    from dataclasses import replace

    import polars as pl

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.source_descriptions import build_source_descriptions
    from rivretrieve._internal.providers.lt_lhmt.config import SERIES_MAPPINGS, config

    artifact = load_packaged_catalogue_artifact(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/lt_lhmt/catalogue"
    )
    products = artifact.products.with_columns(
        pl.lit("unknown").alias(name) for name in ("frequency", "statistic", "period_type", "period_anchor")
    )
    descriptions = build_source_descriptions(replace(artifact, products=products), config(), mappings=SERIES_MAPPINGS)
    # The exact historical API documentation, not the unspecified table cells,
    # independently establishes daily means. It still establishes no interval anchor.
    for description in descriptions.descriptions:
        facts = description.facts[0]
        assert facts == SERIES_MAPPINGS[description.product_id].physical_facts()
        assert facts.frequency.value == "daily"
        assert facts.statistic.value == "mean"
        assert facts.timestamp_anchor.value is None
        assert any("lt_lhmt_terms_licence.html" in ref for ref in facts.statistic.evidence)


def test_instantaneous_physical_support_projects_to_existing_product_vocabulary():
    from dataclasses import replace

    from rivretrieve._internal.catalogues.products import product_row
    from rivretrieve._internal.providers.fr_hydroportail.config import SERIES_MAPPINGS

    # The retained HydroPortail title establishes instantaneous, the same physical
    # predicate used by USGS. Product tables use their existing distinct enum.
    mapping = replace(SERIES_MAPPINGS["discharge_instantaneous"], temporal_support="instantaneous")
    row = product_row("fr_hydroportail", "discharge_instantaneous", "Q", mapping.physical_facts())
    assert row["period_type"] == "instant"
    assert mapping.physical_facts().temporal_support.value == "instantaneous"


def test_generic_product_instant_maps_to_physical_instantaneous():
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.source_descriptions import build_source_descriptions
    from rivretrieve._internal.providers.fr_hydroportail.config import config

    artifact = load_packaged_catalogue_artifact(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue"
    )
    descriptions = build_source_descriptions(artifact, config())
    selected = [
        description for description in descriptions.descriptions if description.product_id == "discharge_instantaneous"
    ]
    assert selected[0].facts[0].temporal_support.value == "instantaneous"
