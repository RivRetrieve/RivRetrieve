"""Canada catalogue claims follow the explicit compiled-store path."""

from datetime import date

from rivretrieve._internal.providers.ca_eccc.generate_catalogue import build_provider_info


def test_provider_metadata_describes_explicit_compilation():
    description = build_provider_info(date(2026, 9, 20))["bulk_observations"]
    assert "explicit" in description
    assert "first use" not in description
    assert "SQL query" not in description


def test_catalogue_and_compiler_share_station_independent_publisher_facts():
    from rivretrieve._internal.providers.ca_eccc.series import source_description, source_series
    from rivretrieve._internal.source_series import EvidenceState

    for product, namespace, unit in (
        ("discharge_daily_mean", "hydat:DLY_FLOWS", "m3/s"),
        ("stage_daily_mean", "hydat:DLY_LEVELS", "m"),
    ):
        description = source_description(product)
        concrete = source_series("07HF001", product)
        assert concrete.identity == description.identity
        assert concrete.facts == description.facts
        assert description.identity.namespace == namespace
        assert description.identity.published_id is None
        facts = description.facts[0]
        assert facts.source_unit.value == unit
        assert facts.frequency.value == "daily"
        assert facts.statistic.value == "mean"
        assert "HYDAT_Definition_EN.pdf" in facts.quantity.evidence[0]
        for fact in (facts.day_definition, facts.time_zone, facts.vertical_reference, facts.vertical_datum):
            assert fact.state is not EvidenceState.KNOWN


def test_generated_products_use_authoritative_hydat_table_coordinates():
    import polars as pl
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.providers.ca_eccc.generate_catalogue import build_products

    assert_frame_equal(
        build_products().select("product_id", "native_id"),
        pl.DataFrame(
            {
                "product_id": ["discharge_daily_mean", "stage_daily_mean"],
                "native_id": ["DLY_FLOWS", "DLY_LEVELS"],
            }
        ),
    )


def test_public_daily_mean_filter_preserves_established_interval_support():
    import rivretrieve as rr

    broad = rr.find(provider="ca_eccc", station="02GA010", quantity="discharge", frequency="daily", statistic="mean")
    interval = rr.pick(broad, temporal_support="interval", on_issue="ignore")
    assert interval.series == broad.series
    assert broad.series
    facts = interval.series[0].facts[0]
    assert facts.day_definition.value is None
    assert facts.timestamp_anchor.value is None
    assert facts.time_zone.value is None
