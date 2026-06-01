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
from rivretrieve._internal.providers.usgs_nwis.issue_codes import UsgsNwisObservationIssueCodes
from rivretrieve._internal.providers.usgs_nwis.observation_client import UsgsNwisObservationClient
from rivretrieve._internal.providers.usgs_nwis.parser import parse_usgs_nwis_observation_json
from rivretrieve._internal.providers.usgs_nwis.transform import (
    UsgsNwisTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("usgs_nwis")
_WINDOW_DAYS = 365


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], UsgsNwisObservationClient] = UsgsNwisObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    series_results: list[UsgsNwisTransformedSeries] = []
    calls_made: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []
    issues: list[Issue] = []
    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)
            windows = _iter_windows(request.start, request.end)
            parsed_records: list[pl.DataFrame] = []
            endpoints: list[str] = []

            for window_start, window_end in windows:
                if policy.endpoint == "dv":
                    assert policy.stat_code is not None
                    endpoint = client.dv_endpoint_for(
                        station_id, policy.param_code, policy.stat_code, window_start, window_end
                    )
                    try:
                        response = client.fetch_dv(
                            station_id, policy.param_code, policy.stat_code, window_start, window_end
                        )
                    except requests.HTTPError as exc:
                        if exc.response is not None and exc.response.status_code == 404:
                            issues.append(
                                _issue(
                                    UsgsNwisObservationIssueCodes.HTTP_NOT_FOUND,
                                    "No data available for station/window (HTTP 404)",
                                    {
                                        "station_id": station_id,
                                        "product_id": product_id,
                                        "window": [window_start, window_end],
                                        "endpoint": endpoint,
                                    },
                                )
                            )
                            continue
                        failures += 1
                        issues.append(
                            _issue(
                                UsgsNwisObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                "usgs_nwis DV request failed",
                                {
                                    "station_id": station_id,
                                    "product_id": product_id,
                                    "window": [window_start, window_end],
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
                                UsgsNwisObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                "usgs_nwis DV request failed",
                                {
                                    "station_id": station_id,
                                    "product_id": product_id,
                                    "window": [window_start, window_end],
                                    "endpoint": endpoint,
                                    "exception_type": type(exc).__name__,
                                },
                            )
                        )
                        continue
                else:
                    endpoint = client.iv_endpoint_for(station_id, policy.param_code, window_start, window_end)
                    try:
                        response = client.fetch_iv(station_id, policy.param_code, window_start, window_end)
                    except requests.HTTPError as exc:
                        if exc.response is not None and exc.response.status_code == 404:
                            issues.append(
                                _issue(
                                    UsgsNwisObservationIssueCodes.HTTP_NOT_FOUND,
                                    "No data available for station/window (HTTP 404)",
                                    {
                                        "station_id": station_id,
                                        "product_id": product_id,
                                        "window": [window_start, window_end],
                                        "endpoint": endpoint,
                                    },
                                )
                            )
                            continue
                        failures += 1
                        issues.append(
                            _issue(
                                UsgsNwisObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                "usgs_nwis IV request failed",
                                {
                                    "station_id": station_id,
                                    "product_id": product_id,
                                    "window": [window_start, window_end],
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
                                UsgsNwisObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                "usgs_nwis IV request failed",
                                {
                                    "station_id": station_id,
                                    "product_id": product_id,
                                    "window": [window_start, window_end],
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
                        "window": [window_start, window_end],
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
                        "window": [window_start, window_end],
                        "status_code": response.status_code,
                        "retrieved_at": _iso_z(retrieved_at),
                    }
                )
                parsed = parse_usgs_nwis_observation_json(
                    response.content,
                    station_id=station_id,
                )
                issues.extend(parsed.issues)
                if not parsed.records.is_empty():
                    parsed_records.append(parsed.records)
                    endpoints.append(endpoint)

            all_records = pl.concat(parsed_records) if parsed_records else empty_data()
            filtered_records = _filter_date_range(all_records, request.start, request.end)

            if not filtered_records.is_empty():
                transformed = transform_series(
                    filtered_records,
                    station_id=station_id,
                    policy=policy,
                    windows=tuple(windows),
                    endpoints=tuple(endpoints),
                )
                series_results.append(transformed)
            elif successes == 0 and failures == 0:
                issues.append(
                    _issue(
                        UsgsNwisObservationIssueCodes.MISSING_DATA,
                        "No provider calls returned data for station-product request",
                        {"station_id": station_id, "product_id": product_id},
                    )
                )

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                UsgsNwisObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more usgs_nwis provider calls failed while other calls succeeded",
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
            time_windows=tuple({"start": w[0], "end": w[1]} for w in _iter_windows(request.start, request.end)),
            decomposition=("station_product_cross_product", "annual_windows"),
            endpoints=(client.dv_base_url, client.iv_base_url),
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses) if raw_responses else None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


def _iter_windows(start: datetime, end: datetime) -> list[tuple[str, str]]:
    start_date = start.date() if isinstance(start, datetime) else start
    end_date = end.date() if isinstance(end, datetime) else end
    windows: list[tuple[str, str]] = []
    current = start_date
    while current <= end_date:
        window_end = min(current + timedelta(days=_WINDOW_DAYS - 1), end_date)
        windows.append((current.isoformat(), window_end.isoformat()))
        current = window_end + timedelta(days=1)
    return windows


def _filter_date_range(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    """Keep rows whose UTC timestamp falls on a calendar date within [start_date, end_date].

    USGS DV timestamps are midnight local time expressed with an explicit UTC offset,
    e.g. 2021-12-31T00:00:00-06:00 → 2021-12-31T06:00:00Z.  Comparing against
    midnight UTC of the end date would drop the entire last day for any non-UTC station.
    We therefore use an exclusive upper bound of midnight UTC of end_date + 1 day, which
    correctly includes all timestamps that fall on end_date in any US timezone.
    """
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    # Inclusive lower bound: midnight UTC of start date
    start_day = datetime(start_utc.year, start_utc.month, start_utc.day, tzinfo=UTC)
    # Exclusive upper bound: midnight UTC of (end date + 1)
    # This captures any UTC timestamp that falls on end_date regardless of the station's timezone offset.
    end_next_day = datetime(end_utc.year, end_utc.month, end_utc.day, tzinfo=UTC) + timedelta(days=1)
    return records.filter((pl.col("time") >= start_day) & (pl.col("time") < end_next_day))


def _raw_payload(responses: list[dict[str, object]]) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.usgs_nwis.raw-metadata+json",
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
    code: UsgsNwisObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
