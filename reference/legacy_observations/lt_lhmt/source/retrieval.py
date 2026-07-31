from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime

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
from rivretrieve._internal.providers.lt_lhmt.issue_codes import LtLhmtObservationIssueCodes
from rivretrieve._internal.providers.lt_lhmt.observation_client import LtLhmtObservationClient
from rivretrieve._internal.providers.lt_lhmt.parser import parse_lt_lhmt_observation_json
from rivretrieve._internal.providers.lt_lhmt.transform import (
    LtLhmtTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("lt_lhmt")


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], LtLhmtObservationClient] = LtLhmtObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    series_results: list[LtLhmtTransformedSeries] = []
    calls_made: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []
    issues: list[Issue] = []
    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)
            year_months = _iter_year_months(request.start, request.end)
            parsed_records: list[pl.DataFrame] = []
            endpoints: list[str] = []
            date_only_seen = False

            for year_month in year_months:
                endpoint = client.endpoint_for(station_id, year_month)
                try:
                    response = client.fetch(station_id, year_month)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        issues.append(
                            _issue(
                                LtLhmtObservationIssueCodes.HTTP_NOT_FOUND,
                                "No data available for station/month (HTTP 404)",
                                {
                                    "station_id": station_id,
                                    "product_id": product_id,
                                    "year_month": year_month,
                                    "endpoint": endpoint,
                                },
                            )
                        )
                        continue
                    failures += 1
                    issues.append(
                        _issue(
                            LtLhmtObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "lt_lhmt provider request failed",
                            {
                                "station_id": station_id,
                                "product_id": product_id,
                                "year_month": year_month,
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
                            LtLhmtObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "lt_lhmt provider request failed",
                            {
                                "station_id": station_id,
                                "product_id": product_id,
                                "year_month": year_month,
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
                        "year_month": year_month,
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
                        "year_month": year_month,
                        "status_code": response.status_code,
                        "retrieved_at": _iso_z(retrieved_at),
                    }
                )
                parsed = parse_lt_lhmt_observation_json(
                    response.content,
                    station_id=station_id,
                    native_field=policy.native_field,
                )
                issues.extend(parsed.issues)
                if not parsed.records.is_empty():
                    parsed_records.append(parsed.records)
                    endpoints.append(endpoint)
                    if any(
                        issue.code == str(LtLhmtObservationIssueCodes.DATE_ONLY_TIMESTAMP) for issue in parsed.issues
                    ):
                        date_only_seen = True

            filtered_records = _filter_date_range(
                pl.concat(parsed_records) if parsed_records else empty_data(), request.start, request.end
            )

            if not filtered_records.is_empty():
                transformed = transform_series(
                    filtered_records,
                    station_id=station_id,
                    policy=policy,
                    year_months=tuple(year_months),
                    endpoints=tuple(endpoints),
                    date_only_timestamp=date_only_seen,
                )
                series_results.append(transformed)
            elif successes == 0 and failures == 0:
                issues.append(
                    _issue(
                        LtLhmtObservationIssueCodes.MISSING_DATA,
                        "No provider calls returned data for station-product request",
                        {"station_id": station_id, "product_id": product_id},
                    )
                )

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                LtLhmtObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more lt_lhmt provider calls failed while other calls succeeded",
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
            decomposition=("station_product_cross_product", "monthly_chunks"),
            endpoints=(client.base_url,),
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses) if raw_responses else None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


def _iter_year_months(start: datetime, end: datetime) -> list[str]:
    start_date = start.date() if isinstance(start, datetime) else start
    end_date = end.date() if isinstance(end, datetime) else end
    months: list[str] = []
    current = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    while current <= end_month:
        months.append(current.strftime("%Y-%m"))
        current = date(current.year + 1, 1, 1) if current.month == 12 else date(current.year, current.month + 1, 1)
    return months


def _filter_date_range(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    end_next_day = datetime(end_utc.year, end_utc.month, end_utc.day, tzinfo=UTC)
    if end_utc.hour > 0 or end_utc.minute > 0 or end_utc.second > 0:
        from datetime import timedelta

        end_next_day = end_next_day + timedelta(days=1)
    start_day = datetime(start_utc.year, start_utc.month, start_utc.day, tzinfo=UTC)
    return records.filter((pl.col("time") >= start_day) & (pl.col("time") <= end_next_day))


def _raw_payload(responses: list[dict[str, object]]) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.lt_lhmt.raw-metadata+json",
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


def _issue(code: LtLhmtObservationIssueCodes, message: str, details: dict[str, object] | None) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
