"""Reject unsupported acquisition batches before any source request is made."""

from datetime import datetime

import pytest

from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ba_fhmzbih.config import config as bosnia_config
from rivretrieve._internal.providers.ba_fhmzbih.fetch import fetch as bosnia_fetch
from rivretrieve._internal.providers.ch_foen.config import config as swiss_config
from rivretrieve._internal.providers.ch_foen.fetch import fetch as swiss_fetch


class NoRequests:
    def send(self, request):
        pytest.fail("Unsupported batch reached source transport")


@pytest.mark.parametrize(
    ("fetch", "config", "stations", "products"),
    [
        (bosnia_fetch, bosnia_config, ("4024", "4110"), ("stage_reported",)),
        (bosnia_fetch, bosnia_config, ("4024",), ("stage_reported", "discharge_reported")),
        (swiss_fetch, swiss_config, ("2135", "2030"), ("stage_reported",)),
    ],
)
def test_unsupported_batches_fail_before_transport(fetch, config, stations, products):
    selected = tuple(ProductId(product) for product in products)
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 9, 2)),
    )
    with pytest.raises(FatalContractError, match="one station"):
        fetch(stations, selected, dict.fromkeys(selected, ()), window, config(), NoRequests())
