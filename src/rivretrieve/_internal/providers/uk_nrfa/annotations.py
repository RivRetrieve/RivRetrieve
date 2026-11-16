"""Official source-annotation schema definitions for ``uk_nrfa``."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

API_HELP_URL = "https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html"
AMAX_DOC_URL = "https://nrfa.ceh.ac.uk/data/about-data/peak-flow-data/data-types/annual-maximum"
MISSING_AND_REJECTED_URL = "https://nrfa.ceh.ac.uk/data/about-data/peak-flow-data/data-types/missing-and-rejected-data"

UK_NRFA_OBSERVATIONS_SCHEMA = AnnotationSchema(
    schema_id="uk_nrfa.observations",
    provider_id="uk_nrfa",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="source_label",
            dtype="String",
            description=(
                "Original date, year-month, or datetime string returned verbatim in NRFA JSON data-stream output."
            ),
            reference_url=API_HELP_URL,
        ),
        AnnotationField(
            name="flag",
            dtype="String",
            description=(
                "NRFA data quality flag returned when flags=true (such as 'E' for estimated or 'S' for suspect); "
                "null when unflagged."
            ),
            reference_url=API_HELP_URL,
        ),
    ),
)

UK_NRFA_SERIES_METADATA_SCHEMA = AnnotationSchema(
    schema_id="uk_nrfa.series_metadata",
    provider_id="uk_nrfa",
    scope=AnnotationScope.SERIES,
    fields=(
        AnnotationField(
            name="data_type_name",
            dtype="String",
            description="Official NRFA data-type display name from the response header (data-type.name).",
            reference_url=API_HELP_URL,
        ),
        AnnotationField(
            name="measurement_type",
            dtype="String",
            description=(
                "Source measurement-type vocabulary from data-type.measurement-type (Mean, Measured, or Maximum); "
                "kept verbatim without inferring an independent stage selection rule."
            ),
            reference_url=API_HELP_URL,
        ),
        AnnotationField(
            name="source_period",
            dtype="String",
            description=(
                "Source ISO period token from data-type.period (P1D, P1M, PT15M, or PT1S); "
                "kept verbatim without inferring observation duration or regular sampling."
            ),
            reference_url=API_HELP_URL,
        ),
    ),
)

UK_NRFA_AMAX_REJECTION_SCHEMA = AnnotationSchema(
    schema_id="uk_nrfa.amax_rejection",
    provider_id="uk_nrfa",
    scope=AnnotationScope.SERIES,
    fields=(
        AnnotationField(
            name="rejected_amax_years",
            dtype="List(Int64)",
            description=(
                "Excluded AMAX year integers reported in NRFA station-info "
                "peak-flow-rejected-amax-years.excluded-years; null when NRFA reports null metadata and empty "
                "list when explicitly empty, preserved verbatim without inferring water-year endpoint encoding."
            ),
            reference_url=AMAX_DOC_URL,
        ),
    ),
)

UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA = AnnotationSchema(
    schema_id="uk_nrfa.peak_rejected_periods",
    provider_id="uk_nrfa",
    scope=AnnotationScope.SERIES,
    fields=(
        AnnotationField(
            name="rejected_periods",
            dtype="List(String)",
            description=(
                "Unrepresentative or rejected period strings reported in NRFA station-info "
                "peak-flow-rejected-periods.rejected-periods; null when NRFA reports null metadata and empty list "
                "when explicitly empty, preserved verbatim without inferring endpoint inclusivity."
            ),
            reference_url=MISSING_AND_REJECTED_URL,
        ),
    ),
)

__all__ = (
    "AMAX_DOC_URL",
    "API_HELP_URL",
    "MISSING_AND_REJECTED_URL",
    "UK_NRFA_AMAX_REJECTION_SCHEMA",
    "UK_NRFA_OBSERVATIONS_SCHEMA",
    "UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA",
    "UK_NRFA_SERIES_METADATA_SCHEMA",
)
