"""Synthetic controls for Germany PEGELONLINE source-annotation schema declarations."""

from __future__ import annotations

from rivretrieve._internal.providers.de_pegelonline.annotations import (
    DE_PEGELONLINE_API_URL,
    DE_PEGELONLINE_SERIES_SCHEMA,
    DE_PEGELONLINE_TRM_SCHEMA,
)
from rivretrieve._internal.source_annotations import AnnotationScope


def test_series_schema_declares_longname_and_comment_fields():
    assert DE_PEGELONLINE_API_URL == "https://www.pegelonline.wsv.de/webservice/dokuRestapi"
    assert DE_PEGELONLINE_SERIES_SCHEMA.schema_id == "de_pegelonline.series"
    assert DE_PEGELONLINE_SERIES_SCHEMA.provider_id == "de_pegelonline"
    assert DE_PEGELONLINE_SERIES_SCHEMA.scope is AnnotationScope.SERIES
    assert [field.name for field in DE_PEGELONLINE_SERIES_SCHEMA.fields] == [
        "longname",
        "comment_short",
        "comment_long",
    ]
    for field in DE_PEGELONLINE_SERIES_SCHEMA.fields:
        assert field.dtype == "String"
        assert field.reference_url == DE_PEGELONLINE_API_URL


def test_trm_schema_declares_the_first_float64_observation_annotation():
    assert DE_PEGELONLINE_TRM_SCHEMA.schema_id == "de_pegelonline.trm"
    assert DE_PEGELONLINE_TRM_SCHEMA.provider_id == "de_pegelonline"
    assert DE_PEGELONLINE_TRM_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in DE_PEGELONLINE_TRM_SCHEMA.fields] == ["difference"]
    difference = DE_PEGELONLINE_TRM_SCHEMA.fields[0]
    assert difference.dtype == "Float64"
    assert difference.polars_dtype.__class__.__name__ == "Float64"
    assert difference.reference_url == DE_PEGELONLINE_API_URL


def test_no_annotation_schema_mentions_the_excluded_live_status_codes():
    for schema in (DE_PEGELONLINE_SERIES_SCHEMA, DE_PEGELONLINE_TRM_SCHEMA):
        for field in schema.fields:
            text = f"{field.name} {field.description}".casefold()
            assert "mnwmhw" not in text
            assert "nswhsw" not in text
