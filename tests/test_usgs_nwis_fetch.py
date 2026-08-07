from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import get_type_hints

import polars as pl
import pytest

from rivretrieve._internal.engine import (
    Daily,
    DayDefinition,
    FetchWindow,
    Instant,
    ProductConfig,
    ProviderConfig,
    RenderedWindow,
    SourceCoordinates,
    Unit,
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
    HttpMethod,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json")
RETRIEVED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

Action = TransportResponse | TransportFailure


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
        return action


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


def _response(content: bytes, status_code: int = 200) -> TransportResponse:
    return TransportResponse(
        content=content,
        status_code=status_code,
        retrieved_at=RETRIEVED_AT,
    )


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    actions: list[Action],
) -> RecordingHttpClient:
    client = RecordingHttpClient(actions)

    def client_factory() -> RecordingHttpClient:
        client.constructor_calls += 1
        return client

    monkeypatch.setattr(fetch_module, "HttpClient", client_factory)
    return client


def _custom_config() -> ProviderConfig:
    return ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId("custom_daily"): ProductConfig(
                coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("dv", "12345", "54321")),
                unit=Unit.FT3_S,
                semantics=Daily(DayDefinition("unknown")),
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
        headers={"Authorization": f"Bearer {secret}"},
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
    client = _patch_client(
        monkeypatch,
        [_response(b"daily-bytes"), _response(b"instant-bytes")],
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
    assert client.constructor_calls == 1
    assert result.issues == ()
    assert len(result.value) == 2
    assert result.value[0].source_coordinates is provider_config.products[daily].coordinates
    assert result.value[0].station_products == (("01234567", daily),)
    assert result.value[0].fetch_window is window
    assert result.value[0].content == b"daily-bytes"
    assert result.value[1].source_coordinates is provider_config.products[instant].coordinates
    assert result.value[1].station_products == (("01234567", instant),)
    assert result.value[1].fetch_window is window
    assert result.value[1].content == b"instant-bytes"


def test_five_stations_one_404_preserves_four_parsed_station_results_and_one_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = FIXTURE_PATH.read_bytes()
    client = _patch_client(
        monkeypatch,
        [
            _response(fixture),
            _response(fixture),
            _response(b"not found", 404),
            _response(fixture),
            _response(fixture),
        ],
    )
    stations = ("station-1", "station-2", "station-3", "station-4", "station-5")
    product = ProductId("discharge_daily_mean")
    provider_config = config()

    fetched = fetch(stations, (product,), _renderings(product), _window(), provider_config)
    parsed = tuple(parse(payload, provider_config) for payload in fetched.value)
    rows = pl.concat([result.value for result in parsed], how="vertical")
    all_issues = fetched.issues + tuple(issue for result in parsed for issue in result.issues)

    assert client.constructor_calls == 1
    assert len(client.requests) == 5
    assert [payload.station_products[0][0] for payload in fetched.value] == [
        "station-1",
        "station-2",
        "station-4",
        "station-5",
    ]
    assert rows.height == 40
    assert rows["station_id"].unique(maintain_order=True).to_list() == [
        "station-1",
        "station-2",
        "station-4",
        "station-5",
    ]
    assert len(all_issues) == 1
    assert all_issues[0].code == "http_not_found"
    assert all_issues[0].details == {
        "station_id": "station-3",
        "product_id": "discharge_daily_mean",
        "source_coordinates": {
            "endpoint": "dv",
            "parameter_code": "00060",
            "statistic_code": "00003",
        },
        "fetch_window": {"start": "2023-01-01", "end": "2023-01-10"},
        "status_code": 404,
    }


def test_404_does_not_skip_remaining_products_for_station(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(
        monkeypatch,
        [_response(b"not found", 404), _response(b"instant-bytes")],
    )
    daily = ProductId("custom_daily")
    instant = ProductId("custom_instant")

    result = fetch(
        ("station-1",),
        (daily, instant),
        _renderings(daily, instant),
        _window(),
        _custom_config(),
    )

    assert len(client.requests) == 2
    assert [payload.station_products for payload in result.value] == [
        (("station-1", instant),),
    ]
    assert [payload.content for payload in result.value] == [b"instant-bytes"]
    assert [issue.code for issue in result.issues] == ["http_not_found"]
    assert result.issues[0].details is not None
    assert result.issues[0].details["product_id"] == daily


def test_retry_exhaustion_does_not_skip_remaining_products_for_station(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(
        monkeypatch,
        [_failure("first-product-secret", None), _response(b"instant-bytes")],
    )
    daily = ProductId("custom_daily")
    instant = ProductId("custom_instant")

    result = fetch(
        ("station-1",),
        (daily, instant),
        _renderings(daily, instant),
        _window(),
        _custom_config(),
    )

    assert len(client.requests) == 2
    assert [payload.station_products for payload in result.value] == [
        (("station-1", instant),),
    ]
    assert [payload.content for payload in result.value] == [b"instant-bytes"]
    assert [issue.code for issue in result.issues] == ["source_request_failed"]
    assert result.issues[0].details is not None
    assert result.issues[0].details["product_id"] == daily


def test_all_404_returns_empty_payload_tuple_with_every_issue_and_call_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stations = ("station-1", "station-2", "station-3", "station-4", "station-5")
    client = _patch_client(
        monkeypatch,
        [_response(b"not found", 404) for _ in stations],
    )
    product = ProductId("stage_instantaneous")

    result = fetch(stations, (product,), _renderings(product), _window(), config())

    assert len(client.requests) == 5
    assert result.value == ()
    assert len(result.issues) == 5
    assert [issue.code for issue in result.issues] == ["http_not_found"] * 5
    assert [issue.details["station_id"] for issue in result.issues if issue.details] == list(stations)
    for issue in result.issues:
        assert issue.details is not None
        assert issue.details["product_id"] == "stage_instantaneous"
        assert issue.details["source_coordinates"] == {
            "endpoint": "iv",
            "parameter_code": "00065",
            "statistic_code": None,
        }
        assert issue.details["fetch_window"] == {
            "start": "2023-01-01",
            "end": "2023-01-10",
        }
        assert issue.details["status_code"] == 404


def test_retry_exhausted_timeout_dns_and_rate_limit_are_sanitized_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(
        monkeypatch,
        [
            _failure("timeout-secret", None),
            _failure("dns-secret", None),
            _failure("rate-secret", 429),
        ],
    )
    stations = ("timeout-station", "dns-station", "rate-station")
    product = ProductId("discharge_instantaneous")

    result = fetch(stations, (product,), _renderings(product), _window(), config())

    assert len(client.requests) == 3
    assert result.value == ()
    assert [issue.code for issue in result.issues] == [
        "source_request_failed",
        "source_request_failed",
        "source_request_failed",
    ]
    assert [issue.details["failure_reason"] for issue in result.issues if issue.details] == [
        "retry_exhausted",
        "retry_exhausted",
        "retry_exhausted",
    ]
    assert [issue.details["attempts"] for issue in result.issues if issue.details] == [
        3,
        3,
        3,
    ]
    assert [issue.details["status_code"] for issue in result.issues if issue.details] == [
        None,
        None,
        429,
    ]
    serialized = json.dumps(
        [issue.model_dump(mode="json") for issue in result.issues],
        sort_keys=True,
    )
    for forbidden in (
        "timeout-secret",
        "dns-secret",
        "rate-secret",
        "do-not-leak.example",
        "Authorization",
        "api_key",
        "Bearer",
    ):
        assert forbidden not in serialized


def test_terminal_sender_failure_is_a_broken_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = TransportRequest(
        HttpMethod.GET,
        "https://do-not-leak.example",
        headers={"Authorization": "Bearer terminal-secret"},
    )
    failure = TransportFailure(
        request,
        TransportFailureReason.TERMINAL_SENDER_FAILURE,
        1,
    )
    client = _patch_client(monkeypatch, [failure])

    with pytest.raises(TransportFailure) as raised:
        fetch(
            ("station-1",),
            (ProductId("discharge_instantaneous"),),
            _renderings(ProductId("discharge_instantaneous")),
            _window(),
            config(),
        )

    assert raised.value is failure
    assert len(client.requests) == 1


@pytest.mark.parametrize("status_code", [400, 401, 403, 422])
def test_unexpected_terminal_http_status_is_a_broken_seam(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    client = _patch_client(monkeypatch, [_response(b"source error", status_code)])

    with pytest.raises(FatalContractError, match=str(status_code)):
        fetch(
            ("station-1",),
            (ProductId("discharge_instantaneous"),),
            _renderings(ProductId("discharge_instantaneous")),
            _window(),
            config(),
        )

    assert len(client.requests) == 1


def test_successful_malformed_body_stays_opaque_until_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(monkeypatch, [_response(b"not-json")])
    provider_config = config()

    fetched = fetch(
        ("station-1",),
        (ProductId("discharge_instantaneous"),),
        _renderings(ProductId("discharge_instantaneous")),
        _window(),
        provider_config,
    )

    assert len(fetched.value) == 1
    assert fetched.value[0].content == b"not-json"
    assert fetched.issues == ()
    with pytest.raises(FatalContractError, match="not valid JSON"):
        parse(fetched.value[0], provider_config)


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
    )

    assert client.requests[0].params["startDT"] == "1984-03-04"
    assert client.requests[0].params["endDT"] == "1984-03-05"
    assert result.value[0].fetch_window is window
    assert result.issues == ()


def test_fetch_fails_loudly_for_missing_or_wrong_coordinate_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_client() -> RecordingHttpClient:
        raise AssertionError("HttpClient must not be constructed")

    monkeypatch.setattr(fetch_module, "HttpClient", forbidden_client)
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
        )
    with pytest.raises(FatalContractError, match="invalid source coordinates"):
        fetch(
            ("station-1",),
            (ProductId("wrong"),),
            _renderings(ProductId("wrong")),
            _window(),
            wrong_coordinates,
        )
