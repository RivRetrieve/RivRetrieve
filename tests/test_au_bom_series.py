"""Unit tests for au_bom's series identity and physical-fact evidence."""

from __future__ import annotations

import pytest

from rivretrieve._internal.providers.au_bom.series import describe_series
from rivretrieve._internal.source_series import admission


@pytest.mark.parametrize(
    ("product_id", "unit_symbol", "expected_target_unit", "expected_quantity", "expected_variant"),
    [
        ("discharge_daily_mean_24hr", "cumec", "m3/s", "discharge", "24hr"),
        ("discharge_hourly_mean", "cumec", "m3/s", "discharge", None),
        ("stage_daily_mean", "m", "m", "stage", None),
        ("water_temperature_daily_mean", "°C", "degC", "temperature", None),
    ],
)
def test_describe_series_is_admitted_with_no_conversion_factor(
    product_id: str, unit_symbol: str, expected_target_unit: str, expected_quantity: str, expected_variant: str | None
) -> None:
    series = describe_series("410730", "1573010", product_id, unit_symbol)
    assert series.provider_id == "au_bom"
    assert series.station_id == "410730"
    assert series.product_id == product_id
    assert series.variant == expected_variant
    assert series.identity.namespace == "KiWIS.ts_id"
    assert series.identity.published_id == "1573010"

    facts = series.facts[0]
    assert facts.quantity.value == expected_quantity
    assert facts.time_zone.value == "+10:00"

    result = admission(facts)
    assert result.status == "supported"
    assert result.target_unit == expected_target_unit
    assert result.factor == 1.0


def test_duplicate_ts_id_produces_distinct_series_id_under_the_same_product() -> None:
    """Confirmed live 2026-11-03: some stations have two ts_id for one product; both must surface."""
    first = describe_series("138020A", "470345010", "discharge_daily_mean_24hr", "cumec")
    second = describe_series("138020A", "381776010", "discharge_daily_mean_24hr", "cumec")
    assert first.series_id != second.series_id
    assert first.station_id == second.station_id
    assert first.product_id == second.product_id
    # Both share discharge_daily_mean_24hr's variant ("24hr"); variant distinguishes
    # the 24hr/09hr daily-mean ambiguity, not this separate within-product ts_id duplication.
    assert first.variant == second.variant == "24hr"


def test_same_station_ts_id_product_is_deterministic() -> None:
    first = describe_series("410730", "1573010", "discharge_daily_mean_24hr", "cumec")
    second = describe_series("410730", "1573010", "discharge_daily_mean_24hr", "cumec")
    assert first.series_id == second.series_id


def test_describe_series_rejects_an_unadmitted_product() -> None:
    with pytest.raises(ValueError, match="admitted product_id"):
        describe_series("410730", "1573010", "discharge_daily_mean_bruto", "cumec")


def test_only_daily_frequency_uses_calendar_date_clipping() -> None:
    """CALENDAR_DATE clipping requires established daily frequency (enforced by PhysicalFacts itself)."""
    from rivretrieve._internal.source_series import ClippingAxis

    hourly = describe_series("410730", "1571010", "discharge_hourly_mean", "cumec")
    daily = describe_series("410730", "1573010", "discharge_daily_mean_24hr", "cumec")
    monthly = describe_series("410730", "1574010", "discharge_monthly_mean", "cumec")
    yearly = describe_series("410730", "1575010", "discharge_yearly_mean", "cumec")
    assert hourly.facts[0].clipping_axis == ClippingAxis.SOURCE_TIMESTAMP
    assert daily.facts[0].clipping_axis == ClippingAxis.CALENDAR_DATE
    assert monthly.facts[0].clipping_axis == ClippingAxis.SOURCE_TIMESTAMP
    assert yearly.facts[0].clipping_axis == ClippingAxis.SOURCE_TIMESTAMP


def test_discharge_09hr_has_its_own_variant_and_label_time_distinct_from_24hr() -> None:
    """09hr is a genuinely different daily mean from 24hr, not a less precise version of it."""
    daily_24hr = describe_series("410730", "1573010", "discharge_daily_mean_24hr", "cumec")
    daily_09hr = describe_series("410730", "1572010", "discharge_daily_mean_09hr", "cumec")
    assert daily_24hr.variant == "24hr"
    assert daily_09hr.variant == "09hr"
    assert daily_24hr.facts[0].label_time == "00:00"
    assert daily_09hr.facts[0].label_time == "09:00"


def test_hourly_products_have_no_label_time_or_variant() -> None:
    hourly = describe_series("410730", "1571010", "discharge_hourly_mean", "cumec")
    assert hourly.facts[0].label_time is None
    assert hourly.variant is None


def test_products_outside_the_24hr_09hr_pair_stay_unambiguous() -> None:
    """Every au_bom product other than discharge's two daily means has no sibling to disambiguate."""
    stage = describe_series("410730", "1598010", "stage_daily_mean", "m")
    monthly = describe_series("410730", "1574010", "discharge_monthly_mean", "cumec")
    assert stage.variant is None
    assert stage.facts[0].label_time == "00:00"
    assert monthly.variant is None
    assert monthly.facts[0].label_time == "00:00"


def test_unrecognized_unit_symbol_leaves_normalized_unit_unset() -> None:
    series = describe_series("410730", "1573010", "discharge_daily_mean_24hr", "megalitre per day")
    facts = series.facts[0]
    assert facts.normalized_unit is None
    result = admission(facts)
    assert result.status == "unsupported"
