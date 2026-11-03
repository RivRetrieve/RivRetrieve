"""Unit tests for au_bom's series identity and physical-fact evidence."""

from __future__ import annotations

import pytest

from rivretrieve._internal.providers.au_bom.series import describe_series
from rivretrieve._internal.source_series import admission


@pytest.mark.parametrize(
    ("product_id", "unit_symbol", "expected_target_unit", "expected_quantity"),
    [
        ("discharge_daily_mean_24hr", "cumec", "m3/s", "discharge"),
        ("discharge_hourly_mean", "cumec", "m3/s", "discharge"),
        ("stage_daily_mean", "m", "m", "stage"),
        ("water_temperature_daily_mean", "°C", "degC", "temperature"),
    ],
)
def test_describe_series_is_admitted_with_no_conversion_factor(
    product_id: str, unit_symbol: str, expected_target_unit: str, expected_quantity: str
) -> None:
    series = describe_series("410730", "1573010", product_id, unit_symbol)
    assert series.provider_id == "au_bom"
    assert series.station_id == "410730"
    assert series.product_id == product_id
    assert series.variant is None
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
    assert first.variant is None
    assert second.variant is None


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


def test_unrecognized_unit_symbol_leaves_normalized_unit_unset() -> None:
    series = describe_series("410730", "1573010", "discharge_daily_mean_24hr", "megalitre per day")
    facts = series.facts[0]
    assert facts.normalized_unit is None
    result = admission(facts)
    assert result.status == "unsupported"
