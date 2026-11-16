"""Annotation schemas for modern USGS Water Data OGC API responses."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

_OPENAPI_V1_REFERENCE = "https://api.waterdata.usgs.gov/ogcapi/v1/openapi?f=json"
_CONTINUOUS_SCHEMA_REFERENCE = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/schema"

APPROVAL_STATUS_FIELD = AnnotationField(
    name="approval_status",
    dtype="String",
    description=(
        "USGS processing review status (Approved after review and publication, "
        "or Provisional while subject to revision)."
    ),
    reference_url=_OPENAPI_V1_REFERENCE,
)

QUALIFIER_FIELD = AnnotationField(
    name="qualifier",
    dtype="List(String)",
    description=(
        "Source observation qualifiers associated with a measurement or published null value, such as Ice or ESTIMATED."
    ),
    reference_url=_OPENAPI_V1_REFERENCE,
)

METHOD_CATEGORY_FIELD = AnnotationField(
    name="method_category",
    dtype="String",
    description="USGS RLMS method category code classifying the method in effect for this interval.",
    reference_url=_CONTINUOUS_SCHEMA_REFERENCE,
)

USGS_NWIS_DAILY_SCHEMA = AnnotationSchema(
    schema_id="usgs_nwis.daily",
    provider_id="usgs_nwis",
    scope=AnnotationScope.OBSERVATION,
    fields=(APPROVAL_STATUS_FIELD, QUALIFIER_FIELD),
)

USGS_NWIS_CONTINUOUS_SCHEMA = AnnotationSchema(
    schema_id="usgs_nwis.continuous",
    provider_id="usgs_nwis",
    scope=AnnotationScope.OBSERVATION,
    fields=(APPROVAL_STATUS_FIELD, QUALIFIER_FIELD, METHOD_CATEGORY_FIELD),
)

__all__ = [
    "APPROVAL_STATUS_FIELD",
    "METHOD_CATEGORY_FIELD",
    "QUALIFIER_FIELD",
    "USGS_NWIS_CONTINUOUS_SCHEMA",
    "USGS_NWIS_DAILY_SCHEMA",
]
