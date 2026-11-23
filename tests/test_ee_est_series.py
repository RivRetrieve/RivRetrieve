"""Source-independent tests for Estonia (`ee_est`) Step 3 series meaning and annotations."""

from __future__ import annotations

import pytest

from rivretrieve._internal.providers.ee_est.annotations import (
    EE_EST_ESTMODEL_SCHEMA,
    ESTMODEL_SWAGGER_URL,
    QUALITY_FLAG_VALUES,
)
from rivretrieve._internal.providers.ee_est.series import (
    EM_KEY_TO_PRODUCT,
    ESTMODEL_NAMESPACE,
    FH_AEGRIDA_TO_PRODUCT,
    FH_NAMESPACE,
    PRODUCT_BY_ID,
    PRODUCT_SPECS,
    catalogue_product_rows,
)
from rivretrieve._internal.source_annotations import AnnotationScope
from rivretrieve._internal.source_series import ClippingAxis, EvidenceState, admission


def test_ee_est_estmodel_annotation_schema() -> None:
    assert EE_EST_ESTMODEL_SCHEMA.schema_id == "ee_est.estmodel"
    assert EE_EST_ESTMODEL_SCHEMA.provider_id == "ee_est"
    assert EE_EST_ESTMODEL_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [(field.name, field.dtype) for field in EE_EST_ESTMODEL_SCHEMA.fields] == [("qualityFlag", "String")]
    field = EE_EST_ESTMODEL_SCHEMA.fields[0]
    assert field.reference_url == ESTMODEL_SWAGGER_URL
    assert QUALITY_FLAG_VALUES == ("BELOW_LOQ", "OUTLIER", "UNCHECKED")
    for token in QUALITY_FLAG_VALUES:
        assert token in field.description


def test_all_18_products_establish_physical_meaning_and_dimensional_admission() -> None:
    assert len(PRODUCT_SPECS) == 18
    assert len(PRODUCT_BY_ID) == 18
    assert len(EM_KEY_TO_PRODUCT) == 9
    assert len(FH_AEGRIDA_TO_PRODUCT) == 9

    rows = {row["product_id"]: row for row in catalogue_product_rows()}
    assert len(rows) == 18

    for spec in PRODUCT_SPECS:
        mapping = spec.series_mapping()
        facts = mapping.physical_facts()
        dec = admission(facts)
        assert dec.status == "supported"

        assert facts.temporal_support.state is EvidenceState.KNOWN
        assert facts.temporal_support.value == "interval"
        assert facts.day_definition.state is EvidenceState.NOT_ESTABLISHED
        assert facts.day_definition.value is None
        assert facts.timestamp_anchor.state is EvidenceState.NOT_ESTABLISHED
        assert facts.timestamp_anchor.value is None

        if spec.source_api == "estmodel":
            assert mapping.namespace == ESTMODEL_NAMESPACE
            assert facts.frequency.value == "daily"
            assert facts.time_zone.state is EvidenceState.NOT_ESTABLISHED
            assert facts.time_zone.value is None
            assert facts.clipping_axis is ClippingAxis.CALENDAR_DATE
            assert facts.label_time == "00:00"
        else:
            assert mapping.namespace == FH_NAMESPACE
            assert facts.frequency.value == "hourly"
            assert facts.time_zone.state is EvidenceState.KNOWN
            assert facts.time_zone.value == "+00:00"
            assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
            assert facts.label_time is None

        if spec.quantity == "stage":
            assert dec.target_unit == "m"
            assert dec.factor == pytest.approx(1.0 if spec.source_unit == "m" else 0.01)
            assert facts.vertical_reference.state is EvidenceState.KNOWN
            assert facts.vertical_reference.value == "gauge_zero"
            assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
            assert facts.vertical_datum.value is None
        elif spec.quantity == "discharge":
            assert dec.target_unit == "m3/s"
            assert dec.factor == pytest.approx(1.0)
            assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
        else:
            assert dec.target_unit == "degC"
            assert dec.factor == pytest.approx(1.0)
            assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED

        cat_row = rows[spec.product_id]
        assert cat_row["frequency"] == spec.frequency
        assert cat_row["statistic"] == spec.statistic
        assert cat_row["period_type"] == "interval"
        assert cat_row["period_anchor"] == "unknown"
        assert cat_row["unit"] == dec.target_unit
