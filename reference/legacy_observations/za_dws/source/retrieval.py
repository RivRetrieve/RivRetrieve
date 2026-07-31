from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import UTC, date, datetime

import polars as pl

from rivretrieve._internal.issues import Issue, apply_on_issue
from rivretrieve._internal.observations import (
    AnnotationTable,
    ObservationProvenance,
    ObservationRequest,
    ObservationResult,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.providers.za_dws.issue_codes import ZaDwsObservationIssueCodes
from rivretrieve._internal.providers.za_dws.observation_client import BASE_URL, ZaDwsObservationClient
from rivretrieve._internal.providers.za_dws.parser import (
    ZaDwsParsedPoint,
    parse_daily_response,
    parse_point_response,
)
from rivretrieve._internal.providers.za_dws.transform import (
    ZaDwsTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_daily_series,
    transform_point_series,
)

PROVIDER_ID = ProviderId("za_dws")

_DAILY_SCHEMA = {"date_str": pl.Utf8, "d_avg_fr": pl.Float64}
_POINT_SCHEMA = {
    "date_str": pl.Utf8,
    "time_str": pl.Utf8,
    "cor_level": pl.Float64,
    "cor_flow": pl.Float64,
}


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], ZaDwsObservationClient] = ZaDwsObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    """Retrieve za_dws observations from the DWS Verified Hydrology portal.

    Three products are supported:

    * ``discharge_daily_mean`` — DataType=Daily, D_AVG_FR column (m³/s),
      20-year windows; timestamps are date-only and interpreted as UTC midnight.
    * ``discharge_instantaneous`` — DataType=Point, COR_FLOW column (m³/s),
      1-year windows; timestamps are SAST (UTC+2) converted to UTC.
    * ``stage_instantaneous`` — DataType=Point, COR_LEVEL column (m),
      1-year windows; timestamps are SAST (UTC+2) converted to UTC.

    Point data for ``discharge_instantaneous`` and ``stage_instantaneous``
    share a single HTTP request per (station, window) via a per-call cache.
    """
    requested_at = datetime.now(UTC)
    client = client_factory()
    issues: list[Issue] = []
    series_results: list[ZaDwsTransformedSeries] = []
    calls_made: list[dict[str, object]] = []

    # Cache for Point responses: (station_id, window_start_iso, window_end_iso) → parsed payload.
    # Shared between discharge_instantaneous and stage_instantaneous for the same station/window.
    point_cache: dict[tuple[str, str, str], ZaDwsParsedPoint] = {}
    point_cache_issues_emitted: set[tuple[str, str, str]] = set()

    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)
            windows = _decompose_windows(request.start, request.end, policy.chunk_years)
            all_records: list[pl.DataFrame] = []
            window_issues: list[Issue] = []

            for window_start, window_end in windows:
                endpoint = _build_url(station_id, policy.data_type, window_start, window_end)

                if policy.is_daily:
                    try:
                        response = client.fetch(station_id, "Daily", window_start, window_end)
                    except Exception as exc:
                        failures += 1
                        window_issues.append(
                            _issue(
                                ZaDwsObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                f"Request failed for station {station_id} daily {window_start}/{window_end}: {exc}",
                                {"station_id": station_id, "window": f"{window_start}/{window_end}"},
                            )
                        )
                        continue

                    calls_made.append(
                        {
                            "station_id": station_id,
                            "product_id": product_id,
                            "endpoint": endpoint,
                            "status_code": response.status_code,
                            "retrieved_at": _iso_z(response.retrieved_at),
                        }
                    )

                    if response.status_code == 404:
                        failures += 1
                        window_issues.append(
                            _issue(
                                ZaDwsObservationIssueCodes.HTTP_NOT_FOUND,
                                f"HTTP 404 for station {station_id} daily {window_start}/{window_end}",
                                {"station_id": station_id, "window": f"{window_start}/{window_end}"},
                            )
                        )
                        continue

                    successes += 1
                    parsed = parse_daily_response(response.content, station_id=station_id)
                    window_issues.extend(parsed.issues)
                    if not parsed.records.is_empty():
                        all_records.append(parsed.records)

                else:
                    cache_key = (station_id, window_start.isoformat(), window_end.isoformat())
                    if cache_key not in point_cache:
                        try:
                            response = client.fetch(station_id, "Point", window_start, window_end)
                        except Exception as exc:
                            failures += 1
                            window_issues.append(
                                _issue(
                                    ZaDwsObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                    f"Request failed for station {station_id} point {window_start}/{window_end}: {exc}",
                                    {"station_id": station_id, "window": f"{window_start}/{window_end}"},
                                )
                            )
                            point_cache[cache_key] = parse_point_response("", station_id=station_id)
                            continue

                        calls_made.append(
                            {
                                "station_id": station_id,
                                "product_id": product_id,
                                "endpoint": endpoint,
                                "status_code": response.status_code,
                                "retrieved_at": _iso_z(response.retrieved_at),
                            }
                        )

                        if response.status_code == 404:
                            failures += 1
                            window_issues.append(
                                _issue(
                                    ZaDwsObservationIssueCodes.HTTP_NOT_FOUND,
                                    f"HTTP 404 for station {station_id} point {window_start}/{window_end}",
                                    {"station_id": station_id, "window": f"{window_start}/{window_end}"},
                                )
                            )
                            point_cache[cache_key] = parse_point_response("", station_id=station_id)
                            continue

                        successes += 1
                        point_cache[cache_key] = parse_point_response(response.content, station_id=station_id)

                    parsed_point = point_cache[cache_key]

                    if cache_key not in point_cache_issues_emitted:
                        window_issues.extend(parsed_point.issues)
                        point_cache_issues_emitted.add(cache_key)

                    if not parsed_point.records.is_empty():
                        all_records.append(parsed_point.records)

            if all_records:
                combined = pl.concat(all_records, how="vertical")
                dedup_subset = ["date_str"] if policy.is_daily else ["date_str", "time_str"]
                combined = combined.unique(subset=dedup_subset, keep="last", maintain_order=True)
            else:
                combined = pl.DataFrame(schema=_DAILY_SCHEMA) if policy.is_daily else pl.DataFrame(schema=_POINT_SCHEMA)

            representative_endpoint = _build_url(
                station_id,
                policy.data_type,
                request.start.date() if isinstance(request.start, datetime) else request.start,
                request.end.date() if isinstance(request.end, datetime) else request.end,
            )

            if policy.is_daily:
                transformed = transform_daily_series(
                    combined,
                    station_id=station_id,
                    policy=policy,
                    endpoint=representative_endpoint,
                )
            else:
                transformed = transform_point_series(
                    combined,
                    station_id=station_id,
                    policy=policy,
                    endpoint=representative_endpoint,
                )

            issues.extend(window_issues)
            series_results.append(transformed)

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                ZaDwsObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more DWS requests failed while other requests succeeded",
                {"failed_requests": failures, "successful_requests": successes},
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

    if not data.is_empty():
        data = data.filter(
            (pl.col("time") >= request.start) & (pl.col("time") <= request.end)
        ).sort(["station_id", "product_id", "time"])

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
            retrieved_at=_latest_retrieved_at(calls_made),
            request={
                "stations": list(request.stations),
                "products": list(request.products),
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
            calls_made=tuple(calls_made),
            time_windows=(),
            decomposition=("station_product_window", "daily_20year_chunks_or_point_1year_chunks"),
            endpoints=(BASE_URL,),
        ),
        issues=tuple(issues),
        raw=None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


