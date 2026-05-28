from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import polars as pl
import requests

from rivretrieve._internal.issues import FatalContractError, Issue, apply_on_issue
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
from rivretrieve._internal.providers.ch_foen.issue_codes import ChFoenObservationIssueCodes
from rivretrieve._internal.providers.ch_foen.observation_client import ChFoenObservationClient
from rivretrieve._internal.providers.ch_foen.parser import parse_ch_foen_observation_csv
from rivretrieve._internal.providers.ch_foen.query import ChFoenProviderCall, build_calls, resolve_product_policy
from rivretrieve._internal.providers.ch_foen.raw_payload import ChFoenRawCsvResponse
from rivretrieve._internal.providers.ch_foen.transform import (
    ChFoenTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    stitch_transformed_series,
    transform_series,
)

PROVIDER_ID = ProviderId("ch_foen")


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], ChFoenObservationClient] = ChFoenObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    series_results: list[ChFoenTransformedSeries] = []
    raw_responses: list[ChFoenRawCsvResponse] = []
    calls_made: list[dict[str, object]] = []
    time_windows: list[dict[str, object]] = []
    issues: list[Issue] = []
    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)
            calls = build_calls(station_id=station_id, product_id=product_id, start=request.start, end=request.end)
            successful_windows = []
            parsed_frames: list[pl.DataFrame] = []
            source_queries: list[str] = []
            timezone_mismatch = False
            for call in calls:
                time_windows.append(_window_dict(call))
                try:
                    response = client.fetch(call.query)
                except (requests.RequestException, OSError, TimeoutError) as exc:
                    failures += 1
                    issues.append(_source_request_failed(call, exc))
                    continue
                successes += 1
                raw_responses.append(
                    ChFoenRawCsvResponse(
                        csv_bytes=response.content,
                        endpoint=client.endpoint,
                        query=call.query,
                        status_code=response.status_code,
                        retrieved_at=response.retrieved_at,
                        station_id=station_id,
                        product_id=product_id,
                        window_start=call.window.start,
                        window_end=call.window.end,
                    )
                )
                calls_made.append(
                    {
                        "endpoint": client.endpoint,
                        "query": call.query,
                        "status_code": response.status_code,
                        "retrieved_at": _iso_z(response.retrieved_at),
                        "station_id": station_id,
                        "product_id": product_id,
                        "window_start": _iso_z(call.window.start),
                        "window_end": _iso_z(call.window.end),
                    }
                )
                parsed = parse_ch_foen_observation_csv(response.content)
                issues.extend(_scope_issue(issue, call) for issue in parsed.issues)
                timezone_mismatch = timezone_mismatch or any(
                    issue.code == ChFoenObservationIssueCodes.TIMEZONE_AMBIGUITY for issue in parsed.issues
                )
                parsed_frames.append(parsed.records)
                source_queries.append(call.query)
                successful_windows.append(call.window)
            if calls and not parsed_frames:
                issues.append(
                    _issue(
                        ChFoenObservationIssueCodes.MISSING_DATA,
                        "No successful provider calls returned data for station-product request",
                        {"station_id": station_id, "product_id": product_id},
                    )
                )
            elif parsed_frames:
                records = pl.concat(parsed_frames, how="vertical") if parsed_frames else empty_data()
                source_query = source_queries[0] if len(source_queries) == 1 else "multiple ch_foen flux queries"
                transformed = transform_series(
                    records,
                    station_id=station_id,
                    policy=policy,
                    windows=tuple(successful_windows),
                    endpoint=client.endpoint,
                    source_query=source_query,
                    timezone_mismatch=timezone_mismatch,
                )
                series_results.append(stitch_transformed_series((transformed,)))

    if failures and successes:
        issues.append(
            _issue(
                ChFoenObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more ch_foen provider calls failed while other calls succeeded",
                {"failed_calls": failures, "successful_calls": successes},
            )
        )

    if series_results:
        data = pl.concat([series.data for series in series_results], how="vertical")
        row_annotations = pl.concat([series.row_annotations for series in series_results], how="vertical")
        series_annotations = pl.concat([series.series_annotations for series in series_results], how="vertical")
        issues.extend(issue for series in series_results for issue in series.issues)
    else:
        data = empty_data()
        row_annotations = empty_row_annotations()
        series_annotations = empty_series_annotations()

    data = data.sort(["station_id", "product_id", "time"]) if not data.is_empty() else data
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
            retrieved_at=_latest_retrieved_at(raw_responses),
            request={
                "stations": list(request.stations),
                "products": list(request.products),
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
            calls_made=tuple(calls_made),
            time_windows=tuple(time_windows),
            decomposition=("station_product_cross_product", "max_366_day_windows"),
            endpoints=(client.endpoint,),
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses),
    )
    _assert_sanitized(result)
    apply_on_issue(result.issues, on_issue)
    return result


def _raw_payload(responses: list[ChFoenRawCsvResponse]) -> RawPayload | None:
    if not responses:
        return None
    metadata = [
        {
            "endpoint": response.endpoint,
            "query": response.query,
            "status_code": response.status_code,
            "retrieved_at": None if response.retrieved_at is None else _iso_z(response.retrieved_at),
            "station_id": response.station_id,
            "product_id": response.product_id,
            "window_start": None if response.window_start is None else _iso_z(response.window_start),
            "window_end": None if response.window_end is None else _iso_z(response.window_end),
            "byte_count": len(response.csv_bytes),
        }
        for response in responses
    ]
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.ch_foen.raw-metadata+json",
        content=None,
        metadata=json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    )


def _source_request_failed(call: ChFoenProviderCall, exc: Exception) -> Issue:
    return _issue(
        ChFoenObservationIssueCodes.SOURCE_REQUEST_FAILED,
        "ch_foen provider request failed",
        {
            "station_id": call.station_id,
            "product_id": call.product_id,
            "window_start": _iso_z(call.window.start),
            "window_end": _iso_z(call.window.end),
            "exception_type": type(exc).__name__,
        },
    )


def _scope_issue(issue: Issue, call: ChFoenProviderCall) -> Issue:
    details = dict(issue.details or {})
    details.update(
        {
            "station_id": call.station_id,
            "product_id": call.product_id,
            "window_start": _iso_z(call.window.start),
            "window_end": _iso_z(call.window.end),
        }
    )
    return issue.model_copy(update={"details": details})


def _window_dict(call: ChFoenProviderCall) -> dict[str, object]:
    return {
        "station_id": call.station_id,
        "product_id": call.product_id,
        "start": _iso_z(call.window.start),
        "end": _iso_z(call.window.end),
        "query_stop": _iso_z(call.window.query_stop),
        "native_fields": list(call.native_fields),
    }


def _latest_retrieved_at(responses: list[ChFoenRawCsvResponse]) -> datetime | None:
    values = [response.retrieved_at for response in responses if response.retrieved_at is not None]
    return max(values) if values else None


def _issue(code: ChFoenObservationIssueCodes, message: str, details: dict[str, object] | None) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)


def _assert_sanitized(result: ObservationResult) -> None:
    rendered = repr(result.provenance) + repr(result.raw) + "".join(issue.message for issue in result.issues)
    if "Authorization" in rendered or "Token " in rendered:
        raise FatalContractError("ch_foen sanitized metadata unexpectedly contains authorization material")


def _iso_z(value: datetime) -> str:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
