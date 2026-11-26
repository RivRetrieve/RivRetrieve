"""Standalone `parse()` entry point for de_pegelonline (split from `fetch.py`, #1020).

Exercises `parse.py`'s `parse(payload, config)` directly: the shared engine's
`ProviderStages.parse` contract, used when reusing a cached/replayed payload
rather than a fresh fetch-time interpretation. `test_de_pegelonline_fetch.py`
already covers `fetch()`'s own inline interpretation (now delegating to
`parse.parse_records`); this module instead builds `Payload` values by hand
to prove the standalone entry point derives `(station, product)` from
`payload.station_products[0]` and validates it against `config`, exactly as
`ch_foen/official_parse.py`'s `_validated_route_coordinates` does.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import polars.testing as pl_testing
import pytest

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.de_pegelonline.config import PegelOnlineTimeseries, config
from rivretrieve._internal.providers.de_pegelonline.parse import parse, parse_records
from rivretrieve._internal.providers.de_pegelonline.series import source_series
from rivretrieve._internal.source_series import OutcomeStatus

_STATION = "station"


def _payload(
    *,
    product: str = "W",
    station_products: tuple[tuple[str, ProductId], ...] | None = None,
    coordinates: PegelOnlineTimeseries | None = None,
    content: bytes | None = None,
    known_series: tuple = (),
) -> Payload:
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 11, 1)), WindowEndpoint.from_datetime(datetime(2026, 11, 2))
    )
    return Payload(
        SourceCoordinates(coordinates if coordinates is not None else PegelOnlineTimeseries(product)),
        station_products if station_products is not None else ((_STATION, ProductId(product)),),
        window,
        content if content is not None else json.dumps([]).encode(),
        SourceCallOrigin(
            UnknownOriginFact(),
            UnknownOriginFact(),
            UnknownOriginFact(),
            datetime(2026, 11, 2, 12, tzinfo=UTC),
            UnknownOriginFact(),
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        (),
        None,
        known_series,
    )


def test_parse_reproduces_parse_records_for_a_single_known_pair():
    series = source_series(_STATION, "W", unit="cm", equidistance=15)
    body = [{"timestamp": "2026-11-01T01:15:00+01:00", "value": 150.0}]
    payload = _payload(product="W", content=json.dumps(body).encode(), known_series=(series,))

    expected = parse_records(payload, _STATION, ProductId("W"))
    actual = parse(payload, config())

    pl_testing.assert_frame_equal(actual.rows, expected.rows)
    assert actual.series == expected.series
    assert actual.outcomes == expected.outcomes
    assert actual.outcomes[0].status is OutcomeStatus.SUCCESS


def test_parse_rejects_payload_without_exactly_one_station_product():
    payload = _payload(station_products=())

    with pytest.raises(FatalContractError, match="exactly one station and product"):
        parse(payload, config())


def test_parse_rejects_payload_with_more_than_one_station_product():
    payload = _payload(station_products=((_STATION, ProductId("W")), (_STATION, ProductId("Q"))))

    with pytest.raises(FatalContractError, match="exactly one station and product"):
        parse(payload, config())


def test_parse_rejects_product_contradicting_configured_coordinates():
    # The payload's own source_coordinates (W) disagree with the declared
    # product (Q), which must resolve to Q's own coordinates.
    payload = _payload(product="Q", coordinates=PegelOnlineTimeseries("W"))

    with pytest.raises(FatalContractError, match="contradicts configured product coordinates"):
        parse(payload, config())


def test_parse_surfaces_malformed_json_as_a_failed_outcome_not_a_raised_error():
    payload = _payload(product="W", content=b"not-json")

    parsed = parse(payload, config())

    assert len(parsed.outcomes) == 1
    assert parsed.outcomes[0].status is OutcomeStatus.FAILED
