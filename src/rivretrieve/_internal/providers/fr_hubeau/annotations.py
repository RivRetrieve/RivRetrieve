"""Official source-annotation schema definitions for ``fr_hubeau``."""

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

FR_HUBEAU_HYDROMETRIE_URL = "https://hubeau.eaufrance.fr/page/api-hydrometrie"
FR_HUBEAU_TEMPERATURE_URL = "https://hubeau.eaufrance.fr/page/api-temperature-continu"

FR_HUBEAU_OBS_ELAB_SCHEMA = AnnotationSchema(
    schema_id="fr_hubeau.obs_elab",
    provider_id="fr_hubeau",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="code_statut",
            dtype="Int64",
            description="Hub'Eau hydrometry validation status code (for example 4 raw, 12 pre-validated, 16 validated).",
            reference_url=FR_HUBEAU_HYDROMETRIE_URL,
        ),
        AnnotationField(
            name="libelle_statut",
            dtype="String",
            description="French label reported by Hub'Eau hydrometry for code_statut.",
            reference_url=FR_HUBEAU_HYDROMETRIE_URL,
        ),
        AnnotationField(
            name="code_qualification",
            dtype="Int64",
            description="Hub'Eau hydrometry quality qualification code for the elaborated observation.",
            reference_url=FR_HUBEAU_HYDROMETRIE_URL,
        ),
        AnnotationField(
            name="libelle_qualification",
            dtype="String",
            description="French label reported by Hub'Eau hydrometry for code_qualification.",
            reference_url=FR_HUBEAU_HYDROMETRIE_URL,
        ),
        AnnotationField(
            name="code_methode",
            dtype="Int64",
            description="Hub'Eau hydrometry elaboration method code (for example 0 measured, 8 calculated).",
            reference_url=FR_HUBEAU_HYDROMETRIE_URL,
        ),
        AnnotationField(
            name="libelle_methode",
            dtype="String",
            description="French label reported by Hub'Eau hydrometry for code_methode.",
            reference_url=FR_HUBEAU_HYDROMETRIE_URL,
        ),
    ),
)

FR_HUBEAU_TEMPERATURE_SCHEMA = AnnotationSchema(
    schema_id="fr_hubeau.temperature_chronique",
    provider_id="fr_hubeau",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="code_qualification",
            dtype="String",
            description="Hub'Eau river temperature qualification code as published in string form.",
            reference_url=FR_HUBEAU_TEMPERATURE_URL,
        ),
        AnnotationField(
            name="libelle_qualification",
            dtype="String",
            description="French label reported by Hub'Eau river temperature for code_qualification.",
            reference_url=FR_HUBEAU_TEMPERATURE_URL,
        ),
    ),
)

__all__ = [
    "FR_HUBEAU_HYDROMETRIE_URL",
    "FR_HUBEAU_OBS_ELAB_SCHEMA",
    "FR_HUBEAU_TEMPERATURE_SCHEMA",
    "FR_HUBEAU_TEMPERATURE_URL",
]
