"""Acquire one PEGELONLINE REST API v2 `measurements.json` window per station x product.

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

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from functools import partial
from math import isfinite
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    InterpretedPayload,
    Payload,
    ProviderConfig,
    RenderedWindow,
    RowsSchema,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.de_pegelonline.annotations import DE_PEGELONLINE_TRM_SCHEMA
from rivretrieve._internal.providers.de_pegelonline.config import PegelOnlineTimeseries
from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget, attempt_request
from rivretrieve._internal.source_annotations import (
    OBSERVATION_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    ObservationAnnotationTable,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    admission,
    stable_id,
)
from rivretrieve._internal.transport import HttpMethod, ReplaySafety, Transport, TransportFailure, TransportRequest
from rivretrieve._internal.window_acquisition import WindowAcquisition, acquire_window

_BASE_URL = "https://www.pegelonline.wsv.de/webservices/rest-api/v2"
_ZONE = ZoneInfo("Europe/Berlin")
_VALID_OFFSETS = {timedelta(hours=1): "+01:00", timedelta(hours=2): "+02:00"}

# TRM and TRM_WT (and only these two) additionally publish a per-observation
# "difference" field (change from the previous day's scheduled reading),
# matching step 3's DE_PEGELONLINE_TRM_SCHEMA annotation (live-verified).
_TRM_PRODUCTS = frozenset({"TRM", "TRM_WT"})

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
    try:
        parsed = _parse_records(payload, station, product)
    except UnsupportedSourceStructureError as error:
        parsed = _failed_parsed(payload, station, product, str(error))
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


def _numeric_or_none(entry: dict[str, object], key: str) -> float | None:
    if key not in entry:
        raise UnsupportedSourceStructureError(f"de_pegelonline observation is missing required field {key!r}")
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise UnsupportedSourceStructureError(f"de_pegelonline observation field {key!r} must be numeric or null")
    try:
        numeric = float(value)
    except OverflowError as error:
        raise UnsupportedSourceStructureError(
            f"de_pegelonline observation field {key!r} must be numeric or null"
        ) from error
    if not isfinite(numeric):
        raise UnsupportedSourceStructureError(f"de_pegelonline observation field {key!r} must be numeric or null")
    return numeric


def _parse_records(payload: Payload, station: str, product: ProductId) -> ParsedSeries:
    """Interpret one station/product's pre-decoded `measurements.json` response."""
    try:
        document = json.loads(payload.content)
    except (ValueError, UnicodeDecodeError) as error:
        raise UnsupportedSourceStructureError("de_pegelonline response is not valid JSON") from error
    if not isinstance(document, list):
        raise UnsupportedSourceStructureError("de_pegelonline response is not a JSON array")
    records = cast("list[object]", document)
    del document

    matches = tuple(
        item for item in payload.known_series if item.station_id == station and item.product_id == str(product)
    )
    if len(matches) > 1:
        raise FatalContractError("de_pegelonline payload matches more than one known source series")

    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None

    if not matches:
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, "unresolved"),
            series_id=None,
            station_id=station,
            product_id=product,
            window=window,
            status=OutcomeStatus.UNRESOLVED,
            reason="No established source-series identity for this station and product",
            retrieved_at=retrieved,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,))

    definition = matches[0]
    if len(definition.facts) != 1:
        raise FatalContractError("de_pegelonline source series requires exactly one physical-fact segment")
    fact = definition.facts[0]
    decision = admission(fact)

    track_difference = str(product) in _TRM_PRODUCTS
    rows: list[dict[str, object]] = []
    ann_rows: list[dict[str, object]] = []
    if decision.status == "supported":
        for item in records:
            if not isinstance(item, dict):
                raise UnsupportedSourceStructureError("de_pegelonline observation must be an object")
            entry = cast("dict[str, object]", item)
            label = entry.get("timestamp")
            if not isinstance(label, str):
                raise UnsupportedSourceStructureError("de_pegelonline observation requires a string timestamp")
            try:
                timestamp = datetime.fromisoformat(label)
            except ValueError as error:
                raise UnsupportedSourceStructureError("de_pegelonline observation timestamp is invalid") from error
            offset = timestamp.utcoffset() if timestamp.tzinfo is not None else None
            time_zone = _VALID_OFFSETS.get(offset) if offset is not None else None
            if time_zone is None:
                raise UnsupportedSourceStructureError(
                    "de_pegelonline observation timestamp must carry the Europe/Berlin +01:00 or +02:00 offset"
                )
            native_time = timestamp.replace(tzinfo=None)
            value = _numeric_or_none(entry, "value")
            rows.append(
                {
                    "station_id": station,
                    "product_id": str(product),
                    "time": native_time,
                    "value": value,
                    "time_zone": time_zone,
                    "series_id": definition.series_id,
                    "facts_id": fact.facts_id,
                    "source_unit": fact.source_unit.value,
                }
            )
            if track_difference:
                difference = _numeric_or_none(entry, "difference")
                ann_rows.append(
                    {
                        "series_id": definition.series_id,
                        "facts_id": fact.facts_id,
                        "station_id": station,
                        "product_id": str(product),
                        "time": native_time,
                        "time_zone": time_zone,
                        "measured": True,
                        "difference": difference,
                    }
                )
    status = (
        OutcomeStatus.UNSUPPORTED
        if decision.status != "supported"
        else OutcomeStatus.SUCCESS
        if rows
        else OutcomeStatus.EMPTY
    )
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id),
        series_id=definition.series_id,
        station_id=station,
        product_id=product,
        window=window,
        facts_ids=(fact.facts_id,),
        status=status,
        reason=decision.reason if status is OutcomeStatus.UNSUPPORTED else None,
        retrieved_at=retrieved,
    )
    evidence = f"source-call:{payload.acquisition_id}"
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, "inventory"),
        scope=payload.scope
        or SeriesScope(provider_ids=("de_pegelonline",), station_ids=(station,), product_ids=(str(product),)),
        members=(definition.series_id,),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=str(product),
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason="Returned series establishes this response, not an exhaustive historical inventory",
    )
    if ann_rows:
        ann_frame = pl.DataFrame(
            ann_rows,
            schema={**OBSERVATION_STRUCTURAL_SCHEMA, **DE_PEGELONLINE_TRM_SCHEMA.polars_schema()},
        )
        ann_table = ObservationAnnotationTable.from_rows(
            schema=DE_PEGELONLINE_TRM_SCHEMA,
            rows=ann_frame,
            measurement_indices=list(range(len(rows))),
        )
        annotations = AnnotationBundle(observation_tables={DE_PEGELONLINE_TRM_SCHEMA.schema_id: ann_table})
    else:
        annotations = AnnotationBundle.empty()
    return ParsedSeries(
        pl.DataFrame(rows, schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        (outcome,),
        annotations=annotations,
    )


def _failed_parsed(payload: Payload, station: str, product: ProductId, reason: str) -> ParsedSeries:
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, "unsupported"),
        series_id=None,
        station_id=station,
        product_id=product,
        window=window,
        status=OutcomeStatus.FAILED,
        reason=reason,
    )
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,))
