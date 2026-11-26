"""Acquire one PEGELONLINE REST API v2 `measurements.json` window per station x product.

Request construction and response-status handling only: response-body decoding
lives in `parse.py` (`_parse_records`, `_failed_parsed`, `_numeric_or_none`,
`_TRM_PRODUCTS`), split out to match every other live-`fetch`/`parse` provider
in this codebase. `_acquire` below imports `parse_records` from `parse.py` for
its own inline fetch-time interpretation, matching
`ch_foen/official_fetch.py` importing from `ch_foen/official_parse.py`.

Each of the five products (`W`, `Q`, `WT`, `TRM`, `TRM_WT`) lives at its own
independent `/stations/{uuid}/{shortname}/measurements.json` route; there is
nothing to decode jointly (unlike `lt_lhmt`'s two co-published products) and
no pagination is needed (PEGELONLINE documents no row cap, and a full 31-day
1-minute window is at most ~44,640 rows, comfortably one response). This
follows `ch_foen/official_fetch.py`'s independent per-call loop shape
(`fetch()` iterating `stations x products x rendered_windows`, delegating
each call to `acquire_window`) even though every call here always reports
`WindowResponseMeaning.COMPLETE`: PEGELONLINE never signals overflow, so the
subdivision path `acquire_window` provides is simply never exercised.

PEGELONLINE's REST API v2 requires an explicit `start`/`end` ISO-8601 instant
with a `Europe/Berlin` UTC offset (never a fixed offset: MEZ `+01:00`/MESZ
`+02:00` alternate across the DST boundary) and never omits `start` (omitting
it silently truncates the response to the last 10 days). There is no shared
engine mechanism that renders a DST-aware localized offset string, so this
module reads `RenderedWindow.bounds` (the engine's own UTC wall-clock bounds)
directly and converts each endpoint itself, the same way
`ch_foen/official_fetch.py`'s `_acquire` reads `window.bounds` directly rather
than relying on the generic ISO-`Z` rendering.

A request outside the rolling ~31-day retention buffer returns `HTTP 200`
with an empty JSON array `[]`; this is a normal `OutcomeStatus.EMPTY`, not an
error, and is not pre-clipped anywhere in this module (there is no "source
retention bounds" concept to hook into). An unexpected `4xx`/`5xx` is not
mapped to any special meaning (unlike `lt_lhmt`'s own `404` -> `NO_OBSERVATIONS`
mapping): step 2's catalogue already declares availability in advance, so a
genuine disagreement here is a real contract problem and must fail loudly.
This module never branches on `response.status_code` itself (a cross-provider
architecture rule, `tests/test_provider_architecture_contracts.py`): by the
time `fetch()` runs, the engine's own transport wrapping has already turned
any non-2xx response into a raised `TransportFailure`, so `attempt_request`
surfaces it as an ordinary `FailedSourceRequest` with no declared status-code
meaning, which the engine maps to `OutcomeStatus.FAILED`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4
from zoneinfo import ZoneInfo

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    InterpretedPayload,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.de_pegelonline.config import PegelOnlineTimeseries
from rivretrieve._internal.providers.de_pegelonline.parse import parse_records
from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget, attempt_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import HttpMethod, ReplaySafety, Transport, TransportFailure, TransportRequest
from rivretrieve._internal.window_acquisition import WindowAcquisition, acquire_window

_BASE_URL = "https://www.pegelonline.wsv.de/webservices/rest-api/v2"
_ZONE = ZoneInfo("Europe/Berlin")

# Overflow subdivision is never exercised: PEGELONLINE documents no row cap
# and fetch() always reports WindowResponseMeaning.COMPLETE. acquire_window
# still requires a precision value for its (unreachable) subdivision path.
_SUBDIVISION_PRECISION = timedelta(milliseconds=1)


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
    *,
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
) -> SourceAcquisition:
    results = []
    for station in stations:
        for product in products:
            coordinates = config.products[product].coordinates.value
            if not isinstance(coordinates, PegelOnlineTimeseries):
                raise FatalContractError(f"de_pegelonline product has invalid source coordinates: {product}")
            for window in rendered_windows[product]:
                acquire = partial(
                    _acquire,
                    station,
                    product,
                    coordinates,
                    transport=transport,
                    scope=scope,
                    known_series=known_series,
                )
                results.append(acquire_window(window, precision=_SUBDIVISION_PRECISION, acquire=acquire))
    return SourceAcquisition(
        value=tuple(item for result in results for item in result.value),
        calls=tuple(item for result in results for item in result.calls),
        outcomes=tuple(item for result in results for item in result.outcomes),
        failed_requests=tuple(item for result in results for item in result.failed_requests),
        interpretations=tuple(item for result in results for item in result.interpretations),
    )


def _acquire(
    station: str,
    product: ProductId,
    coordinates: PegelOnlineTimeseries,
    window: RenderedWindow,
    *,
    transport: Transport,
    scope: SeriesScope | None,
    known_series: tuple[SourceSeries, ...],
) -> WindowAcquisition:
    if window.bounds is None:
        raise FatalContractError("de_pegelonline acquisition requires engine-rendered bounds")
    request = TransportRequest(
        HttpMethod.GET,
        f"{_BASE_URL}/stations/{station}/{coordinates.shortname}/measurements.json",
        params={
            "start": _local_offset_isoformat(window.bounds.start),
            "end": _local_offset_isoformat(window.bounds.end),
        },
        headers={"Accept": "application/json"},
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
        UnknownOriginFact(),
        attempts=response.attempts,
        attempt_traces=response.attempt_traces,
        acquisition_id=call_id,
    )
    # No status-code branch here: the engine's own transport wrapping already
    # turns any unexpected non-2xx response into a raised TransportFailure
    # before fetch() ever sees it (handled above), so every response reaching
    # this point is an ordinary successful call. An unexpected 4xx/5xx
    # therefore fails loudly through the ordinary TransportFailure path, not
    # a provider-declared status-code meaning.
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
    parsed = parse_records(payload, station, product)
    return WindowAcquisition(
        SourceAcquisition(
            (payload,),
            interpretations=(InterpretedPayload.from_payload(payload, parsed),),
        )
    )


def _local_offset_isoformat(endpoint: WindowEndpoint) -> str:
    """Render an engine UTC wall-clock endpoint as a DST-aware Europe/Berlin ISO-8601 instant.

    `requests` (the sender behind `Transport`) percent-encodes the literal `+`
    in the rendered offset as `%2B` automatically when building the query
    string from `TransportRequest.params`; no manual encoding is needed here.
    """
    utc_instant = datetime.fromisoformat(endpoint.isoformat()).replace(tzinfo=UTC)
    return utc_instant.astimezone(_ZONE).isoformat()
