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
from rivretrieve._internal.providers.pl_imgw.observation_client import ImgwCacheClient, ImgwCacheStatus
from rivretrieve._internal.providers.pl_imgw.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("pl_imgw")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = ImgwCacheClient


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
            description="Provider-native unit before conversion (cm for stage, m3/s for discharge, degC for temp).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="converted_unit",
            description="Canonical unit after conversion (m for stage, m3/s for discharge, degC for temp).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="raw_value",
            description="Value in native unit before any unit conversion.",
            value_type="float",
            source_field="IMGW CSV column",
        ),
        AnnotationSchema(
            annotation_id="timezone_source",
            description="Always 'date_only_utc_midnight': IMGW provides year/month/day integers only.",
            value_type="string",
            source_field="IMGW CSV date columns",
        ),
        AnnotationSchema(
            annotation_id="date_only_timestamp_flag",
            description="Always 'true': IMGW timestamps are date-only, interpreted as UTC midnight.",
            value_type="boolean",
            source_field="IMGW CSV date columns",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="source_column",
            description="IMGW CSV column name used for this product (level_cm, flow_m3s, temp_c).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="native_unit_returned",
            description="Native unit in IMGW CSV for this product.",
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
            annotation_id="timezone_source",
            description="Always 'date_only_utc_midnight'.",
            value_type="string",
            source_field="IMGW CSV date columns",
        ),
        AnnotationSchema(
            annotation_id="date_only_timestamp_flag",
            description="Always 'true'.",
            value_type="boolean",
            source_field="IMGW CSV date columns",
        ),
        AnnotationSchema(
            annotation_id="resolved_timezone",
            description="Output timezone (always UTC).",
            value_type="string",
            source_field="time column",
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
            annotation_id="cache_source",
            description="Absolute path to the Parquet cache file used for this observation query.",
            value_type="string",
            source_field="cache path",
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


def cache_status() -> ImgwCacheStatus:
    """Return the status of the local IMGW all-daily Parquet cache.

    Does not trigger a download. Safe to call before making any observation
    request to check whether the cache is present and how old it is.

    Examples
    --------
    >>> import rivretrieve as rr
    >>> status = rr.provider("pl_imgw").cache_status()
    >>> print(status.exists, status.age_days, status.size_mb, status.stale)
    """
    return _observation_client_factory().cache_status()


def refresh_cache() -> list:
    """Force rebuild of the IMGW all-daily Parquet cache.

    Deletes any existing cached file and downloads all IMGW yearly ZIP files
    from 1951 to the current year. Blocks until complete.

    Returns a list of structured ``Issue`` objects.

    Examples
    --------
    >>> import rivretrieve as rr
    >>> issues = rr.provider("pl_imgw").refresh_cache()
    >>> for i in issues:
    ...     print(f"[{i.severity}] {i.code}: {i.message}")
    """
    return _observation_client_factory().refresh_cache()


@lru_cache
def _artifact() -> PackagedCatalogArtifact:
    return load_packaged_catalogue_artifact(_CATALOGUE_PATH, on_issue="raise")


def _reader() -> CatalogueReader:
    return CatalogueReader(_artifact(), PROVIDER_ID)


def _rivretrieve_version() -> str:
    from rivretrieve import __version__

    return __version__
