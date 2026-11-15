"""Official source-annotation schema definitions for ``no_nve``."""

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

NO_NVE_URL = "https://hydapi.nve.no/UserDocumentation/"

NO_NVE_OBSERVATIONS_SCHEMA = AnnotationSchema(
    schema_id="no_nve.observations",
    provider_id="no_nve",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="quality",
            dtype="Int64",
            description=(
                "NVE HydAPI observation quality control code "
                "(0 unchecked, 1 preliminary checked, 2 asserted/adjusted, 3 quality-controlled)."
            ),
            reference_url=NO_NVE_URL,
        ),
        AnnotationField(
            name="correction",
            dtype="Int64",
            description=(
                "NVE HydAPI observation correction code "
                "(0 none, 1 manual, 2 linear interpolation, 3 offset/correction, 4 automatic/derived)."
            ),
            reference_url=NO_NVE_URL,
        ),
    ),
)

__all__ = [
    "NO_NVE_OBSERVATIONS_SCHEMA",
    "NO_NVE_URL",
]
