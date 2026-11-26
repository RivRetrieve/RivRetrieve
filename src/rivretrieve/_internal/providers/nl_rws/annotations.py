"""Official source-annotation schema definitions for `nl_rws`."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

RWS_WATERDATA_URL = "https://rijkswaterstaatdata.nl/onze-data/waterdata/"
AQUO_STANDARD_URL = "https://www.aquo.nl/"

NL_RWS_OBSERVATION_SCHEMA = AnnotationSchema(
    schema_id="nl_rws.observation",
    provider_id="nl_rws",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="statuswaarde",
            dtype="String",
            description=(
                "Rijkswaterstaat DDAPI 2.0 WaarnemingMetadata.Statuswaarde indicating the "
                "publisher's validation status for the observation (e.g. 'Ongecontroleerd', "
                "'Gecontroleerd', 'Definitief')."
            ),
            reference_url=RWS_WATERDATA_URL,
        ),
        AnnotationField(
            name="kwaliteitswaardecode",
            dtype="String",
            description=(
                "Aquo/Rijkswaterstaat DDAPI 2.0 WaarnemingMetadata.Kwaliteitswaardecode "
                "attached to the observation (e.g. '00' normal, '25' qualified, '99' missing "
                "value encoded alongside sentinel 9.99999e+37)."
            ),
            reference_url=AQUO_STANDARD_URL,
        ),
    ),
)
