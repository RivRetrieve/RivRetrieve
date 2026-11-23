"""Physical series-meaning and annotation schema checks for Ireland OPW (`ie_opw`)."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ie_opw.annotations import (
    AGGREGATION_ACCURACY_PCT_FIELD,
    IE_OPW_DAILY_STAGE_SCHEMA,
    IE_OPW_SERIES_SCHEMA,
    QUALITY_CODE_FIELD,
)
from rivretrieve._internal.providers.ie_opw.series import PRODUCT_BY_ID, PRODUCT_SPECS, catalogue_product_rows
from rivretrieve._internal.source_annotations import AnnotationBundle, ObservationAnnotationTable
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceState,
    PhysicalPredicate,
    SeriesScope,
    admission,
)
from rivretrieve._internal.time_axis import TimeAxis, axis_time_expression, timestamp_on_axis


def test_ie_opw_series_physical_facts_distinguish_daily_utc_instantaneous_and_mixed_od_stage() -> None:
    rows = {row["product_id"]: row for row in catalogue_product_rows()}
    assert len(rows) == 12

    for spec in PRODUCT_SPECS:
        series = spec.series_mapping().source_series("ie_opw", "01041", spec.product_id)
        facts = series.facts[0]
        decision = admission(facts)
        assert decision.status == "supported"
        assert decision.factor == 1.0
        assert decision.target_unit == spec.normalized_unit
        assert facts.time_zone.state is EvidenceState.KNOWN
        assert facts.time_zone.value == "+00:00"

        if spec.route == "year.json":
            assert facts.frequency.value == "daily"
            assert facts.temporal_support.value == "calendar_day"
            assert facts.day_definition.value == "+00:00"
            assert facts.timestamp_anchor.value == "start"
            assert facts.clipping_axis is ClippingAxis.CALENDAR_DATE
            assert facts.label_time == "00:00"
            assert rows[spec.product_id]["period_type"] == "calendar_day"
            assert rows[spec.product_id]["period_anchor"] == "start"
        else:
            assert facts.frequency.state is EvidenceState.NOT_ESTABLISHED
            assert facts.frequency.value is None
            assert facts.statistic.value == "instantaneous"
            assert facts.temporal_support.value == "instantaneous"
            assert facts.day_definition.state is EvidenceState.NOT_ESTABLISHED
            assert facts.timestamp_anchor.value == "measurement_time"
            assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
            assert facts.label_time is None
            assert rows[spec.product_id]["period_type"] == "instant"
            assert rows[spec.product_id]["period_anchor"] == "measurement_time"

        if spec.quantity == "stage":
            assert facts.vertical_reference.value == "above_sea_level"
            assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
            assert facts.vertical_datum.value is None
        else:
            assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
            assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED

        ts = datetime(2025, 7, 15, 0, 0)
        assert timestamp_on_axis(ts, facts.time_zone.value, TimeAxis.UTC) == ts
        df = pl.DataFrame({"time": [ts], "time_zone": [facts.time_zone.value]})
        assert df.select(axis_time_expression(TimeAxis.UTC))["time"].item() == ts


def test_ie_opw_physical_predicates_filter_utc_day_and_reject_single_vertical_datum() -> None:
    q_daily = (
        PRODUCT_BY_ID["discharge_daily_mean"].series_mapping().source_series("ie_opw", "01041", "discharge_daily_mean")
    )
    s_daily = PRODUCT_BY_ID["stage_daily_mean"].series_mapping().source_series("ie_opw", "30061", "stage_daily_mean")
    s_inst = (
        PRODUCT_BY_ID["stage_instantaneous"].series_mapping().source_series("ie_opw", "30061", "stage_instantaneous")
    )

    assert SeriesScope(predicates=(PhysicalPredicate(field="day_definition", value="+00:00"),)).matches(q_daily)
    assert SeriesScope(predicates=(PhysicalPredicate(field="vertical_reference", value="above_sea_level"),)).matches(
        s_daily
    )
    assert not SeriesScope(predicates=(PhysicalPredicate(field="vertical_datum", value="Malin Head OSGM15"),)).matches(
        s_daily
    )
    assert not SeriesScope(predicates=(PhysicalPredicate(field="frequency", value="15min"),)).matches(s_inst)


def test_ie_opw_annotation_schemas_enforce_observation_dtypes_and_reserved_names() -> None:
    assert QUALITY_CODE_FIELD.name == "quality_code"
    assert QUALITY_CODE_FIELD.dtype == "Int64"
    assert AGGREGATION_ACCURACY_PCT_FIELD.name == "aggregation_accuracy_pct"
    assert AGGREGATION_ACCURACY_PCT_FIELD.dtype == "Float64"

    series_frame = pl.DataFrame(
        {
            "series_id": ["s1", "s1"],
            "facts_id": ["f1", "f1"],
            "station_id": ["01041", "01041"],
            "product_id": ["discharge_daily_mean", "discharge_daily_mean"],
            "time": [datetime(2025, 7, 15, 0, 0), datetime(2025, 7, 16, 0, 0)],
            "time_zone": ["+00:00", "+00:00"],
            "measured": [True, False],
            "quality_code": pl.Series([31, -1], dtype=pl.Int64),
        }
    )
    daily_stage_frame = pl.DataFrame(
        {
            "series_id": ["s2"],
            "facts_id": ["f2"],
            "station_id": ["30061"],
            "product_id": ["stage_daily_mean"],
            "time": [datetime(2004, 6, 25, 0, 0)],
            "time_zone": ["+00:00"],
            "measured": [True],
            "quality_code": pl.Series([31], dtype=pl.Int64),
            "aggregation_accuracy_pct": pl.Series([100.0], dtype=pl.Float64),
        }
    )
    bundle = AnnotationBundle(
        observation_tables={
            "ie_opw.series": ObservationAnnotationTable.from_rows(
                schema=IE_OPW_SERIES_SCHEMA,
                rows=series_frame,
                measurement_indices=(0, None),
            ),
            "ie_opw.daily_stage": ObservationAnnotationTable.from_rows(
                schema=IE_OPW_DAILY_STAGE_SCHEMA,
                rows=daily_stage_frame,
                measurement_indices=(0,),
            ),
        }
    )
    assert set(bundle.observation_tables) == {"ie_opw.series", "ie_opw.daily_stage"}
    assert bundle.observation_tables["ie_opw.series"].unmeasured_count == 1

    bad_dtype = series_frame.with_columns(pl.col("quality_code").cast(pl.String))
    with pytest.raises((FatalContractError, ValueError)):
        ObservationAnnotationTable.from_rows(
            schema=IE_OPW_SERIES_SCHEMA,
            rows=bad_dtype,
            measurement_indices=(0, None),
        )
