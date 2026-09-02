from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from rivretrieve._internal.engine import (
    RenderedWindow,
    SourceQuery,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.providers.ch_foen.config import config
from rivretrieve._internal.providers.ch_foen.fetch import fetch
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader

DATA = Path("tests/test_data")
PRODUCTS = tuple(config().products)


def window(a, b):
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime.fromisoformat(a)), WindowEndpoint.from_datetime(datetime.fromisoformat(b))
    )


def test_recent_request_replays_exact_anonymous_rest_envelope_and_coalesces_fields():
    replay = ReplayTransport((read_recording(DATA / "ch_foen_2135_rest_2026-09-01.recording.json"),))
    rendered = MappingProxyType(
        {p: (RenderedWindow("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"),) for p in PRODUCTS}
    )
    result = fetch(
        ("2135",), PRODUCTS, rendered, window("2026-09-01T00:00:00", "2026-09-02T00:00:00"), config(), replay
    )
    assert result.issues == () and len(result.value) == 1
    assert result.value[0].station_products == tuple(("2135", p) for p in PRODUCTS)
    assert result.value[0].origin.request_parameters["parameters"] == "flow,flow_ls,height_abs,height,temperature"


def test_old_request_replays_exact_flux_body_and_preserves_query_origin():
    recording = read_recording(DATA / "ch_foen_2135_flux_2020-01-01.recording.json")

    class SourceResponse:
        def __init__(self):
            self.request = None

        def send(self, request):
            self.request = request
            return recording.to_transport_response()

    source = SourceResponse()
    replay = AuthenticatedTransport(
        source,
        (CredentialHeader("Authorization", "Token SENTINEL-NOT-A-REAL-TOKEN", ("https://influx.konzept.space",)),),
    )
    rendered = MappingProxyType(
        {p: (RenderedWindow("2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z"),) for p in PRODUCTS}
    )
    result = fetch(
        ("2135",), PRODUCTS, rendered, window("2020-01-01T00:00:00", "2020-01-01T01:00:00"), config(), replay
    )
    (payload,) = result.value
    assert "flow_ls" in payload.origin.query.statement
    assert source.request.headers["Authorization"] == "Token SENTINEL-NOT-A-REAL-TOKEN"
    assert payload.origin.query == SourceQuery(statement=recording.request.body, parameters=())
    assert payload.origin.request_parameters == {"org": "api.existenz.ch"}
