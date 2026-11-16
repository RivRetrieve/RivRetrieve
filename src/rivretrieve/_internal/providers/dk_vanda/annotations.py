"""Annotation schema for VandA water-temperature reason flags."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

VANDA_SWAGGER_URL = "https://vandah.miljoeportal.dk/api/swagger/index.html"

REASON_SC_FIELD = AnnotationField(
    name="reasonSc",
    dtype="Int64",
    description=(
        "VandA's reasonCodesSc code for a flagged water-temperature reading, one of "
        "examination-type 29's published vocabulary (observed values 0-17). VandA's "
        "`/config/examination-types` publishes this vocabulary with no textual meaning "
        "for any code; only the paired `reason` field carries text."
    ),
    reference_url=VANDA_SWAGGER_URL,
)

REASON_FIELD = AnnotationField(
    name="reason",
    dtype="String",
    description="VandA's own published free-text reason for a flagged water-temperature reading, verbatim.",
    reference_url=VANDA_SWAGGER_URL,
)

DK_VANDA_TEMPERATURE_SCHEMA = AnnotationSchema(
    schema_id="dk_vanda.temperature",
    provider_id="dk_vanda",
    scope=AnnotationScope.OBSERVATION,
    fields=(REASON_SC_FIELD, REASON_FIELD),
)

__all__ = [
    "DK_VANDA_TEMPERATURE_SCHEMA",
    "REASON_FIELD",
    "REASON_SC_FIELD",
    "VANDA_SWAGGER_URL",
]
