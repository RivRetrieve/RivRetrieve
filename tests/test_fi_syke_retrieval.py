"""fi_syke retrieval behavior (#756): nextLink pagination, empty answers, Lippu flags."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType

import polars as pl
import pytest

from rivretrieve._internal.engine import (
    FetchWindow,
    RenderedWindow,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.fi_syke.config import config
from rivretrieve._internal.providers.fi_syke.fetch import fetch
from rivretrieve._internal.providers.fi_syke.parse import parse
from rivretrieve._internal.providers.fi_syke.series import describe_series
from rivretrieve._internal.source_series import OutcomeStatus, admission
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC)
_DISCHARGE = ProductId("discharge_reported")
_STAGE = ProductId("stage_reported")
_TEMPERATURE = ProductId("water_temperature_reported")


def _window(start: datetime, end: datetime) -> FetchWindow:
    return _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _rendered(product: ProductId, fetch_window: FetchWindow) -> MappingProxyType:
    return MappingProxyType(
        {
            product: (
                RenderedWindow(fetch_window.start.isoformat() + "Z", fetch_window.end.isoformat() + "Z", fetch_window),
            )
        }
    )


def _row(paikka_id: int, day: int, value: object, *, flag: int | None = None) -> dict[str, object]:
    return {
        "Paikka_Id": paikka_id,
        "Aika": f"1959-01-{day:02d}T00:00:00",
        "Arvo": value,
        "ArvoMin": None,
        "ArvoMax": None,
        "Lippu_id": flag,
        "huomautus": None,
    }


def _page(rows: list[dict[str, object]], *, next_skip: int | None = None) -> bytes:
    document: dict[str, object] = {"odata.metadata": "x", "value": rows}
    if next_skip is not None:
        document["odata.nextLink"] = (
            "https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata/Virtaama"
            f"?$filter=Paikka_Id%20eq%20894%20and%20Aika%20ge%20datetime%271959-01-01T00%3A00%3A00Z%27"
            f"%20and%20Aika%20le%20datetime%271959-01-10T00%3A00%3A00Z%27&$orderby=Aika%20asc&$skip={next_skip}"
        )
    return json.dumps(document).encode()


class _PagedTransport:
    def __init__(self, pages: list[bytes]) -> None:
        self._pages = list(pages)
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        content = self._pages.pop(0)
        return TransportResponse(
            content, 200, _RETRIEVED_AT, "application/json", request.url, dict(request.params or {})
        )


def test_fetch_follows_nextlink_across_pages_and_never_sets_top() -> None:
    pages = [
        _page([_row(894, i, f"{i}.0") for i in range(1, 6)], next_skip=5),
        _page([_row(894, i, f"{i}.0", flag=1 if i == 9 else None) for i in range(6, 10)]),
    ]
    transport = _PagedTransport(pages)
    fetch_window = _window(datetime(1959, 1, 1), datetime(1959, 1, 10))
    result = fetch(("894",), (_DISCHARGE,), _rendered(_DISCHARGE, fetch_window), fetch_window, config(), transport)

    assert len(result.value) == 2
    assert not result.failed_requests
    assert all("$top" not in (payload.origin.request_parameters or {}) for payload in result.value)
    assert all("$top" not in request.params for request in transport.requests)

    combined = pl.concat([parse(payload, config()).rows for payload in result.value])
    assert combined.height == 9
    assert combined["value"].to_list() == [float(i) for i in range(1, 10)]

    issues = [issue for payload in result.value for issue in parse(payload, config()).issues]
    assert len(issues) == 1
    assert issues[0].code == "source.flag_code"
    assert issues[0].details["source_flag_code"] == 1


def test_fetch_never_follows_a_nextlink_to_a_different_entity_set() -> None:
    malicious = json.dumps(
        {
            "odata.metadata": "x",
            "value": [_row(894, 1, "1.0")],
            "odata.nextLink": "https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata/Vedenkorkeus?$skip=5",
        }
    ).encode()
    transport = _PagedTransport([malicious])
    fetch_window = _window(datetime(1959, 1, 1), datetime(1959, 1, 10))
    result = fetch(("894",), (_DISCHARGE,), _rendered(_DISCHARGE, fetch_window), fetch_window, config(), transport)

    # The one genuine page is kept; paging simply stops rather than following
    # a nextLink that changes the entity set.
    assert len(result.value) == 1
    assert len(transport.requests) == 1


def test_fetch_reports_a_transport_failure_without_crashing() -> None:
    class _FailingTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )

    fetch_window = _window(datetime(1959, 1, 1), datetime(1959, 1, 10))
    result = fetch(
        ("894",), (_DISCHARGE,), _rendered(_DISCHARGE, fetch_window), fetch_window, config(), _FailingTransport()
    )
    assert not result.value
    assert len(result.failed_requests) == 1
    assert result.failed_requests[0].series.station_id == "894"


@pytest.mark.parametrize("product", [_DISCHARGE, _STAGE, _TEMPERATURE])
def test_parse_empty_response_is_an_empty_outcome_not_a_failure(product: ProductId) -> None:
    transport = _PagedTransport([_page([])])
    fetch_window = _window(datetime(2030, 1, 1), datetime(2030, 1, 10))
    result = fetch(("894",), (product,), _rendered(product, fetch_window), fetch_window, config(), transport)
    parsed = parse(result.value[0], config())
    assert parsed.rows.height == 0
    assert parsed.outcomes[0].status is OutcomeStatus.EMPTY


@pytest.mark.parametrize(
    ("product", "expected_unit", "expected_target", "expected_factor"),
    [
        (_DISCHARGE, "m3/s", "m3/s", 1.0),
        (_STAGE, "cm", "m", 0.01),
        (_TEMPERATURE, "°C", "degC", 1.0),
    ],
)
def test_admission_supports_all_three_products_with_correct_native_unit_and_factor(
    product: ProductId, expected_unit: str, expected_target: str, expected_factor: float
) -> None:
    series = describe_series("894", str(product))
    fact = series.facts[0]
    assert fact.source_unit.value == expected_unit
    result = admission(fact)
    assert result.status == "supported"
    assert result.target_unit == expected_target
    assert result.factor == expected_factor


def test_stage_series_carries_above_sea_level_vertical_reference_others_do_not() -> None:
    stage = describe_series("1721", str(_STAGE)).facts[0]
    discharge = describe_series("894", str(_DISCHARGE)).facts[0]
    temperature = describe_series("1685", str(_TEMPERATURE)).facts[0]
    assert stage.vertical_reference.value == "above_sea_level"
    assert discharge.vertical_reference.state == "not_established"
    assert temperature.vertical_reference.state == "not_established"
