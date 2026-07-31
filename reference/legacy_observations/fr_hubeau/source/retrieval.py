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
from rivretrieve._internal.providers.fr_hubeau.issue_codes import FrHubeauObservationIssueCodes
from rivretrieve._internal.providers.fr_hubeau.observation_client import (
    OBS_ELAB_URL,
    OBS_TR_URL,
    TEMPERATURE_URL,
    FrHubeauObservationClient,
)
from rivretrieve._internal.providers.fr_hubeau.parser import (
    parse_fr_hubeau_obs_elab_json,
    parse_fr_hubeau_obs_tr_json,
    parse_fr_hubeau_temperature_json,
)
from rivretrieve._internal.providers.fr_hubeau.transform import (
    FrHubeauTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("fr_hubeau")
MAX_WINDOW_DAYS = 365


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], FrHubeauObservationClient] = FrHubeauObservationClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    series_results: list[FrHubeauTransformedSeries] = []
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
                endpoint, initial_params = _build_endpoint_and_params(client, station_id, policy, start_date, end_date)
                current_url: str | None = _base_url_for(policy)
                params: dict[str, object] | None = initial_params
                page_records: list[pl.DataFrame] = []

                while current_url is not None:
                    try:
                        response = client.fetch(current_url, params)
                    except requests.HTTPError as exc:
                        if exc.response is not None and exc.response.status_code == 404:
                            issues.append(
                                _issue(
                                    FrHubeauObservationIssueCodes.HTTP_NOT_FOUND,
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
                            break
                        failures += 1
                        issues.append(
                            _issue(
                                FrHubeauObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                "fr_hubeau provider request failed",
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
                        break
                    except (requests.RequestException, OSError, TimeoutError) as exc:
                        failures += 1
                        issues.append(
                            _issue(
                                FrHubeauObservationIssueCodes.SOURCE_REQUEST_FAILED,
                                "fr_hubeau provider request failed",
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
                        break

                    successes += 1
                    retrieved_at = response.retrieved_at
                    raw_responses.append(
                        {
                            "endpoint": current_url,
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
                            "endpoint": current_url,
                            "station_id": station_id,
                            "product_id": product_id,
                            "start_date": start_date,
                            "end_date": end_date,
                            "status_code": response.status_code,
                            "retrieved_at": _iso_z(retrieved_at),
                        }
                    )

                    parsed = _parse_response(response.content, policy, station_id)
                    issues.extend(parsed.issues)
                    if not parsed.records.is_empty():
                        page_records.append(parsed.records)

                    current_url = parsed.next_url
                    params = None  # subsequent pages: full next_url, no extra params

                if page_records:
                    window_records = pl.concat(page_records)
                    parsed_records.append(window_records)
                    used_endpoints.append(endpoint)
                    used_windows.append((start_date, end_date))

            all_records = pl.concat(parsed_records) if parsed_records else empty_data()
            filtered_records = _filter_date_range(all_records, request.start, request.end, policy)

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
                        FrHubeauObservationIssueCodes.MISSING_DATA,
                        "No provider calls returned data for station-product request",
                        {"station_id": station_id, "product_id": product_id},
                    )
                )

    if failures > 0 and successes > 0:
        issues.append(
            _issue(
                FrHubeauObservationIssueCodes.PARTIAL_RESPONSE,
                "One or more fr_hubeau provider calls failed while other calls succeeded",
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
            endpoints=(OBS_ELAB_URL, OBS_TR_URL, TEMPERATURE_URL),
        ),
        issues=tuple(issues),
        raw=_raw_payload(raw_responses) if raw_responses else None,
    )
    apply_on_issue(result.issues, on_issue)
    return result


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


def _base_url_for(policy: FrHubeauProductPolicy) -> str:  # type: ignore[name-defined]
    from rivretrieve._internal.providers.fr_hubeau.transform import FrHubeauProductPolicy  # noqa: F401

    if policy.api_type == "obs_elab":
        return OBS_ELAB_URL
    if policy.api_type == "obs_tr":
        return OBS_TR_URL
    return TEMPERATURE_URL


def _build_endpoint_and_params(
    client: FrHubeauObservationClient,
    station_id: str,
    policy: FrHubeauProductPolicy,  # type: ignore[name-defined]
    start_date: str,
    end_date: str,
) -> tuple[str, dict[str, object]]:
    from rivretrieve._internal.providers.fr_hubeau.transform import FrHubeauProductPolicy  # noqa: F401

    if policy.api_type == "obs_elab":
        assert policy.grandeur_code is not None
        return (
            client.endpoint_for_obs_elab(station_id, policy.grandeur_code, start_date, end_date),
            client.initial_params_obs_elab(station_id, policy.grandeur_code, start_date, end_date),
        )
    if policy.api_type == "obs_tr":
        assert policy.grandeur_code is not None
        return (
            client.endpoint_for_obs_tr(station_id, policy.grandeur_code, start_date, end_date),
            client.initial_params_obs_tr(station_id, policy.grandeur_code, start_date, end_date),
        )
    # temperature
    return (
        client.endpoint_for_temperature(station_id, start_date, end_date),
        client.initial_params_temperature(station_id, start_date, end_date),
    )


def _parse_response(
    content: bytes,
    policy: FrHubeauProductPolicy,  # type: ignore[name-defined]
    station_id: str,
) -> FrHubeauParsedPayload:  # type: ignore[name-defined]
    from rivretrieve._internal.providers.fr_hubeau.parser import FrHubeauParsedPayload  # noqa: F401

    if policy.api_type == "obs_elab":
        assert policy.grandeur_code is not None
        return parse_fr_hubeau_obs_elab_json(content, station_id=station_id, grandeur_code=policy.grandeur_code)
    if policy.api_type == "obs_tr":
        assert policy.grandeur_code is not None
        return parse_fr_hubeau_obs_tr_json(content, station_id=station_id, grandeur_code=policy.grandeur_code)
    return parse_fr_hubeau_temperature_json(content, station_id=station_id)


# ---------------------------------------------------------------------------
# Windowing and date filtering
# ---------------------------------------------------------------------------


def _split_windows(start: datetime, end: datetime) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    current = start
    while current <= end:
        window_end = min(end, current + timedelta(days=MAX_WINDOW_DAYS - 1))
        windows.append((current.strftime("%Y-%m-%d"), window_end.strftime("%Y-%m-%d")))
        current = window_end + timedelta(days=1)
    return windows


def _filter_date_range(
    records: pl.DataFrame,
    start: datetime,
    end: datetime,
    policy: FrHubeauProductPolicy,  # type: ignore[name-defined]
) -> pl.DataFrame:
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)

    if policy.api_type == "obs_elab":
        # Date-only UTC midnight: align to day boundaries.
        start_day = datetime(start_utc.year, start_utc.month, start_utc.day, tzinfo=UTC)
        end_next_day = datetime(end_utc.year, end_utc.month, end_utc.day, tzinfo=UTC) + timedelta(days=1)
        return records.filter((pl.col("time") >= start_day) & (pl.col("time") < end_next_day))
    else:
        # Full timestamps: keep [start, end] inclusive.
        return records.filter((pl.col("time") >= start_utc) & (pl.col("time") <= end_utc))


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _raw_payload(responses: list[dict[str, object]]) -> RawPayload:
    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.fr_hubeau.raw-metadata+json",
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
    code: FrHubeauObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)


# Avoid circular import — import after definition.
from rivretrieve._internal.providers.fr_hubeau.parser import FrHubeauParsedPayload  # noqa: E402
from rivretrieve._internal.providers.fr_hubeau.transform import FrHubeauProductPolicy  # noqa: E402
