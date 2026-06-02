from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import polars as pl
import requests

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
from rivretrieve._internal.providers.th_thaiwater.issue_codes import ThThaiWaterObservationIssueCodes
from rivretrieve._internal.providers.th_thaiwater.observation_client import ThThaiWaterObservationClient
from rivretrieve._internal.providers.th_thaiwater.parser import parse_th_thaiwater_observation_json
from rivretrieve._internal.providers.th_thaiwater.transform import (
    ThThaiWaterTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("th_thaiwater")
MAX_WINDOW_DAYS = 365


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], ThThaiWaterObservationClient] = ThThaiWaterObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    series_results: list[ThThaiWaterTransformedSeries] = []
    calls_made: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []
    issues: list[Issue] = []
    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)
            windows = _split_windows(request.start, request.end)
            parsed_records: list[pl.DataFrame] = []
            used_endpoints: list[str] = []
            used_windows: list[tuple[str, str]] = []

            for start_date, end_date in windows:
                endpoint = client.endpoint_for(station_id, start_date, end_date)
                try:
                    response = client.fetch(station_id, start_date, end_date)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        issues.append(
                            _issue(
                                ThThaiWaterObservationIssueCodes.HTTP_NOT_FOUND,
                                "No data available for station/window (HTTP 404)",
                                {
                                    "station_id": station_id,
                                    "product_id": product_id,
                                    "start_date": start_date,
                                    "end_date": end_date,
                                    "endpoint": endpoint,
                                },
                            )
                        )
                        continue
                    failures += 1
                    issues.append(
                        _issue(
                            ThThaiWaterObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "th_thaiwater provider request failed",
                            {
                                "station_id": station_id,
                                "product_id": product_id,
                                "start_date": start_date,
                                "end_date": end_date,
                                "endpoint": endpoint,
                                "exception_type": type(exc).__name__,
                            },
                        )
                    )
                    continue
                except (requests.RequestException, OSError, TimeoutError) as exc:
                    failures += 1
                    issues.append(
                        _issue(
                            ThThaiWaterObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "th_thaiwater provider request failed",
                            {
                                "station_id": station_id,
                                "product_id": product_id,
                                "start_date": start_date,
                                "end_date": end_date,
                                "endpoint": endpoint,
                                "exception_type": type(exc).__name__,
                            },
                        )
                    )
                    continue

                successes += 1
                retrieved_at = response.retrieved_at
                raw_responses.append(
                    {
                        "endpoint": endpoint,
                        "station_id": station_id,
                        "product_id": product_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "status_code": response.status_code,
                        "retrieved_at": _iso_z(retrieved_at),
                        "byte_count": len(response.content),
                    }
                )
                calls_made.append(
                    {
                        "endpoint": endpoint,
                        "station_id": station_id,
                        "product_id": product_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "status_code": response.status_code,
                        "retrieved_at": _iso_z(retrieved_at),
                    }
                )
                parsed = parse_th_thaiwater_observation_json(
                    response.content,
                    station_id=station_id,
                )
                issues.extend(parsed.issues)
                if not parsed.records.is_empty():
                    parsed_records.append(parsed.records)
                    used_endpoints.append(endpoint)
                    used_windows.append((start_date, end_date))

            filtered_records = _filter_date_range(
                pl.concat(parsed_records) if parsed_records else empty_data(),
                request.start,
                request.end,
            )

            if not filtered_records.is_empty():
                transformed = transform_series(
                    filtered_records,
                    station_id=station_id,
                    policy=policy,
                    windows=tuple(used_windows),
                    endpoints=tuple(used_endpoints),
                )
                series_results.append(transformed)
            elif successes == 0 and failures == 0:
                issues.append(
                    _issue(
                        ThThaiWaterObservationIssueCodes.MISSING_DATA,
                        "No provider calls returned data for station-product request",
                        {"station_id": station_id, "product_id": product_id},
                    )
                )

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                ThThaiWaterObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more th_thaiwater provider calls failed while other calls succeeded",
                {"failed_calls": failures, "successful_calls": successes},
            )
        )

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

    retrieved_at_final = _latest_retrieved_at(raw_responses)

    result = ObservationResult(
        data=data,
        row_annotations=AnnotationTable(data=row_annotations, schema=RowAnnotationTableSchema),
        series_annotations=AnnotationTable(data=series_annotations, schema=SeriesAnnotationTableSchema),
        provenance=ObservationProvenance(
            source="live",
            provider_id=PROVIDER_ID,
            rivretrieve_version=rivretrieve_version,
            catalogue_version=catalogue_version,
            requested_at=requested_at,
            retrieved_at=retrieved_at_final,
            request={
                "stations": list(request.stations),
                "products": list(request.products),
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
            calls_made=tuple(calls_made),
            time_windows=(),
            decomposition=("station_product_cross_product", "365_day_windows"),
            endpoints=("https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph",),
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses) if raw_responses else None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


def _split_windows(start: datetime, end: datetime) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    current = start
    while current <= end:
        window_end = min(end, current + timedelta(days=MAX_WINDOW_DAYS - 1))
        windows.append((current.strftime("%Y-%m-%d"), window_end.strftime("%Y-%m-%d")))
        current = window_end + timedelta(days=1)
    return windows


def _filter_date_range(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    """Keep rows whose UTC timestamp falls within [start_day_utc, end_next_day_utc).

    ThaiWater timestamps are in Asia/Bangkok and have already been converted to UTC
    during parsing. We use an inclusive-start exclusive-end UTC day range so that
    Bangkok-midnight UTC (17:00 UTC previous day) is included for daily products.
    """
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    # Use Bangkok dates to determine day boundaries, matching the aggregation logic
    from zoneinfo import ZoneInfo

    bangkok = ZoneInfo("Asia/Bangkok")
    start_bkk = start_utc.astimezone(bangkok)
    end_bkk = end_utc.astimezone(bangkok)
    start_day_utc = datetime(start_bkk.year, start_bkk.month, start_bkk.day, tzinfo=bangkok).astimezone(UTC)
    end_next_day_utc = (
        datetime(end_bkk.year, end_bkk.month, end_bkk.day, tzinfo=bangkok) + timedelta(days=1)
    ).astimezone(UTC)
    return records.filter((pl.col("time") >= start_day_utc) & (pl.col("time") < end_next_day_utc))


def _raw_payload(responses: list[dict[str, object]]) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.th_thaiwater.raw-metadata+json",
        content=None,
        metadata=json.dumps(responses, sort_keys=True, separators=(",", ":")),
    )


def _latest_retrieved_at(responses: list[dict[str, object]]) -> datetime | None:
    values: list[datetime] = []
    for resp in responses:
        val = resp.get("retrieved_at")
        if isinstance(val, str):
            with contextlib.suppress(ValueError):
                values.append(datetime.fromisoformat(val.replace("Z", "+00:00")))
    return max(values) if values else None


def _iso_z(value: datetime) -> str:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue(
    code: ThThaiWaterObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
