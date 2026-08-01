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
from rivretrieve._internal.providers.br_ana.issue_codes import BrAnaObservationIssueCodes
from rivretrieve._internal.providers.br_ana.observation_client import (
    AUTH_URL,
    DISCHARGE_URL,
    STAGE_URL,
    TELEMETRIC_ADOTADA_URL,
    TELEMETRIC_DETALHADA_URL,
    TELEMETRIC_MAX_WINDOW_DAYS,
    BrAnaObservationClient,
    is_telemetric_product,
)
from rivretrieve._internal.providers.br_ana.parser import parse_br_ana_json, parse_br_ana_telemetric_json
from rivretrieve._internal.providers.br_ana.transform import (
    BrAnaTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    resolve_telemetric_product_policy,
    transform_series,
    transform_telemetric_series,
)

PROVIDER_ID = ProviderId("br_ana")
MAX_WINDOW_YEARS = 1
ALL_ENDPOINTS = (AUTH_URL, DISCHARGE_URL, STAGE_URL, TELEMETRIC_ADOTADA_URL, TELEMETRIC_DETALHADA_URL)


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], BrAnaObservationClient] = BrAnaObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    series_results: list[BrAnaTransformedSeries] = []
    calls_made: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []
    issues: list[Issue] = []

    # Emit auth_missing immediately if credentials absent — no per-station loops.
    if not client.has_credentials():
        issues.append(
            _issue(
                BrAnaObservationIssueCodes.AUTH_MISSING,
                "ANA credentials not available. Set ANA_IDENTIFICADOR and ANA_SENHA env vars.",
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
                decomposition=("station_product_cross_product", "annual_windows"),
                endpoints=ALL_ENDPOINTS,
            ),
            issues=tuple(issues),
            raw=None,
        )
        apply_on_issue(result.issues, on_issue)
        return result

    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            telemetric = is_telemetric_product(product_id)

            if telemetric:
                policy_t = resolve_telemetric_product_policy(product_id)
                windows_t = _split_30day_windows(request.start, request.end)
                parsed_records = []
                used_endpoints = []
                used_windows = []
                pre_successes, pre_failures = successes, failures

                for anchor_date, win_start, win_end in windows_t:
                    token = client.fetch_token()
                    if token is None:
                        failures += 1
                        issues.append(
                            _issue(
                                BrAnaObservationIssueCodes.AUTH_FAILED,
                                "Failed to obtain ANA authentication token",
                                {"station_id": station_id, "product_id": product_id},
                            )
                        )
                        continue

                    endpoint = client.telemetric_endpoint_for(station_id, product_id, anchor_date)
                    window_details = {
                        "station_id": station_id,
                        "product_id": product_id,
                        "anchor_date": anchor_date,
                        "window_start": win_start,
                        "window_end": win_end,
                        "endpoint": endpoint,
                    }

                    try:
                        response = client.fetch_telemetric_data(station_id, product_id, anchor_date, token)
                    except requests.HTTPError as exc:
                        if exc.response is not None and exc.response.status_code == 404:
                            issues.append(
                                _issue(
                                    BrAnaObservationIssueCodes.HTTP_NOT_FOUND,
                                    "No telemetric data available for station/window (HTTP 404)",
                                    window_details,
                                )
                            )
                            continue
                        failures += 1
                        issues.append(
                            _issue(
                                BrAnaObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                "br_ana telemetric provider request failed",
                                {**window_details, "exception_type": type(exc).__name__},
                            )
                        )
                        continue
                    except (requests.RequestException, OSError, TimeoutError) as exc:
                        failures += 1
                        issues.append(
                            _issue(
                                BrAnaObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                "br_ana telemetric provider request failed",
                                {**window_details, "exception_type": type(exc).__name__},
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
                            "start_date": win_start,
                            "end_date": win_end,
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
                            "start_date": win_start,
                            "end_date": win_end,
                            "status_code": response.status_code,
                            "retrieved_at": _iso_z(retrieved_at),
                        }
                    )

                    parsed = parse_br_ana_telemetric_json(response.content, station_id=station_id, product_id=product_id)
                    issues.extend(parsed.issues)
                    if not parsed.records.is_empty():
                        parsed_records.append(parsed.records)
                        used_endpoints.append(endpoint)
                        used_windows.append((win_start, win_end))

                all_records = pl.concat(parsed_records) if parsed_records else None
                filtered_records = (
                    _filter_local_date_range(all_records, request.start, request.end)
                    if all_records is not None
                    else None
                )

                if filtered_records is not None and not filtered_records.is_empty():
                    transformed = transform_telemetric_series(
                        filtered_records,
                        station_id=station_id,
                        policy=policy_t,
                        windows=tuple(used_windows),
                        endpoints=tuple(used_endpoints),
                    )
                    series_results.append(transformed)
                elif successes == pre_successes and failures == pre_failures:
                    issues.append(
                        _issue(
                            BrAnaObservationIssueCodes.MISSING_DATA,
                            "No provider calls returned data for station-product request",
                            {"station_id": station_id, "product_id": product_id},
                        )
                    )
                continue

            policy = resolve_product_policy(product_id)
            windows = _split_annual_windows(request.start, request.end)
            parsed_records = []
            used_endpoints = []
            used_windows = []

            for start_date, end_date in windows:
                token = client.fetch_token()
                if token is None:
                    failures += 1
                    issues.append(
                        _issue(
                            BrAnaObservationIssueCodes.AUTH_FAILED,
                            "Failed to obtain ANA authentication token",
                            {"station_id": station_id, "product_id": product_id},
                        )
                    )
                    continue

                endpoint = client.endpoint_for(station_id, product_id, start_date, end_date)

                try:
                    response = client.fetch_data(station_id, product_id, start_date, end_date, token)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        issues.append(
                            _issue(
                                BrAnaObservationIssueCodes.HTTP_NOT_FOUND,
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
                            BrAnaObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "br_ana provider request failed",
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
                            BrAnaObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "br_ana provider request failed",
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

                parsed = parse_br_ana_json(response.content, station_id=station_id, product_id=product_id)
                issues.extend(parsed.issues)
                if not parsed.records.is_empty():
                    parsed_records.append(parsed.records)
                    used_endpoints.append(endpoint)
                    used_windows.append((start_date, end_date))

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
                        BrAnaObservationIssueCodes.MISSING_DATA,
                        "No provider calls returned data for station-product request",
                        {"station_id": station_id, "product_id": product_id},
                    )
                )

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                BrAnaObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more br_ana provider calls failed while other calls succeeded",
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
            decomposition=("station_product_cross_product", "annual_windows"),
            endpoints=ALL_ENDPOINTS,
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses) if raw_responses else None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


