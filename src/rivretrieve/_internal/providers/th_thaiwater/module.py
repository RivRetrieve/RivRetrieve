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
from rivretrieve._internal.providers.th_thaiwater.observation_client import ThThaiWaterObservationClient
from rivretrieve._internal.providers.th_thaiwater.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("th_thaiwater")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = ThThaiWaterObservationClient


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
            description="Provider-native JSON field ('value_field' for stage, 'discharge_field' for discharge).",
            value_type="string",
            source_field="graph_data field",
        ),
        AnnotationSchema(
            annotation_id="native_unit",
            description="Provider-native unit before any conversion.",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical product unit used for the observation value.",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="raw_value",
            description="Provider value before any transformation (instantaneous products only).",
            value_type="float",
            source_field="graph_data value",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="native_field",
            description="Provider-native JSON field used for this station-product series.",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="native_unit_returned",
            description="Native units present in the provider response.",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical product unit returned in observation data.",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="aggregate_daily",
            description="Whether Bangkok-day aggregation was applied (true/false).",
            value_type="boolean",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="returned_time_range_start",
            description="First parsed UTC timestamp returned for the station-product series.",
            value_type="datetime",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="returned_time_range_end",
            description="Last parsed UTC timestamp returned for the station-product series.",
            value_type="datetime",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="resolved_timezone",
            description="Output timezone (always UTC after Bangkok→UTC conversion).",
            value_type="string",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="timezone_source",
            description="How timezone was resolved: 'local_to_utc_conversion' for ThaiWater.",
            value_type="string",
            source_field="datetime field",
        ),
        AnnotationSchema(
            annotation_id="local_timezone",
            description="Source timezone of provider timestamps before UTC conversion.",
            value_type="string",
            source_field="datetime field",
        ),
        AnnotationSchema(
            annotation_id="provider_endpoints",
            description="Provider query endpoints used for this station-product series.",
            value_type="json",
            source_field="waterlevel_graph URL",
        ),
        AnnotationSchema(
            annotation_id="requested_windows",
            description="Date windows (start_date, end_date pairs) used in provider requests.",
            value_type="json",
            source_field="request decomposition",
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
