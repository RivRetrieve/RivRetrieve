"""Annotation schemas for ECCC HYDAT compiled daily observation stores."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

HYDAT_DEFINITION_URL = "https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/HYDAT_Definition_EN.pdf"

SYMBOL_FIELD = AnnotationField(
    name="symbol",
    dtype="String",
    description=(
        "HYDAT daily DATA_SYMBOLS code associated with a daily mean or published null day, "
        "such as A (partial day), B (ice conditions), D (dry), or E (estimated)."
    ),
    reference_url=HYDAT_DEFINITION_URL,
)

PRECISION_CODE_FIELD = AnnotationField(
    name="precision_code",
    dtype="Int64",
    description=(
        "HYDAT PRECISION_CODES water-level recording precision code "
        "(8 for metres to millimetres, 9 for metres to centimetres)."
    ),
    reference_url=HYDAT_DEFINITION_URL,
)

CA_ECCC_DLY_FLOWS_SCHEMA = AnnotationSchema(
    schema_id="ca_eccc.dly_flows",
    provider_id="ca_eccc",
    scope=AnnotationScope.OBSERVATION,
    fields=(SYMBOL_FIELD,),
)

CA_ECCC_DLY_LEVELS_SCHEMA = AnnotationSchema(
    schema_id="ca_eccc.dly_levels",
    provider_id="ca_eccc",
    scope=AnnotationScope.OBSERVATION,
    fields=(SYMBOL_FIELD, PRECISION_CODE_FIELD),
)

__all__ = [
    "CA_ECCC_DLY_FLOWS_SCHEMA",
    "CA_ECCC_DLY_LEVELS_SCHEMA",
    "HYDAT_DEFINITION_URL",
    "PRECISION_CODE_FIELD",
    "SYMBOL_FIELD",
]
