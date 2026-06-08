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
from rivretrieve._internal.providers.ba_fhmzbih.observation_client import BaFhmzbihObservationClient
from rivretrieve._internal.providers.ba_fhmzbih.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("ba_fhmzbih")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = BaFhmzbihObservationClient


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
            description="Provider-native unit before conversion (m3/s for discharge, cm for stage, degC for temperature).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical unit after conversion (m3/s for discharge, m for stage, degC for temperature).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="raw_value",
            description="Value in native unit before any unit conversion (cm for stage; otherwise unchanged).",
            value_type="float",
            source_field="workbook Value column",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="native_unit_returned",
            description="Native unit of the workbook used for this product (m3/s, cm, or degC).",
            value_type="string",
            source_field="workbook #Unit Symbol header",
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
                "Always 'local_to_utc_conversion': the portal publishes naive local "
                "timestamps with no UTC offset; values are interpreted as Europe/Sarajevo "
                "local time (CET/CEST, EU daylight-saving rules) and converted to UTC."
            ),
            value_type="string",
            source_field="workbook #Timestamp column",
        ),
        AnnotationSchema(
            annotation_id="source_timezone",
            description="The IANA timezone used to interpret naive workbook timestamps ('Europe/Sarajevo').",
            value_type="string",
            source_field="inferred (provider documentation does not state an offset)",
        ),
        AnnotationSchema(
            annotation_id="aggregation",
            description=(
                "How the series was derived from hourly workbook rows: "
                "'instantaneous_hourly' (returned as-is) or "
                "'local_calendar_day_mean' (mean over each Europe/Sarajevo calendar day, "
                "anchored at local midnight before UTC conversion)."
            ),
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="station_group",
            description="The numbered station-group shard (1-10) under which the workbook was found.",
            value_type="string",
            source_field="discovered via URL probing",
        ),
        AnnotationSchema(
            annotation_id="provider_endpoint",
            description="The workbook URL used for this station-product series.",
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