def _decompose_windows(start: datetime, end: datetime, chunk_years: int) -> list[tuple[date, date]]:
    """Decompose a datetime range into non-overlapping year-aligned date windows."""
    start_date = start.date() if isinstance(start, datetime) else start
    end_date = end.date() if isinstance(end, datetime) else end

    windows: list[tuple[date, date]] = []
    current = start_date
    while current <= end_date:
        chunk_end = date(current.year + chunk_years - 1, 12, 31)
        if chunk_end > end_date:
            chunk_end = end_date
        windows.append((current, chunk_end))
        current = date(chunk_end.year + 1, 1, 1)
    return windows


def _build_url(station_id: str, data_type: str, start: date, end: date) -> str:
    return (
        f"{BASE_URL}?Station={station_id}100.00"
        f"&DataType={data_type}"
        f"&StartDT={start.isoformat()}"
        f"&EndDT={end.isoformat()}"
        f"&SiteType=RIV"
    )


def _latest_retrieved_at(calls: list[dict[str, object]]) -> datetime | None:
    values: list[datetime] = []
    for call in calls:
        v = call.get("retrieved_at")
        if isinstance(v, str):
            with contextlib.suppress(ValueError):
                values.append(datetime.fromisoformat(v.replace("Z", "+00:00")))
    return max(values) if values else None


def _iso_z(value: datetime) -> str:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue(
    code: ZaDwsObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
