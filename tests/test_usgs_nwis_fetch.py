from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast, get_type_hints

import pytest

from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    FetchWindow,
    Instant,
    ProductConfig,
    ProviderConfig,
    RenderedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    Unit,
    UnknownOriginFact,
    WindowEndpoint,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis import fetch as fetch_module
from rivretrieve._internal.providers.usgs_nwis.config import (
    UsgsNwisSourceCoordinates,
    config,
)
from rivretrieve._internal.providers.usgs_nwis.fetch import fetch
from rivretrieve._internal.providers.usgs_nwis.parse import parse
from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    CredentialHeader,
    HttpClient,
    HttpMethod,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

RETRIEVED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

Action = TransportResponse | TransportFailure


class FixedClock:
    def monotonic(self) -> float:
        return 0.0

    def utcnow(self) -> datetime:
        return RETRIEVED_AT


class RecordingHttpClient:
    def __init__(self, actions: list[Action]) -> None:
        self.actions = actions
        self.requests: list[TransportRequest] = []
        self.constructor_calls = 0

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        action = self.actions[len(self.requests) - 1]
        if isinstance(action, TransportFailure):
            raise action
        return TransportResponse(
            content=action.content,
            status_code=action.status_code,
            retrieved_at=action.retrieved_at,
            content_type=action.content_type,
            url=request.url,
            request_parameters={} if request.params is None else request.params,
        )


def _window() -> FetchWindow:
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 1, 10, 23, 59, 59, 999999)),
    )


def _renderings(
    *products: ProductId,
    windows: dict[ProductId, tuple[RenderedWindow, ...]] | None = None,
) -> Mapping[ProductId, tuple[RenderedWindow, ...]]:
    return MappingProxyType(
        dict(windows)
        if windows is not None
        else {product: (RenderedWindow("2023-01-01", "2023-01-10"),) for product in products}
    )


def _response(
    content: bytes, status_code: int = 200, content_type: str | None = "application/json; charset=utf-8"
) -> TransportResponse:
    return TransportResponse(
        content=content,
        status_code=status_code,
        retrieved_at=RETRIEVED_AT,
        content_type=content_type,
        url="https://source.example/data",
        request_parameters={},
    )


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    actions: list[Action],
) -> RecordingHttpClient:
    del monkeypatch
    return RecordingHttpClient(actions)


def _custom_config() -> ProviderConfig:
    return ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId("custom_daily"): ProductConfig(
                coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("dv", "12345", "54321")),
                unit=Unit.FT3_S,
                semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
            ),
            ProductId("custom_instant"): ProductConfig(
                coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("iv", "67890", None)),
                unit=Unit.FT,
                semantics=Instant(),
            ),
        },
    )


def _failure(secret: str, status_code: int | None) -> TransportFailure:
    request = TransportRequest(
        method=HttpMethod.GET,
        url=f"https://do-not-leak.example/data?token={secret}",
        params={"api_key": secret},
        headers={"Accept": "application/json"},
        body=secret,
    )
    return TransportFailure(
        request,
        TransportFailureReason.RETRY_EXHAUSTED,
        3,
        status_code=status_code,
    )


def test_fetch_signature_accepts_engine_renderings_and_fetch_window_tag() -> None:
    hints = get_type_hints(fetch)

    assert hints["rendered_windows"] == Mapping[ProductId, tuple[RenderedWindow, ...]]
    assert hints["fetch_window"] is FetchWindow
    assert "RequestedWindow" not in repr(hints)


