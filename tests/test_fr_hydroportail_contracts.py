"""HydroPortail internal stage contracts and window declarations."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from rivretrieve._internal.engine import (
    RenderedWindow,
    StopConvention,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.fr_hydroportail.config import config, window_declarations
from rivretrieve._internal.providers.fr_hydroportail.fetch import fetch
from rivretrieve._internal.providers.fr_hydroportail.parse import parse
from rivretrieve._internal.source_series import SeriesScope
from rivretrieve._internal.transport import Transport, TransportRequest, TransportResponse
from tests.test_fr_hydroportail_station import _empty_payload


@pytest.mark.recorded(
    "tests/test_data/fr_hydroportail_J783301020_empty.body",
    "tests/test_data/fr_hydroportail_J783301020_empty.receipt.json",
)
def test_unknown_payload_product_is_fatal_contract_error(retained_evidence_root):
    payload = replace(_empty_payload(retained_evidence_root), station_products=(("J783301020", ProductId("unknown")),))
    with pytest.raises(FatalContractError):
        parse(payload, config())


def test_hydroportail_window_declarations_use_capped_span() -> None:
    declarations = window_declarations()
    assert set(declarations.products) == set(config().products)
    for declaration in declarations.products.values():
        assert declaration.granularity == WindowGranularity("capped-span")
        assert declaration.rendering == WindowRenderingVocabulary.DATE_DMY
        assert declaration.stop_convention == StopConvention.INCLUSIVE
        assert declaration.size == 1000


class _SyntheticTransport(Transport):
    def __init__(self) -> None:
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        params = dict(request.params)
        body = {
            "series": {
                "code": "Y251002001",
                "metric": params["hydro_series[simpleAndInterpolatedAndHourlyVariable]"],
                "statuses": params["hydro_series[statusData]"],
                "unit": "l",
                "title": "Débit instantané",
                "data": [{"t": "2020-01-01T12:00:00Z", "v": 1500.0, "s": 4, "q": 0, "m": 0, "c": 0}],
            },
            "timezone": "UTC",
        }
        return TransportResponse(
            json.dumps(body).encode(),
            200,
            datetime(2026, 10, 10, tzinfo=UTC),
            "application/json",
            request.url,
            params,
        )


def test_hydroportail_fetch_processes_all_sub_windows() -> None:
    transport = _SyntheticTransport()
    product = ProductId("discharge_instantaneous")
    start1 = WindowEndpoint(2020, 1, 1, 0, 0, 0, 0)
    stop1 = WindowEndpoint(2022, 9, 26, 23, 59, 59, 0)
    start2 = WindowEndpoint(2022, 9, 27, 0, 0, 0, 0)
    stop2 = WindowEndpoint(2025, 1, 1, 23, 59, 59, 0)
    w1 = RenderedWindow("01/01/2020", "26/09/2022", _make_fetch_window(start1, stop1))
    w2 = RenderedWindow("27/09/2022", "01/01/2025", _make_fetch_window(start2, stop2))

    total_window = _make_fetch_window(start1, stop2)
    acquired = fetch(
        ("Y251002001",),
        (product,),
        {product: (w1, w2)},
        total_window,
        config(),
        transport,
        scope=SeriesScope(restriction="explicit", variants=("validated",)),
    )
    assert len(transport.requests) == 2
    assert transport.requests[0].params["hydro_series[startAt]"] == "01/01/2020"
    assert transport.requests[0].params["hydro_series[endAt]"] == "26/09/2022"
    assert transport.requests[1].params["hydro_series[startAt]"] == "27/09/2022"
    assert transport.requests[1].params["hydro_series[endAt]"] == "01/01/2025"

    assert len(acquired.value) == 2
    assert acquired.value[0].fetch_window == w1.bounds
    assert acquired.value[1].fetch_window == w2.bounds
