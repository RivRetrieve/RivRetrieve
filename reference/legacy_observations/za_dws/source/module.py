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
from rivretrieve._internal.providers.za_dws.observation_client import ZaDwsObservationClient
from rivretrieve._internal.providers.za_dws.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("za_dws")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = ZaDwsObservationClient


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
            annotation_id="native_unit",
            description=(
                "Provider-native unit before any conversion "
                "(m3/s for discharge, m for stage; no conversions apply for za_dws)."
            ),
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical unit after conversion (same as native_unit for za_dws).",
            value_type="string",
            source_field="product policy",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="native_unit_returned",
            description="Native unit of the DWS column used for this product (m3/s or m).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical unit after conversion.",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="returned_time_range_start",
            description="First UTC timestamp returned for this series.",
            value_type="datetime",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="returned_time_range_end",
            description="Last UTC timestamp returned for this series.",
            value_type="datetime",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="resolved_timezone",
            description="Output timezone (always UTC).",
            value_type="string",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="timezone_source",
            description=(
                "How the output UTC timestamp was derived: "
                "'date_only_utc_midnight' for discharge_daily_mean (date-only YYYYMMDD interpreted as UTC midnight); "
                "'local_to_utc_conversion' for instantaneous products (SAST = Africa/Johannesburg, UTC+2, "
                "no DST, converted to UTC)."
            ),
            value_type="string",
            source_field="product policy + DWS response format",
        ),
        AnnotationSchema(
            annotation_id="source_timezone",
            description=(
                "IANA timezone used to interpret naive timestamps for instantaneous products "
                "('Africa/Johannesburg'). Null for date_only_utc_midnight products."
            ),
            value_type="string",
            source_field="inferred (DWS operates in SAST; no offset in response)",
        ),
        AnnotationSchema(
            annotation_id="provider_endpoint",
            description="The DWS HyData.aspx URL used for this station/product series.",
            value_type="string",
            source_field="URL",
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
