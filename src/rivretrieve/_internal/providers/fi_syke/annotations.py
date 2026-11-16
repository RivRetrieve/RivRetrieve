"""Official source-annotation schema definitions for ``fi_syke``."""

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

FI_SYKE_URL = "https://www.syke.fi/en-US/Open_information/Open_web_services"

FI_SYKE_OBSERVATIONS_SCHEMA = AnnotationSchema(
    schema_id="fi_syke.observations",
    provider_id="fi_syke",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="Lippu_id",
            dtype="Int64",
            description=(
                "SYKE Hydrologiarajapinta integer foreign key into the Lippu flag table "
                "covering mixed quality, processing, percentile, simulated-value, and device indicators; "
                "null when unflagged."
            ),
            reference_url=FI_SYKE_URL,
        ),
    ),
)

__all__ = [
    "FI_SYKE_OBSERVATIONS_SCHEMA",
    "FI_SYKE_URL",
]
