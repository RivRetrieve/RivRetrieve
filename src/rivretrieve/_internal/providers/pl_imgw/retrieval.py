from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.issues import Issue, apply_on_issue
from rivretrieve._internal.observations import (
    AnnotationTable,
    ObservationProvenance,
    ObservationRequest,
    ObservationResult,
    RawPayload,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.providers.pl_imgw.issue_codes import PlImgwObservationIssueCodes
from rivretrieve._internal.providers.pl_imgw.observation_client import (
    CACHE_FILENAME,
    ImgwCacheClient,
)
from rivretrieve._internal.providers.pl_imgw.transform import (
    PlImgwTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("pl_imgw")


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], ImgwCacheClient] = ImgwCacheClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    issues: list[Issue] = []

    # --- Ensure local Parquet cache is available --------------------------
    cache_path, cache_issues = client.ensure_cache()
    issues.extend(cache_issues)

    if cache_path is None:
        result = ObservationResult(
            data=empty_data(),
            row_annotations=AnnotationTable(data=empty_row_annotations(), schema=RowAnnotationTableSchema),
            series_annotations=AnnotationTable(
                data=empty_series_annotations(), schema=SeriesAnnotationTableSchema
            ),
            provenance=ObservationProvenance(
                source="local",
                provider_id=PROVIDER_ID,
                rivretrieve_version=rivretrieve_version,
                catalogue_version=catalogue_version,
                requested_at=requested_at,
                retrieved_at=None,
                request={
                    "stations": list(request.stations),
                    "products": list(request.products),
                    "start": request.start.isoformat(),
                    "end": request.end.isoformat(),
                },
                calls_made=(),
                time_windows=(),
                decomposition=("parquet_cache_query",),
                endpoints=(CACHE_FILENAME,),
            ),
            issues=tuple(issues),
            raw=None,
        )
        apply_on_issue(result.issues, on_issue)
        return result

    # --- Query cache for all requested stations at once -------------------
    station_ids = frozenset(request.stations)
    all_records = client.query(cache_path, station_ids, request.start, request.end)

    # --- Assemble per-station-product series ------------------------------
    series_results: list[PlImgwTransformedSeries] = []

    for station_id in request.stations:
        station_records = (
            all_records.filter(pl.col("station_id") == station_id)
            if not all_records.is_empty()
            else pl.DataFrame(schema=all_records.schema)
        )

        for product_id in request.products:
            policy = resolve_product_policy(product_id)

            if station_records.is_empty():
                issues.append(
                    _issue(
                        PlImgwObservationIssueCodes.MISSING_DATA,
                        "No data in cache for station in the requested date range",
                        {
                            "station_id": station_id,
                            "product_id": product_id,
                            "start": request.start.isoformat(),
                            "end": request.end.isoformat(),
                        },
                    )
                )
                series_results.append(
                    PlImgwTransformedSeries(
                        data=empty_data(),
                        row_annotations=empty_row_annotations(),
                        series_annotations=empty_series_annotations(),
                        issues=(),
                    )
                )
            else:
                transformed = transform_series(
                    station_records,
                    station_id=station_id,
                    policy=policy,
                    cache_path=cache_path,
                )
                series_results.append(transformed)

    if series_results:
        data = pl.concat([s.data for s in series_results], how="vertical")
        row_annotations = pl.concat([s.row_annotations for s in series_results], how="vertical")
        series_annotations = pl.concat([s.series_annotations for s in series_results], how="vertical")
        issues.extend(issue for s in series_results for issue in s.issues)
    else:
        data = empty_data()
        row_annotations = empty_row_annotations()
        series_annotations = empty_series_annotations()

    data = data.sort(["station_id", "product_id", "time"]) if not data.is_empty() else data

    result = ObservationResult(
        data=data,
        row_annotations=AnnotationTable(data=row_annotations, schema=RowAnnotationTableSchema),
        series_annotations=AnnotationTable(
            data=series_annotations, schema=SeriesAnnotationTableSchema
        ),
        provenance=ObservationProvenance(
            source="local",
            provider_id=PROVIDER_ID,
            rivretrieve_version=rivretrieve_version,
            catalogue_version=catalogue_version,
            requested_at=requested_at,
            retrieved_at=datetime.now(UTC),
            request={
                "stations": list(request.stations),
                "products": list(request.products),
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
            calls_made=(),
            time_windows=(),
            decomposition=("parquet_cache_query",),
            endpoints=(str(cache_path),),
        ),
        issues=tuple(issues),
        raw=_raw_payload(cache_path),
    )
    apply_on_issue(result.issues, on_issue)
    return result


def _raw_payload(cache_path: Path) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.pl_imgw.cache-metadata+json",
        content=None,
        metadata=json.dumps({"cache_path": str(cache_path)}, separators=(",", ":")),
    )


def _issue(
    code: PlImgwObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
