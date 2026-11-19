"""Annotation schemas for official Swiss FOEN / BAFU GraphQL responses."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

BAFU_WATER_OBSERVATIONS_URL = "https://data.bafu.admin.ch/en/dataproduct-water-observations"

RELEASE_STATE_FIELD = AnnotationField(
    name="releaseState",
    dtype="String",
    description=(
        "BAFU archive release and validation state code (null or '0' for raw, '1' for unreleased/prechecked, "
        "'2' for released/checked, '3' for released/definitive; publisher 'ersetzt' wording establishes no lineage)."
    ),
    reference_url=BAFU_WATER_OBSERVATIONS_URL,
)

RELEASE_STATUS_FIELD = AnnotationField(
    name="releaseStatus",
    dtype="Int64",
    description="BAFU recent live-feed release status flag (0 for uncorrected raw readings).",
    reference_url=BAFU_WATER_OBSERVATIONS_URL,
)

CH_FOEN_ARCHIVE_SCHEMA = AnnotationSchema(
    schema_id="ch_foen.archive",
    provider_id="ch_foen",
    scope=AnnotationScope.OBSERVATION,
    fields=(RELEASE_STATE_FIELD,),
)

CH_FOEN_RECENT_SCHEMA = AnnotationSchema(
    schema_id="ch_foen.recent",
    provider_id="ch_foen",
    scope=AnnotationScope.OBSERVATION,
    fields=(RELEASE_STATUS_FIELD,),
)

__all__ = [
    "BAFU_WATER_OBSERVATIONS_URL",
    "CH_FOEN_ARCHIVE_SCHEMA",
    "CH_FOEN_RECENT_SCHEMA",
    "RELEASE_STATE_FIELD",
    "RELEASE_STATUS_FIELD",
]
