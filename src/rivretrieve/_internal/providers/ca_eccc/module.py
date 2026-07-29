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
from rivretrieve._internal.providers.ca_eccc.config import config as config
from rivretrieve._internal.providers.ca_eccc.observation_client import CacheStatus, HydatClient
from rivretrieve._internal.providers.ca_eccc.parse import parse as parse
from rivretrieve._internal.providers.ca_eccc.retrieval import retrieve_observations
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("ca_eccc")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
_observation_client_factory = HydatClient


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
            description="Provider-native unit for this observation (m or m3/s; no conversion applied).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="raw_value",
            description="Value as stored in HYDAT (identical to value; no unit conversion needed).",
            value_type="float",
            source_field="FLOW or LEVEL day column",
        ),
        AnnotationSchema(
            annotation_id="quality_flag",
            description=(
                "HYDAT quality symbol code from FLOW_SYMBOL or LEVEL_SYMBOL column. "
                "Empty string means no flag. Known codes: A=Estimated, B=Ice conditions, "
                "D=Dry, E=Estimated (ice-affected), R=Revised, S=Sample."
            ),
            value_type="string",
            source_field="FLOW_SYMBOL or LEVEL_SYMBOL day column",
        ),
        AnnotationSchema(
            annotation_id="quality_description",
            description="English description of the quality flag from HYDAT DATA_SYMBOLS table.",
            value_type="string",
            source_field="DATA_SYMBOLS.SYMBOL_EN",
        ),
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="hydat_table",
            description="HYDAT table queried for this product (DLY_FLOWS or DLY_LEVELS).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="hydat_value_prefix",
            description="Column prefix used in the HYDAT table (FLOW or LEVEL).",
            value_type="string",
            source_field="product policy",
        ),
        AnnotationSchema(
            annotation_id="hydat_source",
            description="Filename of the HYDAT SQLite database used (date-stamped, e.g. Hydat_sqlite3_20240101.sqlite3).",
            value_type="string",
            source_field="SQLite filename",
        ),
        AnnotationSchema(
            annotation_id="query_years",
            description="[start_year, end_year] range passed to the HYDAT SQL query.",
            value_type="json",
            source_field="request decomposition",
        ),
        AnnotationSchema(
            annotation_id="native_unit_returned",
            description="Native unit in HYDAT for this product.",
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
            description="Output timezone (always UTC for ca_eccc).",
            value_type="string",
            source_field="time column",
        ),
        AnnotationSchema(
            annotation_id="timezone_source",
            description=(
                "Always 'date_only_utc_midnight': HYDAT stores YEAR, MONTH, DAY integers; "
                "interpreted as UTC midnight (T00:00:00Z)."
            ),
            value_type="string",
            source_field="YEAR/MONTH/DAY columns",
        ),
        AnnotationSchema(
            annotation_id="date_only_timestamp_flag",
            description="Always 'true': HYDAT timestamps are date-only integers, interpreted as UTC midnight.",
            value_type="boolean",
            source_field="YEAR/MONTH/DAY columns",
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


def cache_status() -> CacheStatus:
    """Return the status of the local HYDAT SQLite cache.

    Does not trigger a download. Safe to call before making any observation
    request to check whether the database is present and how old it is.

    Examples
    --------
    >>> import rivretrieve as rr
    >>> status = rr.provider("ca_eccc").cache_status()
    >>> print(status.exists, status.age_days, status.size_mb, status.stale)
    """
    return _observation_client_factory().cache_status()


def refresh_cache() -> list:
    """Force re-download of the HYDAT SQLite database.

    Deletes any existing cached file and downloads the latest quarterly release
    from ECCC (~1 GB zip). Blocks until complete (may take several minutes).

    Returns a list of structured ``Issue`` objects describing what happened
    (download started, complete, or failed).

    Examples
    --------
    >>> import rivretrieve as rr
    >>> issues = rr.provider("ca_eccc").refresh_cache()
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
