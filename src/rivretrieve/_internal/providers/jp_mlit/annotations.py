"""Official source-annotation schema definitions for ``jp_mlit``."""

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

JP_MLIT_URL = "https://www1.river.go.jp/"

JP_MLIT_OBSERVATIONS_SCHEMA = AnnotationSchema(
    schema_id="jp_mlit.observations",
    provider_id="jp_mlit",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="flag",
            dtype="String",
            description=(
                "Source observation slot flag from MLIT Water Information System DAT exports: "
                "'*' provisional measurement, '$' missing slot, '#' station closed, "
                "'-' unregistered slot, or null when unflagged."
            ),
            reference_url=JP_MLIT_URL,
        ),
    ),
)

__all__ = [
    "JP_MLIT_OBSERVATIONS_SCHEMA",
    "JP_MLIT_URL",
]
