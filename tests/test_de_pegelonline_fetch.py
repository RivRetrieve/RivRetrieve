"""Request construction and response-outcome mapping for de_pegelonline retrieval.

Exercises `fetch()`/`config()` directly, the way this codebase tests retrieval
logic ahead of full provider wiring (`declaration.py`/`provider_manifest.py`
registration is #1020's job, not this step's).
"""

import json
from datetime import UTC, datetime

from rivretrieve._internal.engine import (
    RenderedWindow,
    StopConvention,
    Unit,
    WindowEndpoint,
    WindowRenderingVocabulary,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.de_pegelonline.config import config, window_declarations
from rivretrieve._internal.providers.de_pegelonline.fetch import fetch
from rivretrieve._internal.providers.de_pegelonline.series import source_series
from rivretrieve._internal.source_acquisition import SourceResponseMeaning
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from rivretrieve._internal.window_planning import plan_windows

_STATION = "station"
_BASE = "https://www.pegelonline.wsv.de/webservices/rest-api/v2"


def _bounds(start: datetime, end: datetime):
    return _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _window(start: datetime, end: datetime) -> RenderedWindow:
    bounds = _bounds(start, end)
    # window.start/window.stop are deliberately nonsense: fetch.py reads
    # window.bounds directly (the generic Z-rendering is never consulted).
    return RenderedWindow("ignored-start", "ignored-stop", bounds)


class _FixedResponseTransport:
    """A transport double that always answers with one fixed status and body."""

    def __init__(self, status_code: int, body: object, *, content_type: str = "application/json") -> None:
        self.status_code = status_code
        self.body = body
        self.content_type = content_type
        self.requests: list = []

    def send(self, request):
        self.requests.append(request)
        content = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()
        return TransportResponse(
            content,
            self.status_code,
            datetime(2026, 11, 25, 12, 0, tzinfo=UTC),
            self.content_type,
            request.url,
            dict(request.params or {}),
        )


class _RaisingTransport:
    """A transport double simulating a raised `TransportFailure`.

    In real engine operation, `fetch()`'s `transport` argument is always the
    engine's own wrapper (`driver.py`'s `_SourceResponseTransport`), which
    already turns any non-2xx response into a raised `TransportFailure`
    before `fetch()` ever runs -- `fetch()` itself never branches on
    `response.status_code` (`tests/test_provider_architecture_contracts.py`).
    So both a `404`/`400` mismatch against the catalogue and a retry-exhausted
    `5xx` reach `fetch()` the same way: as a failure `attempt_request` already
    turned into a value, never as an ordinary 404-status `TransportResponse`.
    """

    def __init__(self, reason: TransportFailureReason, status_code: int) -> None:
        self.reason = reason
        self.status_code = status_code
        self.requests: list = []

    def send(self, request):
        self.requests.append(request)
        raise TransportFailure(request, self.reason, 1, status_code=self.status_code)


def test_request_uses_uuid_shortname_json_route_with_explicit_start_and_end():
    product = ProductId("W")
    window = _window(datetime(2026, 11, 1, 0, 0, 0), datetime(2026, 11, 2, 0, 0, 0))
    transport = _FixedResponseTransport(200, [])

    fetch((_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport)

    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url == f"{_BASE}/stations/{_STATION}/W/measurements.json"
    # Never omit start: an absent start silently truncates to the last 10 days.
    assert request.params == {
        "start": "2026-11-01T01:00:00+01:00",
        "end": "2026-11-02T01:00:00+01:00",
    }


def test_window_crossing_the_real_2026_10_25_dst_transition_renders_both_offsets():
    """Live-verified against PEGELONLINE itself (issue #874).

    `2026-10-25T01:00:00Z` is the exact Europe/Berlin fall-back instant (MESZ
    `03:00` -> MEZ `02:00`). A window spanning it must render `+02:00` before
    the boundary and `+01:00` from it onward, not one fixed offset.
    """
    product = ProductId("W")
    window = _window(datetime(2026, 10, 24, 22, 0, 0), datetime(2026, 10, 25, 2, 0, 0))
    transport = _FixedResponseTransport(200, [])

    fetch((_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport)

    assert transport.requests[0].params == {
        "start": "2026-10-25T00:00:00+02:00",
        "end": "2026-10-25T03:00:00+01:00",
    }


def test_plan_windows_renders_the_real_dst_transition_through_the_declared_window():
    """Same DST boundary, but through the real engine planner (`plan_windows`),
    not a hand-built `RenderedWindow` -- exercising `window_declarations()`'s
    own `WindowDeclaration` end to end."""
    product = ProductId("W")
    declaration = window_declarations().products[product]
    fetch_window = _bounds(datetime(2026, 10, 24, 22, 0, 0), datetime(2026, 10, 25, 2, 0, 0))
    (rendered,) = plan_windows(fetch_window, declaration)
    transport = _FixedResponseTransport(200, [])

    fetch((_STATION,), (product,), {product: (rendered,)}, fetch_window, config(), transport)

    assert transport.requests[0].params == {
        "start": "2026-10-25T00:00:00+02:00",
        "end": "2026-10-25T03:00:00+01:00",
    }


def test_http_200_empty_array_outside_retention_is_empty_not_error():
    product = ProductId("W")
    window = _window(datetime(2020, 1, 1), datetime(2020, 1, 2))
    series = source_series(_STATION, "W", unit="cm", equidistance=15)
    transport = _FixedResponseTransport(200, [])

    acquired = fetch(
        (_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport, known_series=(series,)
    )

    assert acquired.failed_requests == ()
    outcomes = acquired.interpretations[0].parsed.outcomes
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.status is OutcomeStatus.EMPTY
    assert outcome.series_id == series.series_id


def test_http_404_fails_loudly_and_is_not_mapped_to_no_observations():
    """A `404` reaches `fetch()` as a raised `TransportFailure` (see `_RaisingTransport`),
    not as an ordinary `TransportResponse`: `fetch()` never branches on
    `response.status_code` itself (`tests/test_provider_architecture_contracts.py`) --
    by the time it runs, the engine's own transport wrapping has already turned
    any non-2xx response into this raised failure. `de_pegelonline` declares no
    special status-code meaning, so this surfaces as a plain, unspecified
    `FailedSourceRequest` -- never `lt_lhmt`'s own `NO_OBSERVATIONS` mapping for
    its unrelated `404`.
    """
    product = ProductId("WT")
    window = _window(datetime(2026, 11, 1), datetime(2026, 11, 2))
    transport = _RaisingTransport(TransportFailureReason.HTTP_STATUS, 404)

    acquired = fetch((_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport)

    assert acquired.outcomes == ()
    assert len(acquired.failed_requests) == 1
    failed = acquired.failed_requests[0]
    assert failed.failure.status_code == 404
    assert failed.meaning is SourceResponseMeaning.UNSPECIFIED


def test_raised_transport_failure_surfaces_as_failed_request_not_absorbed():
    product = ProductId("W")
    window = _window(datetime(2026, 11, 1), datetime(2026, 11, 2))
    transport = _RaisingTransport(TransportFailureReason.RETRY_EXHAUSTED, 503)

    acquired = fetch((_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport)

    assert acquired.outcomes == ()
    assert len(acquired.failed_requests) == 1
    assert acquired.failed_requests[0].failure.status_code == 503


def test_success_preserves_native_time_zone_per_row_and_null_values():
    product = ProductId("W")
    window = _window(datetime(2026, 11, 1), datetime(2026, 11, 2))
    series = source_series(_STATION, "W", unit="cm", equidistance=15)
    body = [
        {"timestamp": "2026-11-01T01:15:00+01:00", "value": 150.0},
        {"timestamp": "2026-11-01T01:30:00+01:00", "value": None},
    ]
    transport = _FixedResponseTransport(200, body)

    acquired = fetch(
        (_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport, known_series=(series,)
    )

    assert len(acquired.interpretations) == 1
    rows = acquired.interpretations[0].parsed.rows.sort("time")
    assert rows["time"].to_list() == [datetime(2026, 11, 1, 1, 15), datetime(2026, 11, 1, 1, 30)]
    assert rows["time_zone"].to_list() == ["+01:00", "+01:00"]
    assert rows["value"].to_list() == [150.0, None]
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id


def test_dst_duplicate_wall_clock_hour_rows_stay_distinguishable():
    """Live-verified (issue #874): the repeated 2026-10-25 02:00-02:45 hour
    produces two JSON rows with identical wall-clock labels but different,
    explicit offsets and different values. `.csv` collapses these into
    indistinguishable duplicates; `.json`'s explicit per-row offset keeps
    them apart, and this preserves that distinction rather than converting
    everything to a single shared axis."""
    product = ProductId("W")
    window = _window(datetime(2026, 10, 25, 0, 0), datetime(2026, 10, 25, 4, 0))
    series = source_series(_STATION, "W", unit="cm", equidistance=15)
    body = [
        {"timestamp": "2026-10-25T02:00:00+02:00", "value": 166.0},
        {"timestamp": "2026-10-25T02:00:00+01:00", "value": 165.0},
    ]
    transport = _FixedResponseTransport(200, body)

    acquired = fetch(
        (_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport, known_series=(series,)
    )

    rows = acquired.interpretations[0].parsed.rows
    pairs = sorted(zip(rows["time_zone"].to_list(), rows["value"].to_list(), strict=True))
    assert pairs == [("+01:00", 165.0), ("+02:00", 166.0)]


def test_trm_product_captures_the_difference_annotation():
    product = ProductId("TRM")
    window = _window(datetime(2026, 11, 22), datetime(2026, 11, 24))
    series = source_series(_STATION, "TRM", unit="cm")
    body = [
        {"timestamp": "2026-11-22T16:00:00+01:00", "value": 150.0, "difference": -3.0},
        {"timestamp": "2026-11-22T21:00:00+01:00", "value": None, "difference": None},
    ]
    transport = _FixedResponseTransport(200, body)

    acquired = fetch(
        (_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport, known_series=(series,)
    )

    parsed = acquired.interpretations[0].parsed
    table = parsed.annotations.observation_tables["de_pegelonline.trm"]
    assert table.rows.height == 2
    assert table.rows.sort("time")["difference"].to_list() == [-3.0, None]


def test_w_product_never_carries_the_difference_annotation():
    product = ProductId("W")
    window = _window(datetime(2026, 11, 1), datetime(2026, 11, 2))
    series = source_series(_STATION, "W", unit="cm", equidistance=15)
    body = [{"timestamp": "2026-11-01T01:15:00+01:00", "value": 150.0}]
    transport = _FixedResponseTransport(200, body)

    acquired = fetch(
        (_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport, known_series=(series,)
    )

    assert acquired.interpretations[0].parsed.annotations.is_empty


def test_unknown_series_identity_is_unresolved_not_silently_dropped():
    product = ProductId("Q")
    window = _window(datetime(2026, 11, 1), datetime(2026, 11, 2))
    body = [{"timestamp": "2026-11-01T01:00:00+01:00", "value": 10.0}]
    transport = _FixedResponseTransport(200, body)

    acquired = fetch((_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport)

    outcomes = acquired.interpretations[0].parsed.outcomes
    assert len(outcomes) == 1
    assert outcomes[0].status is OutcomeStatus.UNRESOLVED


def test_malformed_json_response_fails_loudly():
    product = ProductId("W")
    window = _window(datetime(2026, 11, 1), datetime(2026, 11, 2))
    transport = _FixedResponseTransport(200, b"not-json")

    acquired = fetch((_STATION,), (product,), {product: (window,)}, window.bounds, config(), transport)

    outcomes = acquired.interpretations[0].parsed.outcomes
    assert len(outcomes) == 1
    assert outcomes[0].status is OutcomeStatus.FAILED


def test_config_declares_berlin_zone_canonical_units_and_no_cache():
    cfg = config()
    assert cfg.zone == ZoneValue("Europe/Berlin")
    assert cfg.cache is None
    assert {str(product_id): product.unit for product_id, product in cfg.products.items()} == {
        "W": Unit.M,
        "Q": Unit.M3_S,
        "WT": Unit.DEG_C,
        "TRM": Unit.M,
        "TRM_WT": Unit.DEG_C,
    }


def test_window_declarations_are_inclusive_iso_instant_without_precision():
    declarations = window_declarations()
    assert set(declarations.products) == {"W", "Q", "WT", "TRM", "TRM_WT"}
    for declaration in declarations.products.values():
        assert declaration.granularity == "iso-instant"
        assert declaration.rendering is WindowRenderingVocabulary.ISO_INSTANT
        assert declaration.stop_convention is StopConvention.INCLUSIVE
        assert declaration.timestamp_precision is None
