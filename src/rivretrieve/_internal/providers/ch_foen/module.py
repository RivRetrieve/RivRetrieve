from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact, load_packaged_catalogue_artifact
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import (
    AnnotationSchema,
    AnnotationTable,
    ObservationDataSchema,
    ObservationProvenance,
    ObservationRequest,
    ObservationResult,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import CatalogSource, OnIssue, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("ch_foen")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")


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
    return []


def series_annotation_schema() -> list[AnnotationSchema]:
    return []


def observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
) -> ObservationResult:
    issue = Issue(
        severity="error",
        code="observations_not_yet_implemented",
        message="ch_foen observation retrieval is not yet implemented",
        details={
            "stations": list(request.stations),
            "products": list(request.products),
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        },
        provider_id=PROVIDER_ID,
    )
    provenance = ObservationProvenance(
        source="placeholder",
        provider_id=PROVIDER_ID,
        rivretrieve_version=_rivretrieve_version(),
        catalogue_version=info().catalogue_version,
        request={
            "stations": list(request.stations),
            "products": list(request.products),
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        },
    )
    return ObservationResult(
        data=pl.DataFrame(schema=ObservationDataSchema.polars_schema),
        row_annotations=AnnotationTable(
            data=pl.DataFrame(schema=RowAnnotationTableSchema.polars_schema),
            schema=RowAnnotationTableSchema,
        ),
        series_annotations=AnnotationTable(
            data=pl.DataFrame(schema=SeriesAnnotationTableSchema.polars_schema),
            schema=SeriesAnnotationTableSchema,
        ),
        provenance=provenance,
        issues=(issue,),
        raw=None,
    )


@lru_cache
def _artifact() -> PackagedCatalogArtifact:
    return load_packaged_catalogue_artifact(_CATALOGUE_PATH, on_issue="raise")


def _reader() -> CatalogueReader:
    return CatalogueReader(_artifact(), PROVIDER_ID)


def _rivretrieve_version() -> str:
    from rivretrieve import __version__

    return __version__
