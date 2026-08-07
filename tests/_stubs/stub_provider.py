from __future__ import annotations

from collections.abc import Callable, Sequence

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
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
from rivretrieve._internal.primitives import CatalogSource, OnIssue
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.results import CatalogResult

_PROVIDER_INFO_ROW = {
    "provider_id": "stub_provider",
    "name": "stub_provider Provider",
    "live_stations": False,
    "live_products": False,
    "live_station_products": False,
    "bulk_observations": "none",
    "catalogue_version": "2026.01",
}


def info() -> ProviderInfo:
    return ProviderInfo.from_row(_PROVIDER_INFO_ROW)


def products(
    *,
    source: CatalogSource = "packaged",
    observed_property: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    raise NotImplementedError("deferred to M2 step 02")


def stations(
    *,
    source: CatalogSource = "packaged",
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    raise NotImplementedError("deferred to M2 step 02")


def station_products(
    stations: Sequence[str] | None = None,
    *,
    source: CatalogSource = "packaged",
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    raise NotImplementedError("deferred to M2 step 02")


def row_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="stub.quality",
            description="Stub row quality flag.",
            value_type="string",
            allowed_values=("good", "suspect"),
            source_field="quality",
        )
    ]


def series_annotation_schema() -> list[AnnotationSchema]:
    return [
        AnnotationSchema(
            annotation_id="stub.native_unit",
            description="Stub native unit returned for the series.",
            value_type="string",
            allowed_values=("m", "m3/s"),
            source_field="unit",
        )
    ]


def observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
) -> ObservationResult:
    _ = on_issue
    known_stations = {"station-1", "station-2"}
    known_products = {"level", "flow", "level_hourly", "level_max"}

    rows: list[dict[str, object]] = []
    row_annotations: list[dict[str, object]] = []
    series_annotations: list[dict[str, object]] = []
    value = 1.0

    for station_id in request.stations:
        for product_id in request.products:
            if station_id not in known_stations or product_id not in known_products:
                continue

            unit = "m3/s" if product_id == "flow" else "m"
            series_annotations.append(
                {
                    "station_id": station_id,
                    "product_id": product_id,
                    "annotation": "stub.native_unit",
                    "value": unit,
                }
            )
            for observed_at in (request.start, request.end):
                rows.append(
                    {
                        "time": observed_at,
                        "time_zone": "unknown",
                        "station_id": station_id,
                        "product_id": product_id,
                        "value": value,
                    }
                )
                row_annotations.append(
                    {
                        "time": observed_at,
                        "station_id": station_id,
                        "product_id": product_id,
                        "annotation": "stub.quality",
                        "value": "good",
                    }
                )
                value += 1.0

    return ObservationResult(
        data=pl.DataFrame(rows, schema=ObservationDataSchema.polars_schema),
        row_annotations=AnnotationTable(
            pl.DataFrame(row_annotations, schema=RowAnnotationTableSchema.polars_schema),
            RowAnnotationTableSchema,
        ),
        series_annotations=AnnotationTable(
            pl.DataFrame(series_annotations, schema=SeriesAnnotationTableSchema.polars_schema),
            SeriesAnnotationTableSchema,
        ),
        provenance=ObservationProvenance(
            source="stub",
            provider_id=request.provider_id,
            catalogue_version="2026.01",
            request={
                "provider_id": str(request.provider_id),
                "stations": list(request.stations),
                "products": list(request.products),
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
        ),
        issues=(),
        raw=None,
    )


def build_artifact(
    factory: Callable[..., PackagedCatalogArtifact],
) -> PackagedCatalogArtifact:
    return factory("stub_provider")
