"""Canonical products cannot establish anchors absent from source facts."""

from importlib import import_module

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact


@pytest.mark.parametrize("provider", ["ca_eccc", "pl_imgw", "za_dws"])
@pytest.mark.parametrize("representation", ["generator", "packaged"])
def test_unknown_source_anchor_remains_unknown_in_canonical_products(provider, representation):
    declaration = import_module(f"rivretrieve._internal.providers.{provider}.declaration").declaration
    artifact = load_packaged_catalogue_artifact(declaration.catalogue)
    assert artifact.source_descriptions is not None
    descriptions = artifact.source_descriptions.descriptions
    assert all(facts.timestamp_anchor.value is None for item in descriptions for facts in item.facts)
    products = (
        import_module(f"rivretrieve._internal.providers.{provider}.generate_catalogue").build_products()
        if representation == "generator"
        else artifact.products
    )
    actual = products.select("product_id", "period_anchor").sort("product_id")
    expected = actual.with_columns(pl.lit("unknown").alias("period_anchor"))
    assert_frame_equal(actual, expected)
