"""Source-independent tests for Belgium - Wallonia (`be_wal`) Step 3 series meaning and annotations."""

from __future__ import annotations

from datetime import datetime

import pytest

from rivretrieve._internal.physical_window import native_window
from rivretrieve._internal.providers.be_wal.annotations import (
    BE_WAL_QUALITY_CODES_URL,
    BE_WAL_QUALITY_SCHEMA,
    QUALITY_CODES,
)
from rivretrieve._internal.providers.be_wal.series import (
    KIWIS_NAMESPACE,
    PRODUCT_BY_ID,
    PRODUCT_SPECS,
    catalogue_product_rows,
)
from rivretrieve._internal.source_annotations import AnnotationScope
from rivretrieve._internal.source_series import ClippingAxis, EvidenceState, admission


def test_be_wal_quality_annotation_schema() -> None:
    assert BE_WAL_QUALITY_SCHEMA.schema_id == "be_wal.quality"
    assert BE_WAL_QUALITY_SCHEMA.provider_id == "be_wal"
    assert BE_WAL_QUALITY_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [(field.name, field.dtype) for field in BE_WAL_QUALITY_SCHEMA.fields] == [
        ("quality_code", "Int64"),
        ("quality_code_name", "String"),
    ]
    assert all(field.reference_url == BE_WAL_QUALITY_CODES_URL for field in BE_WAL_QUALITY_SCHEMA.fields)
    assert set(QUALITY_CODES) == {0, 40, 80, 120, 160, 161, 162, 163, 165, 200, 205, 210, 253}


def test_all_62_products_satisfy_step3_physical_contracts_and_cet_windowing() -> None:
    assert len(PRODUCT_SPECS) == 62
    assert len(PRODUCT_BY_ID) == 62
    rows = {row["product_id"]: row for row in catalogue_product_rows()}
    assert len(rows) == 62

    for spec in PRODUCT_SPECS:
        mapping = spec.series_mapping(published_id="297314010")
        assert mapping.namespace == KIWIS_NAMESPACE
        facts = mapping.physical_facts()
        dec = admission(facts)
        assert dec.status == "supported"
        assert facts.time_zone.state is EvidenceState.KNOWN
        assert facts.time_zone.value == "+01:00"

        if spec.quantity == "discharge":
            assert facts.source_unit.value == "m³/s"
            assert dec.target_unit == "m3/s"
            assert dec.factor == pytest.approx(1.0)
            assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
            assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
        elif spec.quantity == "temperature":
            assert facts.source_unit.value == "°C"
            assert dec.target_unit == "degC"
            assert dec.factor == pytest.approx(1.0)
            assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
            assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
        else:
            assert facts.source_unit.value == "m"
            assert dec.target_unit == "m"
            assert dec.factor == pytest.approx(1.0)
            expected_ref = "above_sea_level" if spec.family == "stage_absolute" else "gauge_zero"
            assert facts.vertical_reference.state is EvidenceState.KNOWN
            assert facts.vertical_reference.value == expected_ref
            assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
            assert facts.vertical_datum.value is None

        cat_row = rows[spec.product_id]
        assert cat_row["unit"] == dec.target_unit
        if spec.frequency is None:
            assert facts.frequency.state is EvidenceState.NOT_ESTABLISHED
            assert facts.statistic.state is EvidenceState.NOT_ESTABLISHED
            assert facts.temporal_support.state is EvidenceState.NOT_ESTABLISHED
            assert facts.timestamp_anchor.state is EvidenceState.NOT_ESTABLISHED
            assert facts.day_definition.state is EvidenceState.NOT_ESTABLISHED
            assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
            assert facts.label_time is None
            assert cat_row["frequency"] == "unknown"
            assert cat_row["statistic"] == "unknown"
            assert cat_row["period_type"] == "unknown"
            assert cat_row["period_anchor"] == "unknown"
        else:
            assert facts.frequency.value == spec.frequency
            assert facts.statistic.value == spec.statistic
            assert facts.temporal_support.value == "interval"
            assert facts.timestamp_anchor.value == "start"
            assert cat_row["frequency"] == spec.frequency
            assert cat_row["statistic"] == spec.statistic
            assert cat_row["period_type"] == "interval"
            assert cat_row["period_anchor"] == "start"
            if spec.frequency == "daily":
                assert facts.day_definition.value == "+01:00"
                assert facts.clipping_axis is ClippingAxis.CALENDAR_DATE
                assert facts.label_time == "00:00"
                win = native_window(datetime(2024, 7, 1, 12, 0), datetime(2024, 7, 5, 6, 0), facts)
                assert win.start == datetime(2024, 7, 1, 0, 0)
                assert win.end == datetime(2024, 7, 5, 23, 59, 59, 999999)
            elif spec.frequency in {"monthly", "yearly"}:
                assert facts.day_definition.value is None
                assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
                assert facts.label_time == "00:00"
            else:
                assert facts.day_definition.value is None
                assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
                assert facts.label_time is None
