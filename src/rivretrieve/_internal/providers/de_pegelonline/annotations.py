"""Official source-annotation schema definitions for `de_pegelonline`."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

DE_PEGELONLINE_API_URL = "https://www.pegelonline.wsv.de/webservice/dokuRestapi"

DE_PEGELONLINE_SERIES_SCHEMA = AnnotationSchema(
    schema_id="de_pegelonline.series",
    provider_id="de_pegelonline",
    scope=AnnotationScope.SERIES,
    fields=(
        AnnotationField(
            name="longname",
            dtype="String",
            description=(
                "PEGELONLINE's published 'longname' for this timeseries, distinguishing raw-data "
                "variants (e.g. 'WASSERSTAND ROHDATEN') from their edited counterparts that share "
                "the same shortname (e.g. 'WASSERSTAND')."
            ),
            reference_url=DE_PEGELONLINE_API_URL,
        ),
        AnnotationField(
            name="comment_short",
            dtype="String",
            description=(
                "PEGELONLINE's catalogue-time 'comment.shortDescription' outage/malfunction note for "
                "this timeseries (e.g. 'Ausfall'), honest only as of the catalogue's own check date."
            ),
            reference_url=DE_PEGELONLINE_API_URL,
        ),
        AnnotationField(
            name="comment_long",
            dtype="String",
            description=(
                "PEGELONLINE's catalogue-time 'comment.longDescription' outage/malfunction note for "
                "this timeseries, honest only as of the catalogue's own check date."
            ),
            reference_url=DE_PEGELONLINE_API_URL,
        ),
    ),
)

DE_PEGELONLINE_TRM_SCHEMA = AnnotationSchema(
    schema_id="de_pegelonline.trm",
    provider_id="de_pegelonline",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="difference",
            dtype="Float64",
            description=(
                "PEGELONLINE's published change from the previous day's scheduled ('Terminwerte') "
                "reading. Published only on TRM and TRM_WT, PEGELONLINE's scheduled-reading products."
            ),
            reference_url=DE_PEGELONLINE_API_URL,
        ),
    ),
)
