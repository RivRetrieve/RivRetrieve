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
from rivretrieve._internal.providers.fr_hubeau.observation_client import FrHubeauObservationClient
from rivretrieve._internal.providers.fr_hubeau.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("fr_hubeau")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = FrHubeauObservationClient


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
            annotation_id="grandeur_code",
            description="Hubeau grandeur_hydro_elab code (QmnJ, HIXnJ) for this observation.",
            value_type="string",
            source_field="grandeur_hydro_elab",
        ),
        AnnotationSchema(
            annotation_id="native_unit",
            description="Provider-native unit before any conversion (l/s or mm).",
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
            description="Provider value before unit conversion (in native unit).",
            value_type="float",
            source_field="resultat_obs_elab",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="grandeur_code",
            description="Hubeau grandeur_hydro_elab code used for this station-product series.",
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
            annotation_id="returned_time_range_start",
            description="First UTC timestamp returned for the station-product series.",
            value_type="datetime",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="returned_time_range_end",
            description="Last UTC timestamp returned for the station-product series.",
            value_type="datetime",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="resolved_timezone",
            description="Output timezone (always UTC for fr_hubeau).",
            value_type="string",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="date_only_timestamp_flag",
            description="Always 'true': Hubeau date_obs_elab is date-only, interpreted as UTC midnight.",
            value_type="boolean",
            source_field="date_obs_elab",
        ),
        AnnotationSchema(
            annotation_id="timezone_source",
            description="How timezone was resolved: 'date_only_utc_midnight' for fr_hubeau.",
            value_type="string",
            source_field="date_obs_elab",
        ),
        AnnotationSchema(
            annotation_id="provider_endpoints",
            description="Provider query endpoints used for this station-product series.",
            value_type="json",
            source_field="obs_elab URL",
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