def _split_annual_windows(start: datetime, end: datetime) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    current_year = start.year
    end_year = end.year
    while current_year <= end_year:
        window_start = max(start, datetime(current_year, 1, 1, tzinfo=UTC))
        window_end = min(end, datetime(current_year, 12, 31, tzinfo=UTC))
        if window_start <= window_end:
            windows.append((window_start.strftime("%Y-%m-%d"), window_end.strftime("%Y-%m-%d")))
        current_year += 1
    return windows


def _split_30day_windows(start: datetime, end: datetime) -> list[tuple[str, str, str]]:
    """Decompose [start, end] into ≤30-day chunks for the telemetric endpoints.

    Each chunk is requested with a single ``Data de Busca`` anchor date plus
    ``Range Intervalo de busca = DIAS_30`` (the ANA API resolves the actual
    returned span from those two parameters; requests are capped at 30 days
    per the live OpenAPI spec). We anchor each chunk at its end date, which
    is the most common convention for "give me the last N days" search APIs —
    this should be empirically reconfirmed against live responses (see
    /tmp/ana_telemetric_diag.py) since the manual does not document the
    search direction explicitly.

    Returns a list of (anchor_date, window_start, window_end) string triples
    (yyyy-MM-dd). ``window_start``/``window_end`` describe the *requested*
    sub-range for provenance/logging; the actual returned span is filtered
    against the overall request range by ``_filter_local_date_range``.
    """
    windows: list[tuple[str, str, str]] = []
    cursor = start
    step = timedelta(days=TELEMETRIC_MAX_WINDOW_DAYS - 1)
    while cursor <= end:
        window_end = min(end, cursor + step)
        windows.append(
            (
                window_end.strftime("%Y-%m-%d"),
                cursor.strftime("%Y-%m-%d"),
                window_end.strftime("%Y-%m-%d"),
            )
        )
        cursor = window_end + timedelta(days=1)
    return windows


def _filter_local_date_range(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    """Filter telemetric records (naive local-time ``time`` column) to [start, end].

    Telemetric records carry naive local (BRT, UTC-3) timestamps prior to
    transformation. The comparison is done on local calendar dates — matching
    the same "inclusive day" semantics as ``_filter_date_range`` — so the
    final UTC-converted series isn't truncated at local-midnight boundaries.
    """
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    start_day = datetime(start_utc.year, start_utc.month, start_utc.day)
    end_next_day = datetime(end_utc.year, end_utc.month, end_utc.day) + timedelta(days=1)
    return records.filter((pl.col("time") >= start_day) & (pl.col("time") < end_next_day))


def _filter_date_range(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    start_day = datetime(start_utc.year, start_utc.month, start_utc.day, tzinfo=UTC)
    end_next_day = datetime(end_utc.year, end_utc.month, end_utc.day, tzinfo=UTC) + timedelta(days=1)
    return records.filter((pl.col("time") >= start_day) & (pl.col("time") < end_next_day))


def _raw_payload(responses: list[dict[str, object]]) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.br_ana.raw-metadata+json",
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
    code: BrAnaObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
