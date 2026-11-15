"""Official source-annotation schema definition for ``at_ehyd``."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

AT_EHYD_GUIDE_URL = "https://ehyd.gv.at/assets/documents/eHYD_Allgemein.pdf"

AT_EHYD_SERIES_SCHEMA = AnnotationSchema(
    schema_id="at_ehyd.series",
    provider_id="at_ehyd",
    scope=AnnotationScope.SERIES,
    fields=(
        AnnotationField(
            name="data_quality",
            dtype="String",
            description=(
                "Series-level validation label published by eHYD streams "
                "('Geprüfte Daten' on historical OWF CSV downloads; "
                "'ungeprüfte Rohdaten!' on Pegel Aktuell telemetry series)."
            ),
            reference_url=AT_EHYD_GUIDE_URL,
        ),
    ),
)
