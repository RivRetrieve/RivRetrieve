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
        '"BELOW_LOQ", "OUTLIER", "UNCHECKED"). Verified daily observations through '
        "the end of the last completed calendar year omit qualityFlag (null); "
        'current-year operational daily discharge (Q) and stage (H) rows carry "UNCHECKED" '
        "pending annual WISKI verification, while operational daily water-temperature "
        "(T) rows continue omitting qualityFlag (null). RivRetrieve preserves the "
        "publisher label without filtering or ranking."
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