def test_fetch_builds_dv_and_iv_requests_from_config_and_preserves_payload_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daily_bytes = b"daily-bytes"
    instant_bytes = b"instant-bytes"
    client = _patch_client(
        monkeypatch,
        [_response(daily_bytes), _response(instant_bytes)],
    )
    provider_config = _custom_config()
    window = _window()
    daily = ProductId("custom_daily")
    instant = ProductId("custom_instant")

    result = fetch(
        ("01234567",),
        (daily, instant),
        _renderings(
            windows={
                daily: (RenderedWindow("1999-02-03", "1999-02-04"),),
                instant: (RenderedWindow("2001-06-07", "2001-06-08"),),
            }
        ),
        window,
        provider_config,
        client,
    )

    assert client.requests == [
        TransportRequest(
            method=HttpMethod.GET,
            url="https://waterservices.usgs.gov/nwis/dv/",
            params={
                "format": "json",
                "sites": "01234567",
                "startDT": "1999-02-03",
                "endDT": "1999-02-04",
                "parameterCd": "12345",
                "statCd": "54321",
            },
            headers={"Accept": "application/json"},
        ),
        TransportRequest(
            method=HttpMethod.GET,
            url="https://waterservices.usgs.gov/nwis/iv/",
            params={
                "format": "json",
                "sites": "01234567",
                "startDT": "2001-06-07",
                "endDT": "2001-06-08",
                "parameterCd": "67890",
            },
            headers={"Accept": "application/json"},
        ),
    ]
    assert result.issues == ()
    assert len(result.value) == 2
    assert result.value[0].source_coordinates is provider_config.products[daily].coordinates
    assert result.value[0].station_products == (("01234567", daily),)
    assert result.value[0].fetch_window is window
    assert result.value[0].content is daily_bytes
    assert result.value[0].origin == SourceCallOrigin(
        url="https://waterservices.usgs.gov/nwis/dv/",
        request_parameters={
            "format": "json",
            "sites": "01234567",
            "startDT": "1999-02-03",
            "endDT": "1999-02-04",
            "parameterCd": "12345",
            "statCd": "54321",
        },
        status_code=200,
        retrieved_at=RETRIEVED_AT,
        content_type="application/json; charset=utf-8",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )
    assert result.value[1].source_coordinates is provider_config.products[instant].coordinates
    assert result.value[1].station_products == (("01234567", instant),)
    assert result.value[1].fetch_window is window
    assert result.value[1].content is instant_bytes
    assert result.value[1].origin == SourceCallOrigin(
        url="https://waterservices.usgs.gov/nwis/iv/",
        request_parameters={
            "format": "json",
            "sites": "01234567",
            "startDT": "2001-06-07",
            "endDT": "2001-06-08",
            "parameterCd": "67890",
        },
        status_code=200,
        retrieved_at=RETRIEVED_AT,
        content_type="application/json; charset=utf-8",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )
    for payload in result.value:
        assert "headers" not in {field.name for field in fields(payload.origin)}
        scanned = tuple(str(getattr(payload.origin, field.name)) for field in fields(payload.origin))
        for forbidden in (
            "Accept",
            "Authorization",
            "X-API-Key",
            "Bearer transport-secret",
            "api-key-secret",
        ):
            assert all(forbidden not in candidate for candidate in scanned)


def test_missing_response_media_type_becomes_unknown_origin_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(monkeypatch, [_response(b"{}", content_type=None)])

    result = fetch(
        ("station-1",),
        (ProductId("discharge_instantaneous"),),
        _renderings(ProductId("discharge_instantaneous")),
        _window(),
        config(),
        client,
    )

    assert isinstance(result.value[0].origin.content_type, UnknownOriginFact)


