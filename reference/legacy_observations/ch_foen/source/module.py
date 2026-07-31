from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact, load_packaged_catalogue_artifact
from rivretrieve._internal.observations import (
    AnnotationSchema,
    ObservationRequest,
    ObservationResult,
)
from rivretrieve._internal.primitives import CatalogSource, OnIssue, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.providers.ch_foen.observation_client import ChFoenObservationClient
from rivretrieve._internal.providers.ch_foen.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("ch_foen")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = ChFoenObservationClient


def info() -> ProviderInfo:
    return ProviderInfo.from_row(_artifact().provider_info)


def products(
    *,
    source: CatalogSource = "packaged",
    observed_property: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    return _reader().read_products(
        source=source,
        observed_property=observed_property,
        frequency=frequency,
        statistic=statistic,
        on_issue=on_issue,
    )


def stations(
    *,
    source: CatalogSource = "packaged",
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    return _reader().read_stations(source=source, on_issue=on_issue)


def station_products(
    stations: Sequence[str] | None = None,
    *,
    source: CatalogSource = "packaged",
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    return _reader().read_station_products(stations, source=source, on_issue=on_issue)


def row_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="native_field",
            description="Provider-native field that produced the canonical observation value.",
            value_type="string",
            source_field="_field",
        ),
        AnnotationSchema(
            annotation_id="native_unit",
            description="Provider-native unit before any conversion.",
            value_type="string",
            source_field="_field",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical product unit used for the observation value.",
            value_type="string",
            source_field="unit",
        ),
        AnnotationSchema(
            annotation_id="source_endpoint_or_query",
            description="Endpoint or query identity that produced the row, without credentials.",
            value_type="string",
            source_field="Flux query / endpoint",
        ),
        AnnotationSchema(
            annotation_id="raw_value",
            description="Provider value before conversion or conflict handling.",
            value_type="float",
            source_field="_value",
        ),
        AnnotationSchema(
            annotation_id="alternative_native_field",
            description="Non-selected same-timestamp native field preserved for overlap handling.",
            value_type="string",
            source_field="_field",
        ),
        AnnotationSchema(
            annotation_id="alternative_raw_value",
            description="Non-selected same-timestamp raw value preserved for conflict handling.",
            value_type="float",
            source_field="_value",
        ),
        AnnotationSchema(
            annotation_id="alternative_native_unit",
            description="Provider-native unit for the non-selected same-timestamp value.",
            value_type="string",
            source_field="_field",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="preferred_source",
            description="Configured preferred native field for the station-product request.",
            value_type="string",
            source_field="preferred_parameter",
        ),
        AnnotationSchema(
            annotation_id="fallback_source_used",
            description="Whether fallback native fields contributed to the returned series.",
            value_type="boolean",
            source_field="parsed native fields",
        ),
        AnnotationSchema(
            annotation_id="native_unit_returned",
            description="Native units actually present in the provider response.",
            value_type="string",
            source_field="parsed native fields",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical product unit returned in observation data.",
            value_type="string",
            source_field="unit",
        ),
        AnnotationSchema(
            annotation_id="returned_time_range_start",
            description="First parsed timestamp returned for the station-product series.",
            value_type="datetime",
            source_field="_time",
        ),
        AnnotationSchema(
            annotation_id="returned_time_range_end",
            description="Last parsed timestamp returned for the station-product series.",
            value_type="datetime",
            source_field="_time",
        ),
        AnnotationSchema(
            annotation_id="resolved_timezone",
            description="Timezone resolved from explicit provider timestamps.",
            value_type="string",
            source_field="_time",
        ),
        AnnotationSchema(
            annotation_id="timezone_mismatch_flag",
            description="Whether timestamps contradicted the expected explicit UTC shape.",
            value_type="boolean",
            source_field="_time",
        ),
        AnnotationSchema(
            annotation_id="provider_endpoint",
            description="Provider query endpoint without token or authorization metadata.",
            value_type="string",
            source_field="INFLUX_URL",
        ),
        AnnotationSchema(
            annotation_id="provider_query_fields",
            description="Requested provider-native fields without credential metadata.",
            value_type="json",
            source_field="Flux _field filter",
        ),
    ]


def observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
) -> ObservationResult:
    return retrieve_observations(
        request,
        on_issue=on_issue,
        client_factory=_observation_client_factory,
        rivretrieve_version=_rivretrieve_version(),
        catalogue_version=info().catalogue_version,
    )


@lru_cache
def _artifact() -> PackagedCatalogArtifact:
    return load_packaged_catalogue_artifact(_CATALOGUE_PATH, on_issue="raise")


def _reader() -> CatalogueReader:
    return CatalogueReader(_artifact(), PROVIDER_ID)


def _rivretrieve_version() -> str:
    from rivretrieve import __version__

    return __version__
