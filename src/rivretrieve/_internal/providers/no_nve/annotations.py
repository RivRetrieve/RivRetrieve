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
                "NVE HydAPI Observation.quality code "
                "(0 - unknown, 1 - uncontrolled, 2 - primary controlled, 3 - secondary controlled)."
            ),
            reference_url=NO_NVE_URL,
        ),
        AnnotationField(
            name="correction",
            dtype="Int64",
            description=(
                "NVE HydAPI Observation.correction code "
                "(0: No changes, 1: Manual- or ice correction, 2: Interpolation, "
                "3: Value computed with models or/and other series, "
                "4: Daily mean computed with arithmetic mean, 5: Smooth negative value, "
                "6: Dry pipe, 7: Ice in pipe, 8: Damaged pipe, 9: Pumping, "
                "11: Start/end value linear adjustment, 12: Incomplete data source, "
                "13: Calculated from a similar or nearby station, "
                "14: Missing, calculated from series statistics, "
                "15: Calculation ended in NaN or +/-Inf, "
                "16: Value fetched from rejected period)."
            ),
            reference_url=NO_NVE_URL,
        ),
    ),
)

__all__ = [
    "NO_NVE_OBSERVATIONS_SCHEMA",
    "NO_NVE_URL",
]