def test_transport_credentials_do_not_reach_final_payload_origin() -> None:
    source_request = TransportRequest(
        method=HttpMethod.GET,
        url="https://waterservices.usgs.gov/nwis/dv/",
        params={"format": "json", "sites": "01234567"},
        headers={"Accept": "application/json"},
    )
    sent_requests: list[TransportRequest] = []

    def sender(request: TransportRequest, _timeout_seconds: float) -> tuple[bytes, int, str | None]:
        sent_requests.append(request)
        return b"daily-bytes", 200, "application/json; charset=utf-8"

    response = AuthenticatedTransport(
        HttpClient(sender=sender, clock=FixedClock()),
        (
            CredentialHeader("Authorization", "Bearer transport-secret", ("https://waterservices.usgs.gov",)),
            CredentialHeader("X-API-Key", "api-key-secret", ("https://waterservices.usgs.gov",)),
        ),
    ).send(source_request)
    product = ProductId("custom_daily")
    provider_config = _custom_config()
    payload = fetch_module._payload(
        provider_config.products[product].coordinates,
        "01234567",
        product,
        _window(),
        response,
    )

    assert len(sent_requests) == 1
    executed = sent_requests[0]
    assert executed.method is HttpMethod.GET
    assert executed.url == source_request.url
    assert dict(executed.headers) == {
        "Accept": "application/json",
        "Authorization": "Bearer transport-secret",
        "X-API-Key": "api-key-secret",
        "User-Agent": "RivRetrieve",
    }
    assert cast("Any", executed).credential_header_names == ("Authorization", "X-API-Key")

    forbidden = (
        "Authorization",
        "Bearer transport-secret",
        "X-API-Key",
        "api-key-secret",
    )
    request_scan = tuple(str(value) for value in fields(TransportRequest))
    request_scan += tuple(str(getattr(source_request, field.name)) for field in fields(source_request))
    for value in forbidden:
        assert all(value not in candidate for candidate in request_scan)

    assert "headers" not in {field.name for field in fields(payload.origin)}
    origin_scan = tuple(str(getattr(payload.origin, field.name)) for field in fields(payload.origin))
    for value in forbidden:
        assert all(value not in candidate for candidate in origin_scan)


def test_non_success_response_is_handed_to_the_engine_without_provider_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(monkeypatch, [_response(b"not found", 404)])
    product = ProductId("stage_instantaneous")

    result = fetch(("station-1",), (product,), _renderings(product), _window(), config(), client)

    (payload,) = result.value
    assert payload.origin.status_code == 404
    assert payload.content == b"not found"
    assert result.issues == ()


def test_transport_failure_propagates_to_the_engine_isolation_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = _failure("transport-secret", None)
    client = _patch_client(monkeypatch, [failure])
    product = ProductId("stage_instantaneous")

    with pytest.raises(TransportFailure) as raised:
        fetch(("station-1",), (product,), _renderings(product), _window(), config(), client)

    assert raised.value is failure
    assert "transport-secret" not in str(raised.value)


def test_successful_malformed_body_stays_opaque_until_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(monkeypatch, [_response(b"not-json")])
    provider_config = config()

    fetched = fetch(
        ("station-1",),
        (ProductId("discharge_instantaneous"),),
        _renderings(ProductId("discharge_instantaneous")),
        _window(),
        provider_config,
        client,
    )

    assert len(fetched.value) == 1
    assert fetched.value[0].content == b"not-json"
    assert fetched.issues == ()
    parsed = parse(fetched.value[0], provider_config)
    assert parsed.outcomes[0].status == "unsupported"
    assert parsed.issues


def test_usgs_fetch_uses_engine_rendered_dates_without_reading_fetch_window_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(monkeypatch, [_response(b"{}")])
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1, 12, 34, 56, 123456)),
        WindowEndpoint.from_datetime(datetime(2023, 1, 10, 23, 59, 59, 999999)),
    )

    result = fetch(
        ("station-1",),
        (ProductId("discharge_instantaneous"),),
        _renderings(windows={ProductId("discharge_instantaneous"): (RenderedWindow("1984-03-04", "1984-03-05"),)}),
        window,
        config(),
        client,
    )

    assert client.requests[0].params["startDT"] == "1984-03-04"
    assert client.requests[0].params["endDT"] == "1984-03-05"
    assert result.value[0].fetch_window is window
    assert result.issues == ()


def test_fetch_fails_loudly_for_missing_or_wrong_coordinate_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    wrong_coordinates = ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId("wrong"): ProductConfig(
                coordinates=SourceCoordinates(object()),
                unit=Unit.FT,
                semantics=Instant(),
            )
        },
    )

    with pytest.raises(FatalContractError, match="absent"):
        fetch(
            ("station-1",),
            (ProductId("absent"),),
            _renderings(ProductId("absent")),
            _window(),
            wrong_coordinates,
            RecordingHttpClient([]),
        )
    with pytest.raises(FatalContractError, match="invalid source coordinates"):
        fetch(
            ("station-1",),
            (ProductId("wrong"),),
            _renderings(ProductId("wrong")),
            _window(),
            wrong_coordinates,
            RecordingHttpClient([]),
        )
