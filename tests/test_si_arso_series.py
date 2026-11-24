"""Verify Slovenia ARSO source-series identity, units, and deferred column tables."""

from __future__ import annotations

from rivretrieve._internal.providers.si_arso import series


def test_si_arso_product_specs_and_series_identities() -> None:
    assert len(series.PRODUCT_SPECS) == 18
    assert len({spec.product_id for spec in series.PRODUCT_SPECS}) == 18

    q_daily = series.source_series("1060", "archive_discharge_daily")
    assert q_daily.identity.namespace == "arso.hidarhiv.oddo"
    assert q_daily.identity.published_id == "pretok (m3/s)"
    assert q_daily.facts[0].quantity.value == "discharge"
    assert q_daily.facts[0].frequency.value == "P1D"
    assert q_daily.facts[0].source_unit.value == "m3/s"
    assert q_daily.facts[0].normalized_unit == "m3/s"

    h_max = series.source_series("1060", "archive_stage_monthly_max")
    assert h_max.identity.namespace == "arso.hidarhiv.eks"
    assert h_max.identity.published_id == "H_MAX"
    assert h_max.facts[0].frequency.value == "P1M"
    assert h_max.facts[0].source_unit.value == "cm"
    assert h_max.facts[0].vertical_reference.value == "gauge_zero"

    t_10 = series.source_series("1060", "operational_temperature_10min")
    assert t_10.identity.namespace == "arso.amp.t_1"
    assert t_10.facts[0].frequency.value == "PT10M"
    assert t_10.facts[0].time_zone.value == "UTC+01:00"
    assert t_10.facts[0].source_unit.value == "°C"
    assert t_10.facts[0].normalized_unit == "degC"

    assert series.source_series("1260", "operational_discharge_10min").facts[0].frequency.value == "PT5M"
    assert series.source_series("3900", "operational_discharge_10min").facts[0].frequency.value == "PT30M"
    assert series.source_series("1060", "operational_discharge_30min").facts[0].frequency.value == "PT30M"
    assert series.source_series("1060", "operational_discharge_hourly").facts[0].frequency.value == "PT1H"
    assert series.route_product_facts("operational_discharge_10min").frequency.state == "not_established"
    assert series.route_product_facts("operational_discharge_10min").frequency.value is None


def test_si_arso_deferred_columns_and_prefixes() -> None:
    assert "vsebnost suspendiranega materiala (g/m3)" in series.DEFERRED_ODDO_COLUMNS
    assert "Vs.S.M." in series.DEFERRED_EKS_PREFIXES
    assert "kZ" in series.DEFERRED_EKS_PREFIXES
    assert "S.El.P." in series.DEFERRED_EKS_PREFIXES
    assert "Elektroprevodnost vode [uS]" in series.DEFERRED_AMP_COLUMNS
