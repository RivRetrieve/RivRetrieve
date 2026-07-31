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
from rivretrieve._internal.providers.cz_chmi.observation_client import CzChmiObservationClient
from rivretrieve._internal.providers.cz_chmi.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("cz_chmi")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = CzChmiObservationClient


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
            annotation_id="ts_con_id",
            description="CHMI tsConID that produced the canonical observation value (e.g. QD, HD, TD, QH, HH).",
            value_type="string",
            source_field="tsConID",
        ),
        AnnotationSchema(
            annotation_id="native_unit",
            description="Provider-native unit before any conversion (m3/s for discharge; cm for stage; degC for temperature).",
            value_type="string",
            source_field="product metadata",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical product unit used for the observation value.",
            value_type="string",
            source_field="unit",
        ),
        AnnotationSchema(
            annotation_id="raw_value",
            description="Provider value before unit conversion.",
            value_type="float",
            source_field="VAL column",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="ts_con_id",
            description="CHMI tsConID for this station-product series.",
            value_type="string",
            source_field="product metadata",
        ),
        AnnotationSchema(
            annotation_id="url_type",
            description="URL template type used for retrieval: 'daily' or 'hourly'.",
            value_type="string",
            source_field="product metadata",
        ),
        AnnotationSchema(
            annotation_id="native_unit_returned",
            description="Native unit in the provider response.",
            value_type="string",
            source_field="product metadata",
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
            source_field="DT column",
        ),
        AnnotationSchema(
            annotation_id="returned_time_range_end",
            description="Last parsed timestamp returned for the station-product series.",
            value_type="datetime",
            source_field="DT column",
        ),
        AnnotationSchema(
            annotation_id="resolved_timezone",
            description="Timezone resolved for the series. Always UTC for cz_chmi (Z suffix in timestamps).",
            value_type="string",
            source_field="DT column",
        ),
        AnnotationSchema(
            annotation_id="timezone_source",
            description="How the timezone was determined. 'provider_timestamp_utc' means the Z suffix is authoritative.",
            value_type="string",
            source_field="DT column",
        ),
        AnnotationSchema(
            annotation_id="provider_endpoints",
            description="Provider API endpoints called for this series (JSON list), without credentials.",
            value_type="json",
            source_field="CHMI opendata URL",
        ),
        AnnotationSchema(
            annotation_id="requested_years",
            description="Calendar years requested from the provider (JSON list).",
            value_type="json",
            source_field="date range decomposition",
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
