"""Official source-annotation schema definitions for ``co_ideam``."""

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

CO_IDEAM_S3_REFERENCE_URL = "https://datos.ideam.gov.co"

CO_IDEAM_S3_SCHEMA = AnnotationSchema(
    schema_id="co_ideam.s3",
    provider_id="co_ideam",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="nivelAprobacion",
            dtype="String",
            description=(
                "IDEAM AQUARIUS approval status for this observation row, verbatim from the "
                "S3 CSV ``nivelAprobacion`` column. Known vocabulary: "
                '"Preliminar" (AQUARIUS approval 900, operational or migrated unvalidated), '
                '"En revisión" (approval 1100, under hydrological validation review), '
                '"Definitivo" (approval 1200, hydrologically validated), '
                "or empty string (unlabeled legacy migrated row). "
                "RivRetrieve preserves the value without interpretation."
            ),
            reference_url=CO_IDEAM_S3_REFERENCE_URL,
        ),
    ),
)

__all__ = [
    "CO_IDEAM_S3_REFERENCE_URL",
    "CO_IDEAM_S3_SCHEMA",
]
