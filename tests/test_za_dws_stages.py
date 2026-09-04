"""South Africa stage contracts that need no source bytes : declarations, call coalescing, refusals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from rivretrieve._internal.engine import (
    Daily,
    Instant,
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.za_dws.config import ZaDwsDataType, ZaDwsSourceCoordinates
from rivretrieve._internal.providers.za_dws.declaration import declaration
from rivretrieve._internal.providers.za_dws.fetch import ZaDwsSourceRoute
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from rivretrieve._internal.window_planning import plan_windows

assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages
_CONFIG = _STAGES.config
_DAILY = ProductId("discharge_daily_mean")
_FLOW = ProductId("discharge_instantaneous")
_LEVEL = ProductId("stage_instantaneous")


class _EmptyBodyTransport:
    """Answer every request with an empty 200 body; only the issued requests are under test."""

    def __init__(self) -> None:
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return TransportResponse(
            content=b"",
            status_code=200,
            retrieved_at=datetime(2026, 9, 3, tzinfo=UTC),
            content_type="text/html",
            url=request.url,
            request_parameters=request.params or {},
        )


def _fetch_window(start: datetime, end: datetime):
    return _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _payload(content: bytes, data_type: str, products: tuple[ProductId, ...]) -> Payload:
    assert data_type in ("Daily", "Point")
    return Payload(
        source_coordinates=SourceCoordinates(ZaDwsSourceRoute(cast("ZaDwsDataType", data_type))),
        station_products=tuple(("X3H001", product) for product in products),
        fetch_window=_fetch_window(datetime(2020, 1, 1), datetime(2020, 1, 31)),
        content=content,
        origin=SourceCallOrigin(
            url="https://www.dws.gov.za/Hydrology/Verified/HyData.aspx",
            request_parameters={},
            status_code=200,
            retrieved_at=datetime(2026, 9, 3, tzinfo=UTC),
            content_type=UnknownOriginFact(),
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
        prerequisite_calls=(),
    )


def test_config_states_unknown_zone_and_source_coordinates_per_product() -> None:
    assert _CONFIG.zone.value == "unknown"
    coordinates = {product: config.coordinates.value for product, config in _CONFIG.products.items()}
    assert coordinates == {
        _DAILY: ZaDwsSourceCoordinates("Daily", "D AVG F/R"),
        _FLOW: ZaDwsSourceCoordinates("Point", "COR.FLOW"),
        _LEVEL: ZaDwsSourceCoordinates("Point", "COR.LEVEL"),
    }
    daily = _CONFIG.products[_DAILY].semantics
    assert isinstance(daily, Daily)
    assert daily.day_definition.value == "unknown"
    assert all(isinstance(_CONFIG.products[product].semantics, Instant) for product in (_FLOW, _LEVEL))
    with pytest.raises(ValueError, match="not published by DataType=Daily"):
        ZaDwsSourceCoordinates("Daily", "COR.FLOW")


def test_window_declarations_are_exclusive_year_chunks_per_data_type() -> None:
    declarations = _STAGES.window_declarations.products
    assert {product: (d.granularity, d.size, d.stop_convention) for product, d in declarations.items()} == {
        _DAILY: ("n-year-chunk", 20, StopConvention.EXCLUSIVE),
        _FLOW: ("n-year-chunk", 1, StopConvention.EXCLUSIVE),
        _LEVEL: ("n-year-chunk", 1, StopConvention.EXCLUSIVE),
    }


def test_fetch_issues_one_call_per_station_data_type_and_window() -> None:
    fetch_window = _fetch_window(datetime(2020, 1, 3), datetime(2020, 1, 8, 23, 59, 59, 999999))
    rendered = {
        product: plan_windows(fetch_window, _STAGES.window_declarations.products[product])
        for product in (_FLOW, _LEVEL, _DAILY)
    }
    transport = _EmptyBodyTransport()

    fetched = _STAGES.fetch(("X3H001",), (_FLOW, _LEVEL, _DAILY, _FLOW), rendered, fetch_window, _CONFIG, transport)

    assert fetched.issues == ()
    assert [dict(request.params or {}) for request in transport.requests] == [
        {
            "Station": "X3H001100.00",
            "DataType": "Point",
            "StartDT": "2020-01-03",
            "EndDT": "2020-01-09",
            "SiteType": "RIV",
        },
        {
            "Station": "X3H001100.00",
            "DataType": "Daily",
            "StartDT": "2020-01-03",
            "EndDT": "2020-01-09",
            "SiteType": "RIV",
        },
    ]
    assert all(request.url == "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx" for request in transport.requests)
    assert [payload.station_products for payload in fetched.value] == [
        (("X3H001", _FLOW), ("X3H001", _LEVEL)),
        (("X3H001", _DAILY),),
    ]
    assert [payload.source_coordinates.value for payload in fetched.value] == [
        ZaDwsSourceRoute("Point"),
        ZaDwsSourceRoute("Daily"),
    ]


def test_fetch_refuses_unexpected_http_status() -> None:
    class _Forbidden(_EmptyBodyTransport):
        def send(self, request: TransportRequest) -> TransportResponse:
            response = super().send(request)
            return TransportResponse(
                content=response.content,
                status_code=403,
                retrieved_at=response.retrieved_at,
                content_type=response.content_type,
                url=response.url,
                request_parameters=response.request_parameters,
            )

    fetch_window = _fetch_window(datetime(2020, 1, 3), datetime(2020, 1, 8))
    rendered = {_DAILY: plan_windows(fetch_window, _STAGES.window_declarations.products[_DAILY])}
    with pytest.raises(FatalContractError, match="unexpected HTTP status 403"):
        _STAGES.fetch(("X3H001",), (_DAILY,), rendered, fetch_window, _CONFIG, _Forbidden())


@pytest.mark.parametrize(
    ("content", "data_type", "products", "match"),
    [
        (b"<html><body>Server Error</body></html>", "Daily", (_DAILY,), "neither a <pre> data block"),
        (
            b"<pre>POS. 1-8 = Date\nX3H001\nVariable 100.00 Surface Water Level\nDATE D AVG F/R QUAL\n</pre>",
            "Daily",
            (_DAILY,),
            "ZZZZZZZZZZZZ terminator",
        ),
        (
            b"<pre>POS. 1-8 = Date\nA1H001\nVariable 100.00 Surface Water Level\nDATE D AVG F/R QUAL\nZZZZZZZZZZZZ\n</pre>",
            "Daily",
            (_DAILY,),
            "requested station X3H001",
        ),
        (
            b"<pre>POS. 1-8 = Date\nX3H001\nVariable 100.00 Surface Water Level\nDATE D AVG F/R QUAL\n20200101 1.257\nZZZZZZZZZZZZ\n</pre>",
            "Daily",
            (_DAILY,),
            "exactly 3 fields",
        ),
        (
            b"<pre>POS. 1-8 = Date\nX3H001\nVariable 100.00 Surface Water Level\nDATE D AVG F/R QUAL\nZZZZZZZZZZZZ\n</pre>",
            "Daily",
            (_FLOW,),
            "DataType Daily does not publish",
        ),
        (
            b"<pre>POS. 1-8 = Date\nX3H001\nVariable 100.00 Surface Water Level\nDATE TIME COR.LEVEL QUA COR.FLOW QUA\n20200101 000000 0.146 1 abc 1\nZZZZZZZZZZZZ\n</pre>",
            "Point",
            (_FLOW,),
            "COR.FLOW field is not numeric",
        ),
    ],
)
def test_parse_dies_rather_than_guess(
    content: bytes, data_type: str, products: tuple[ProductId, ...], match: str
) -> None:
    with pytest.raises(FatalContractError, match=match):
        _STAGES.parse(_payload(content, data_type, products), _CONFIG)


# A mutated copy of the real 2020 legacy Daily bytes (reference/legacy_observations/za_dws), cut
# to three rows with the second value replaced by the 99999.999 token. It grounds no claim about
# the source; it only exercises how parse treats that token.
_MUTATED_DAILY_PAGE = (
    b"<p><pre>Data are continuously updated and reviewed.\n"
    b"The format of this file is as follows:\n"
    b"POS.  1-8   = Date of daily flow  CCYYMMDD\n"
    b"POS. 10-18  = Daily avg flow rate in cubic metres/sec 99999.999\n"
    b"POS. 20-24  = Quality code\n\n"
    b"X3H001\nVariable 100.00 Surface Water Level\n\n"
    b"DATE     D AVG F/R  QUAL\n"
    b"20200101     1.257     1\n"
    b"20200102 99999.999     1\n"
    b"20200103     1.217     1\n"
    b"ZZZZZZZZZZZZ\n</pre></p>"
)


def test_parse_returns_the_marker_token_as_published_with_a_warning() -> None:
    result = _STAGES.parse(_payload(_MUTATED_DAILY_PAGE, "Daily", (_DAILY,)), _CONFIG)

    assert result.value["value"].to_list() == [1.257, 99999.999, 1.217]
    assert result.value["time_zone"].unique().to_list() == ["unknown"]
    marker = [issue for issue in result.issues if issue.code == "unverified_marker_value"]
    assert len(marker) == 1
    assert marker[0].severity == "warning"
    assert marker[0].details is not None
    assert marker[0].details["token"] == "99999.999"
    assert marker[0].details["count"] == 1
    assert marker[0].details["first_time"] == "2020-01-02T00:00:00"
    assert marker[0].details["last_time"] == "2020-01-02T00:00:00"
