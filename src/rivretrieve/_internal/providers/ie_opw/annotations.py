"""Official source-annotation schema definitions for Ireland OPW (``ie_opw``)."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

OPW_QUALITY_CODES_URL = "https://waterlevel.ie/hydro-data/html/qualitycodes.html"
OPW_DATA_TYPES_URL = "https://waterlevel.ie/hydro-data/html/datatypes.html"

QUALITY_CODE_FIELD = AnnotationField(
    name="quality_code",
    dtype="Int64",
    description=(
        "Native OPW WISKI integer Quality Code verbatim from Hydro-Data JSON and ZIP exports. "
        "OPW documents -1 and 255 as missing/no data available, 254 as unchecked imported/provisional "
        "data (including uncalibrated water-temperature transducer telemetry), 31/32/36/41/42/46/56/96/"
        "101/151 as inspected/corrected/rating-curve/unusable grades, and exports additional WISKI "
        "codes (observed integers include 1, 16, 34, 99, 146, 150, 156, 225) preserved verbatim."
    ),
    reference_url=OPW_QUALITY_CODES_URL,
)

AGGREGATION_ACCURACY_PCT_FIELD = AnnotationField(
    name="aggregation_accuracy_pct",
    dtype="Float64",
    description=(
        "Native OPW Hydro-Data Aggregation Accuracy % numeric column published on daily stage "
        "(S/year.json) exports alongside Value and Quality Code."
    ),
    reference_url=OPW_DATA_TYPES_URL,
)

IE_OPW_SERIES_SCHEMA = AnnotationSchema(
    schema_id="ie_opw.series",
    provider_id="ie_opw",
    scope=AnnotationScope.OBSERVATION,
    fields=(QUALITY_CODE_FIELD,),
)

IE_OPW_DAILY_STAGE_SCHEMA = AnnotationSchema(
    schema_id="ie_opw.daily_stage",
    provider_id="ie_opw",
    scope=AnnotationScope.OBSERVATION,
    fields=(QUALITY_CODE_FIELD, AGGREGATION_ACCURACY_PCT_FIELD),
)

__all__ = [
    "AGGREGATION_ACCURACY_PCT_FIELD",
    "IE_OPW_DAILY_STAGE_SCHEMA",
    "IE_OPW_SERIES_SCHEMA",
    "OPW_DATA_TYPES_URL",
    "OPW_QUALITY_CODES_URL",
    "QUALITY_CODE_FIELD",
]
