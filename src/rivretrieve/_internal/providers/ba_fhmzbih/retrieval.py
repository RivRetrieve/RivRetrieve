from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

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
from rivretrieve._internal.providers.ba_fhmzbih.issue_codes import BaFhmzbihObservationIssueCodes
from rivretrieve._internal.providers.ba_fhmzbih.observation_client import (
    METADATA_URL,
    WORKBOOK_URL_TEMPLATE,
    BaFhmzbihObservationClient,
)
from rivretrieve._internal.providers.ba_fhmzbih.parser import parse_ba_fhmzbih_workbook
from rivretrieve._internal.providers.ba_fhmzbih.transform import (
    BaFhmzbihTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("ba_fhmzbih")
SARAJEVO_TZ = ZoneInfo("Europe/Sarajevo")


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], BaFhmzbihObservationClient] = BaFhmzbihObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    """Retrieve ba_fhmzbih observations.

    The vodostaji.voda.ba portal does not expose a date-range query parameter:
    each ``<code>_1Y.xlsx`` workbook always contains a ~1-year rolling window
    of hourly observations ending at the most recent reading. One workbook is
    fetched per (station, parameter) pair — shared by the instantaneous and
    daily-mean variants of the same product — and then filtered/aggregated to
    the requested window. Requests for periods outside the returned window
    produce a recoverable ``requested_range_beyond_window`` issue and an empty
    series for that station/product.
    """
    requested_at = datetime.now(UTC)
    client = client_factory()
    issues: list[Issue] = []
    series_results: list[BaFhmzbihTransformedSeries] = []
    calls_made: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []

    # Cache parsed workbooks per (station_id, parameter_code) since the
    # instantaneous and daily-mean variants of a product share one workbook.
    workbook_cache: dict[tuple[str, str], tuple[pl.DataFrame, int | None, str | None]] = {}

    successes = 0
    failures = 0

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)
            cache_key = (station_id, policy.parameter_code)

            if cache_key not in workbook_cache:
                response, group, probed = client.fetch_workbook(station_id, policy.parameter_code, policy.workbook_file)

                if response is None:
                    failures += 1
                    issues.append(
                        _issue(
                            BaFhmzbihObservationIssueCodes.STATION_GROUP_NOT_FOUND,
                            "Could not locate a station-group workbook for station/parameter "
                            "(probed all groups, all returned 404 or errored)",
                            {
                                "station_id": station_id,
                                "parameter_code": policy.parameter_code,
                                "probed_urls": probed,
                            },
                        )
                    )
                    workbook_cache[cache_key] = (_empty_local_records(), None, None)
                else:
                    successes += 1
                    endpoint = client.workbook_url(station_id, group or 0, policy.parameter_code, policy.workbook_file)
                    retrieved_at = response.retrieved_at
                    raw_responses.append(
                        {
                            "endpoint": endpoint,
                            "station_id": station_id,
                            "parameter_code": policy.parameter_code,
                            "station_group": group,
                            "status_code": response.status_code,
                            "retrieved_at": _iso_z(retrieved_at),
                            "byte_count": len(response.content),
                            "probed_urls": probed,
                        }
                    )
                    calls_made.append(
                        {
                            "endpoint": endpoint,
                            "station_id": station_id,
                            "parameter_code": policy.parameter_code,
                            "station_group": group,
                            "status_code": response.status_code,
                            "retrieved_at": _iso_z(retrieved_at),
                        }
                    )
                    parsed = parse_ba_fhmzbih_workbook(response.content, station_id=station_id, product_id=product_id)
                    issues.extend(parsed.issues)
                    workbook_cache[cache_key] = (parsed.records, group, endpoint)

            records, group, endpoint = workbook_cache[cache_key]
            filtered = _filter_local_window(records, request.start, request.end)

            if not records.is_empty() and filtered.is_empty():
                issues.append(
                    _issue(
                        BaFhmzbihObservationIssueCodes.REQUESTED_RANGE_BEYOND_WINDOW,
                        "Requested range falls outside the ~1-year rolling window the provider publishes",
                        {
                            "station_id": station_id,
                            "product_id": product_id,
                            "requested_start": request.start.isoformat(),
                            "requested_end": request.end.isoformat(),
                            "available_local_start": _iso_local(records["time_local"].min()),
                            "available_local_end": _iso_local(records["time_local"].max()),
                        },
                    )
                )

            transformed = transform_series(
                filtered,
                station_id=station_id,
                policy=policy,
                group=group,
                endpoint=endpoint,
            )
            series_results.append(transformed)

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                BaFhmzbihObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more ba_fhmzbih workbook fetches failed while other fetches succeeded",
                {"failed_fetches": failures, "successful_fetches": successes},
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
            time_windows=(),
            decomposition=("station_parameter_workbook", "rolling_one_year_window", "local_calendar_filter"),
            endpoints=(METADATA_URL, WORKBOOK_URL_TEMPLATE),
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses) if raw_responses else None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


def _empty_local_records() -> pl.DataFrame:
    return pl.DataFrame(schema={"time_local": pl.Datetime(time_unit="us"), "raw_value": pl.Float64})


def _filter_local_window(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    """Filter naive-local-time records to the requested window.

    To match the ``[start_day_utc, end_next_day_utc)`` convention used by the
    other providers (e.g. br_ana, th_thaiwater, cz_chmi) — i.e. the result
    covers every UTC calendar day touched by the request — we compute that
    UTC window first and then convert its boundaries into Europe/Sarajevo
    local time (an unambiguous UTC -> local conversion) before filtering the
    naive ``time_local`` column. Because ``transform_series`` converts the
    surviving rows back to UTC via the same IANA timezone, the final ``data``
    ends up matching the UTC window exactly (modulo any rows that fall in a
    DST spring-forward gap, which ``transform_series`` already nulls out).
    """
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    start_day_utc = datetime(start_utc.year, start_utc.month, start_utc.day, tzinfo=UTC)
    end_next_day_utc = datetime(end_utc.year, end_utc.month, end_utc.day, tzinfo=UTC) + timedelta(days=1)
    local_start = start_day_utc.astimezone(SARAJEVO_TZ).replace(tzinfo=None)
    local_end = end_next_day_utc.astimezone(SARAJEVO_TZ).replace(tzinfo=None)
    return records.filter((pl.col("time_local") >= local_start) & (pl.col("time_local") < local_end))


def _iso_local(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return None


def _raw_payload(responses: list[dict[str, object]]) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.ba_fhmzbih.raw-metadata+json",
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
    code: BaFhmzbihObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
