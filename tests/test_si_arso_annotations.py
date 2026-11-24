"""Verify Slovenia ARSO series annotation schemas and provenance status semantics."""

from __future__ import annotations

from rivretrieve._internal.providers.si_arso.annotations import (
    ARSO_OPOMBA_HIDRO_URL,
    SI_ARSO_SERIES_SCHEMA,
)
from rivretrieve._internal.source_annotations import AnnotationScope


def test_si_arso_series_annotation_schema() -> None:
    assert SI_ARSO_SERIES_SCHEMA.schema_id == "si_arso.series"
    assert SI_ARSO_SERIES_SCHEMA.provider_id == "si_arso"
    assert SI_ARSO_SERIES_SCHEMA.scope == AnnotationScope.SERIES
    assert [field.name for field in SI_ARSO_SERIES_SCHEMA.fields] == ["data_status"]
    assert SI_ARSO_SERIES_SCHEMA.fields[0].reference_url == ARSO_OPOMBA_HIDRO_URL
