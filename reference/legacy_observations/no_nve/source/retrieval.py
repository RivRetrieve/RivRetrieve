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
from rivretrieve._internal.providers.no_nve.issue_codes import NoNveObservationIssueCodes
from rivretrieve._internal.providers.no_nve.observation_client import OBSERVATIONS_URL, NoNveObservationClient
from rivretrieve._internal.providers.no_nve.parser import parse_nve_response
from rivretrieve._internal.providers.no_nve.transform import (
    NoNveTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("no_nve")


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], NoNveObservationClient] = NoNveObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    issues: list[Issue] = []

    if not client.has_credentials():
        issues.append(
            _issue(
                NoNveObservationIssueCodes.AUTH_MISSING,
                "NVE API key not available. Set NVE_API_KEY environment variable.",
                None,
            )
        )
        result = ObservationResult(
            data=empty_data(),
            row_annotations=AnnotationTable(data=empty_row_annotations(), schema=RowAnnotationTableSchema),
            series_annotations=AnnotationTable(data=empty_series_annotations(), schema=SeriesAnnotationTableSchema),
            provenance=ObservationProvenance(
                source="live",
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
                decomposition=("station_product_cross_product", "yearly_or_monthly_windows"),
                endpoints=(OBSERVATIONS_URL,),
            ),
            issues=tuple(issues),
            raw=None,
        )
        apply_on_issue(result.issues, on_issue)
        return result

    series_results: list[NoNveTransformedSeries] = []
    calls_made: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []
    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)
            windows = _split_windows(request.start, request.end, policy.resolution_time)
            parsed_records: list[pl.DataFrame] = []
            used_endpoints: list[str] = []
            used_windows: list[tuple[str, str]] = []

            for begin_date, end_date in windows:
                reference_time = f"{begin_date}/{end_date}"
                endpoint = client.endpoint_for(station_id, policy.parameter_id, policy.resolution_time, reference_time)
                try:
                    resp = client.fetch_observations(
                        station_id, policy.parameter_id, policy.resolution_time, reference_time
                    )
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        issues.append(
                            _issue(
                                NoNveObservationIssueCodes.HTTP_NOT_FOUND,
                                "No data available for station/window (HTTP 404)",
                                {
                                    "station_id": station_id,
                                    "product_id": product_id,
                                    "begin_date": begin_date,
                                    "end_date": end_date,
                                    "endpoint": endpoint,
                                },
                            )
                        )
                        continue
                    failures += 1
                    issues.append(
                        _issue(
                            NoNveObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "NVE HydAPI request failed",
                            {
                                "station_id": station_id,
                                "product_id": product_id,
                                "begin_date": begin_date,
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
                            NoNveObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "NVE HydAPI request failed",
                            {
                                "station_id": station_id,
                                "product_id": product_id,
                                "begin_date": begin_date,
                                "end_date": end_date,
                                "endpoint": endpoint,
                                "exception_type": type(exc).__name__,
                            },
                        )
                    )
                    continue

                successes += 1
                retrieved_at = resp.retrieved_at
                raw_responses.append(
                    {
                        "endpoint": endpoint,
                        "station_id": station_id,
                        "product_id": product_id,
                        "parameter_id": policy.parameter_id,
                        "resolution_time": policy.resolution_time,
                        "begin_date": begin_date,
                        "end_date": end_date,
                        "retrieved_at": _iso_z(retrieved_at),
                    }
                )
                calls_made.append(
                    {
                        "endpoint": endpoint,
                        "station_id": station_id,
                        "product_id": product_id,
                        "parameter_id": policy.parameter_id,
                        "resolution_time": policy.resolution_time,
                        "begin_date": begin_date,
                        "end_date": end_date,
                        "retrieved_at": _iso_z(retrieved_at),
                    }
                )

                parsed = parse_nve_response(
                    resp.content,
                    station_id=station_id,
                    resolution_time=policy.resolution_time,
                )
                issues.extend(parsed.issues)
                if not parsed.records.is_empty():
                    parsed_records.append(parsed.records)
                    used_endpoints.append(endpoint)
                    used_windows.append((begin_date, end_date))

            all_records = pl.concat(parsed_records) if parsed_records else empty_data()
            filtered_records = _filter_date_range(all_records, request.start, request.end)

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
                        NoNveObservationIssueCodes.MISSING_DATA,
                        "No provider calls returned data for station-product request",
                        {"station_id": station_id, "product_id": product_id},
                    )
                )

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                NoNveObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more NVE HydAPI calls failed while others succeeded",
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
            decomposition=(
                "station_product_cross_product",
                "yearly_windows_for_daily_restime_1440",
                "monthly_windows_for_hourly_restime_60_and_instant_restime_0",
            ),
            endpoints=(OBSERVATIONS_URL,),
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses) if raw_responses else None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


# ---------------------------------------------------------------------------
# Windowing helpers
# ---------------------------------------------------------------------------


def _split_windows(start: datetime, end: datetime, resolution_time: int) -> list[tuple[str, str]]:
    """Generate request windows.

    Daily (resTime=1440): yearly windows in YYYY-MM-DD format.
    Hourly/instantaneous (resTime=60 or 0): monthly windows.

    NVE ReferenceTime uses ISO 8601 interval: 'YYYY-MM-DD/YYYY-MM-DD'.
    """
    windows: list[tuple[str, str]] = []
    if resolution_time == 1440:
        for year in range(start.year, end.year + 1):
            begin_str = f"{year}-01-01"
            end_str = f"{year}-12-31"
            windows.append((begin_str, end_str))
    else:
        # Use first-of-next-month as exclusive end so NVE returns the full last day.
        # e.g. January window: 2020-01-01/2020-02-01 (NVE end is exclusive midnight).
        current = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while current <= end:
            year = current.year
            month = current.month
            begin_str = f"{year}-{month:02d}-01"
            next_month = current.replace(year=year + 1, month=1) if month == 12 else current.replace(month=month + 1)
            end_str = f"{next_month.year}-{next_month.month:02d}-01"
            windows.append((begin_str, end_str))
            current = next_month
    return windows


def _filter_date_range(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    start_day = datetime(start_utc.year, start_utc.month, start_utc.day, tzinfo=UTC)
    end_next_day = datetime(end_utc.year, end_utc.month, end_utc.day, tzinfo=UTC) + timedelta(days=1)
    return records.filter((pl.col("time") >= start_day) & (pl.col("time") < end_next_day))


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _raw_payload(responses: list[dict[str, object]]) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.no_nve.raw-metadata+json",
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
    code: NoNveObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
