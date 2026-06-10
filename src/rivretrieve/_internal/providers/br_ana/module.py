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
from rivretrieve._internal.providers.br_ana.observation_client import BrAnaObservationClient
from rivretrieve._internal.providers.br_ana.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("br_ana")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = BrAnaObservationClient


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
            description="Provider-native unit before any conversion (m3/s for discharge, cm for stage).",
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
            source_field="Vazao_DD / Cota_DD / Vazao_Adotada / Cota_Adotada / Temperatura_Agua",
        ),
        AnnotationSchema(
            annotation_id="quality_flag",
            description=(
                "ANA telemetric quality flag, mapped from the provider's numeric "
                "<Field>_Status code (0=ok, 1=suspeito, 2=ruim) to canonical strings "
                "'ok'/'suspect'/'poor' ('unknown' for unrecognised codes). Only present "
                "for instantaneous/telemetric products (discharge_instantaneous, "
                "stage_instantaneous, water_temperature_instantaneous); the legacy daily "
                "columnar series (discharge_daily_mean, stage_daily_mean) carry no "
                "quality flags in the provider response."
            ),
            value_type="string",
            source_field="Vazao_Adotada_Status / Cota_Adotada_Status / Temperatura_Agua_Status",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
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
            description="Output timezone (always UTC for br_ana).",
            value_type="string",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="timezone_source",
            description=(
                "How timezone was resolved. 'date_only_utc_midnight' — daily columnar "
                "products (discharge_daily_mean, stage_daily_mean): ANA provides no "
                "explicit timezone; date-only values interpreted as UTC midnight. "
                "'naive_local_brt_minus_3' — telemetric/instantaneous products: "
                "Data_Hora_Medicao carries genuine time-of-day but no explicit timezone; "
                "interpreted as Brasília Standard Time (UTC-3) and converted to UTC."
            ),
            value_type="string",
            source_field="Data_Hora_Dado + day column / Data_Hora_Medicao",
        ),
        AnnotationSchema(
            annotation_id="date_only_timestamp_flag",
            description=(
                "'true' for the daily columnar products (discharge_daily_mean, "
                "stage_daily_mean): timestamps are reconstructed from year/month/day "
                "and interpreted as UTC midnight (T00:00:00Z). 'false' for telemetric/"
                "instantaneous products, whose timestamps carry genuine time-of-day "
                "information (see naive_local_timestamp issue and timezone_source)."
            ),
            value_type="boolean",
            source_field="Data_Hora_Dado + day column / Data_Hora_Medicao",
        ),
        AnnotationSchema(
            annotation_id="provider_endpoints",
            description="Provider query endpoints used for this station-product series.",
            value_type="json",
            source_field="URL",
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
