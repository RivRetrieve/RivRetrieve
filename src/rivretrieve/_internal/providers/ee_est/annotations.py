"""Official source-annotation schema for Estonia EstModel observation quality flags."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

ESTMODEL_SWAGGER_URL = "https://app.swaggerhub.com/apis/estmodel/estmodel-api/1.0.0"

QUALITY_FLAG_VALUES: tuple[str, ...] = ("BELOW_LOQ", "OUTLIER", "UNCHECKED")

QUALITY_FLAG_FIELD = AnnotationField(
    name="qualityFlag",
    dtype="String",
    description=(
        "EstModel OpenAPI Measurement.qualityFlag verbatim string (schema enum: "
        '"BELOW_LOQ", "OUTLIER", "UNCHECKED"). Null does not mean checked: observed '
        "2026-11-26 across the full daily histories at Ahja (SJA8821000) and Tartu "
        "(SJA7331000), every row up to 2025-12-31 omits qualityFlag (null), 2026 Q "
        'and H rows carry "UNCHECKED", 2026 T rows omit qualityFlag (null), and '
        '"BELOW_LOQ" and "OUTLIER" never appear. RivRetrieve preserves the publisher '
        "label without filtering or ranking."
    ),
    reference_url=ESTMODEL_SWAGGER_URL,
)

EE_EST_ESTMODEL_SCHEMA = AnnotationSchema(
    schema_id="ee_est.estmodel",
    provider_id="ee_est",
    scope=AnnotationScope.OBSERVATION,
    fields=(QUALITY_FLAG_FIELD,),
)

__all__ = [
    "EE_EST_ESTMODEL_SCHEMA",
    "ESTMODEL_SWAGGER_URL",
    "QUALITY_FLAG_FIELD",
    "QUALITY_FLAG_VALUES",
]
