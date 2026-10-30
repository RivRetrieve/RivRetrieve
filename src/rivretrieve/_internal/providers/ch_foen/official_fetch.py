"""Acquire bounded anonymous official GraphQL queries and preserve partial results."""

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from functools import partial
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    SourceQuery,
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.official_config import TIMESTAMP_PRECISION, OfficialRoute
from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget, attempt_request
from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome, SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import HttpMethod, ReplaySafety, Transport, TransportFailure, TransportRequest
from rivretrieve._internal.window_acquisition import WindowAcquisition, WindowResponseMeaning, acquire_window

_ENDPOINT = "https://data.bafu.admin.ch/api"
# Public pagination documentation defines this omitted-limit rejection.
_OVERFLOW = "Query returned more than 10000 rows. Please narrow your query using filters or specify a limit."


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
    *,
    timestamp_precision: timedelta = TIMESTAMP_PRECISION,
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
) -> SourceAcquisition:
    results = []
    for station in stations:
        for product in products:
            coordinates = config.products[product].coordinates.value
            if not isinstance(coordinates, OfficialRoute):
                raise FatalContractError("Official Swiss acquisition requires official route coordinates")
            for window in rendered_windows[product]:
                acquire = partial(
                    _acquire, station, product, coordinates, transport=transport, scope=scope, known_series=known_series
                )
                results.append(acquire_window(window, precision=timestamp_precision, acquire=acquire))
    return SourceAcquisition(
        value=tuple(item for result in results for item in result.value),
        calls=tuple(item for result in results for item in result.calls),
        outcomes=tuple(item for result in results for item in result.outcomes),
        failed_requests=tuple(item for result in results for item in result.failed_requests),
    )


def _acquire(station, product, coordinates, window, transport, scope, known_series) -> WindowAcquisition:
    if window.bounds is None or window.stop is None:
        raise FatalContractError("Official Swiss acquisition requires engine-rendered bounds")
    query = _query(station, coordinates, window)
    request = TransportRequest(
        HttpMethod.POST,
        _ENDPOINT,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        body=json.dumps({"query": query}),
        replay_safety=ReplaySafety.SAFE,
    )
    response = attempt_request(transport, request)
    interval = SeriesWindow(
        start=datetime.fromisoformat(window.bounds.start.isoformat()),
        end=datetime.fromisoformat(window.bounds.end.isoformat()),
    )
    if isinstance(response, (TransportFailure, CredentialExchangeError)):
        return WindowAcquisition(
            SourceAcquisition(
                (),
                failed_requests=(
                    FailedSourceRequest(
                        uuid4().hex,
                        SourceRequestTarget(station, product),
                        interval,
                        request,
                        response,
                    ),
                ),
            )
        )
    call_id = uuid4().hex
    origin = SourceCallOrigin(
        response.url,
        response.request_parameters,
        response.status_code,
        response.retrieved_at,
        response.content_type or UnknownOriginFact(),
        UnknownOriginFact(),
        SourceQuery(query, ()),
        attempts=response.attempts,
        attempt_traces=response.attempt_traces,
        acquisition_id=call_id,
    )
    meaning, reason = response_meaning(response.content, coordinates.route)
    if not 200 <= response.status_code < 300:
        meaning, reason = WindowResponseMeaning.COMPLETE, f"Source returned HTTP {response.status_code}"
    if reason is not None:
        outcome = RetrievalOutcome(
            outcome_id=uuid4().hex,
            series_id=None,
            station_id=station,
            product_id=product,
            window=interval,
            status=OutcomeStatus.FAILED,
            reason=reason,
            retrieved_at=response.retrieved_at,
            calls=(call_id,),
        )
        return WindowAcquisition(
            SourceAcquisition((), calls=(origin,), outcomes=(outcome,)),
            meaning,
            (outcome.outcome_id,) if meaning is WindowResponseMeaning.OVERFLOW else (),
        )
    payload = Payload(
        SourceCoordinates(coordinates),
        ((station, product),),
        window.bounds,
        response.content,
        origin,
        response.prerequisite_calls,
        scope,
        known_series,
        attempt_traces=response.attempt_traces,
    )
    return WindowAcquisition(SourceAcquisition((payload,)))


def response_meaning(content: bytes, route: str) -> tuple[WindowResponseMeaning, str | None]:
    """Classify the envelope, leaving observation interpretation to parsing."""
    try:
        document = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return WindowResponseMeaning.COMPLETE, "Source response is not valid JSON"
    if not isinstance(document, dict):
        return WindowResponseMeaning.COMPLETE, "Source response is not an object"
    errors = document.get("errors")
    if errors:
        overflow = (
            document.get("data") is None
            and isinstance(errors, list)
            and all(
                isinstance(error, dict)
                and error.get("errorType") == "ValidationError"
                and error.get("message") == _OVERFLOW
                and error.get("path") == ["water", "observations", route]
                for error in errors
            )
        )
        return (
            (WindowResponseMeaning.OVERFLOW, "Source rejected the interval because it exceeds the row limit")
            if overflow
            else (
                WindowResponseMeaning.COMPLETE,
                "Source GraphQL errors: "
                + json.dumps(
                    [
                        {key: error[key] for key in ("message", "errorType", "path") if key in error}
                        for error in errors
                        if isinstance(error, dict)
                    ]
                    if isinstance(errors, list)
                    else errors,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
    try:
        records = document["data"]["water"]["observations"][route]
    except (KeyError, TypeError):
        return WindowResponseMeaning.COMPLETE, "Source response lacks the requested observation route"
    if not isinstance(records, list):
        return WindowResponseMeaning.COMPLETE, "Source observation route is not an array"
    return WindowResponseMeaning.COMPLETE, None


def _query(station: str, coordinates: OfficialRoute, window: RenderedWindow) -> str:
    station_filter = (
        f"stationNo: {{_eq: {json.dumps(station)}}}"
        if coordinates.route == "data_live"
        else (f"station: {{no: {{_eq: {json.dumps(station)}}}}}")
    )
    fields = (
        "stationNo parameterName timestamp value releaseStatus"
        if coordinates.route == "data_live"
        else ("station { no } parameterName tsName unitSymbol timestamp value releaseState")
    )
    return (
        "query { water { observations { "
        + coordinates.route
        + "(where: {"
        + station_filter
        + f", parameterName: {{_eq: {json.dumps(coordinates.parameter)}}}, timestamp: {{_gte: {json.dumps(window.start)}, _lt: {json.dumps(window.stop)}}}"
        + "}) { "
        + fields
        + " } } } }"
    )
