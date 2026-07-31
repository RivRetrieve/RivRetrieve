from __future__ import annotations

import calendar
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
from rivretrieve._internal.providers.jp_mlit.issue_codes import JpMlitObservationIssueCodes
from rivretrieve._internal.providers.jp_mlit.observation_client import DSP_URL, JpMlitObservationClient
from rivretrieve._internal.providers.jp_mlit.parser import parse_jp_mlit_daily_dat, parse_jp_mlit_hourly_dat
from rivretrieve._internal.providers.jp_mlit.transform import (
    JpMlitTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("jp_mlit")


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], JpMlitObservationClient] = JpMlitObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    series_results: list[JpMlitTransformedSeries] = []
    calls_made: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []
    issues: list[Issue] = []
    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)
            windows = _split_windows(request.start, request.end, policy.kind)
            parsed_records: list[pl.DataFrame] = []
            used_endpoints: list[str] = []
            used_windows: list[tuple[str, str]] = []

            for begin_date, end_date in windows:
                endpoint = _html_url(station_id, policy.kind, begin_date, end_date)
                try:
                    dat_response = client.fetch_observation_window(station_id, policy.kind, begin_date, end_date)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        issues.append(
                            _issue(
                                JpMlitObservationIssueCodes.HTTP_NOT_FOUND,
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
                            JpMlitObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "jp_mlit provider request failed",
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
                            JpMlitObservationIssueCodes.SOURCE_REQUEST_FAILED,
                            "jp_mlit provider request failed",
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

                # No .dat link found in the HTML page.
                if dat_response.dat_url is None:
                    issues.append(
                        _issue(
                            JpMlitObservationIssueCodes.NO_DAT_LINK,
                            "No .dat link found in MLIT HTML response",
                            {
                                "station_id": station_id,
                                "product_id": product_id,
                                "begin_date": begin_date,
                                "end_date": end_date,
                                "html_url": dat_response.html_url,
                            },
                        )
                    )
                    continue

                successes += 1
                retrieved_at = dat_response.retrieved_at
                raw_responses.append(
                    {
                        "html_url": dat_response.html_url,
                        "dat_url": dat_response.dat_url,
                        "station_id": station_id,
                        "product_id": product_id,
                        "kind": policy.kind,
                        "begin_date": begin_date,
                        "end_date": end_date,
                        "retrieved_at": _iso_z(retrieved_at),
                    }
                )
                calls_made.append(
                    {
                        "html_url": dat_response.html_url,
                        "dat_url": dat_response.dat_url,
                        "station_id": station_id,
                        "product_id": product_id,
                        "kind": policy.kind,
                        "begin_date": begin_date,
                        "end_date": end_date,
                        "retrieved_at": _iso_z(retrieved_at),
                    }
                )

                if policy.frequency == "hourly":
                    parsed = parse_jp_mlit_hourly_dat(dat_response.dat_content, station_id=station_id)
                else:
                    parsed = parse_jp_mlit_daily_dat(dat_response.dat_content, station_id=station_id)

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
                        JpMlitObservationIssueCodes.MISSING_DATA,
                        "No provider calls returned data for station-product request",
                        {"station_id": station_id, "product_id": product_id},
                    )
                )

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                JpMlitObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more jp_mlit provider calls failed while other calls succeeded",
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
                "monthly_windows_for_hourly_kinds_2_6",
                "yearly_windows_for_daily_kinds_3_7",
            ),
            endpoints=(DSP_URL,),
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses) if raw_responses else None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


# ---------------------------------------------------------------------------
# Windowing helpers
# ---------------------------------------------------------------------------


def _split_windows(start: datetime, end: datetime, kind: int) -> list[tuple[str, str]]:
    """Generate request windows.

    Hourly kinds (2, 6): monthly windows in YYYYMMDD format.
    Daily kinds (3, 7): yearly windows with year-start → year-end.

    The MLIT system uses YYYYMMDD (no separator) for its date params.
    """
    windows: list[tuple[str, str]] = []
    if kind in (2, 6):
        # Monthly windows.
        current = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while current <= end:
            year = current.year
            month = current.month
            last_day = calendar.monthrange(year, month)[1]
            begin_str = f"{year}{month:02d}01"
            end_str = f"{year}{month:02d}{last_day:02d}"
            windows.append((begin_str, end_str))
            current = current.replace(year=year + 1, month=1) if month == 12 else current.replace(month=month + 1)
    else:
        # Yearly windows.
        for year in range(start.year, end.year + 1):
            begin_str = f"{year}0101"
            end_str = f"{year}1231"
            windows.append((begin_str, end_str))
    return windows


def _filter_date_range(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    # For both daily and hourly, use inclusive [start_day, end_day+1) to cover full days.
    start_day = datetime(start_utc.year, start_utc.month, start_utc.day, tzinfo=UTC)
    end_next_day = datetime(end_utc.year, end_utc.month, end_utc.day, tzinfo=UTC) + timedelta(days=1)
    return records.filter((pl.col("time") >= start_day) & (pl.col("time") < end_next_day))


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _html_url(station_id: str, kind: int, begin_date: str, end_date: str) -> str:
    return f"{DSP_URL}?KIND={kind}&ID={station_id}&BGNDATE={begin_date}&ENDDATE={end_date}&KAWABOU=NO"


def _raw_payload(responses: list[dict[str, object]]) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.jp_mlit.raw-metadata+json",
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
    code: JpMlitObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
