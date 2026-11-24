"""Annotation schema for BoM KiWIS per-observation quality codes."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

BOM_WATER_DATA_URL = "https://www.bom.gov.au/waterdata/"

QUALITY_CODE_FIELD = AnnotationField(
    name="Quality_Code",
    dtype="Int64",
    description=(
        "BoM KiWIS Quality Code: a numeric quality code published alongside each observation "
        "(for example 10 for quality-A, -1 for quality-E). Not a RivRetrieve ranking or filter."
    ),
    reference_url=BOM_WATER_DATA_URL,
)

QUALITY_CODE_NAME_FIELD = AnnotationField(
    name="Quality_Code_Name",
    dtype="String",
    description=(
        "BoM KiWIS Quality Code Name: the human-readable label published alongside Quality_Code "
        "(for example 'quality-A', 'quality-E'); can be null even when a code is published."
    ),
    reference_url=BOM_WATER_DATA_URL,
)

AU_BOM_QUALITY_SCHEMA = AnnotationSchema(
    schema_id="au_bom.quality",
    provider_id="au_bom",
    scope=AnnotationScope.OBSERVATION,
    fields=(QUALITY_CODE_FIELD, QUALITY_CODE_NAME_FIELD),
)

__all__ = [
    "AU_BOM_QUALITY_SCHEMA",
    "BOM_WATER_DATA_URL",
    "QUALITY_CODE_FIELD",
    "QUALITY_CODE_NAME_FIELD",
]
