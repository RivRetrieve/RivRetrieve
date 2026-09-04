from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from rivretrieve._internal.engine import (
    RenderedWindow,
    SourceQuery,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.providers.ch_foen.config import ChFoenRequestCoordinates, config
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
    assert result.value[0].source_coordinates.value == ChFoenRequestCoordinates(
        ("flow", "flow_ls", "height_abs", "height", "temperature")
    )
    assert not isinstance(result.value[0].origin.request_parameters, UnknownOriginFact)
    assert result.value[0].origin.request_parameters["parameters"] == "flow,flow_ls,height_abs,height,temperature"


def test_old_request_replays_exact_flux_body_and_preserves_query_origin():
    recording = read_recording(DATA / "ch_foen_2135_flux_2020-01-01.recording.json")
    replay = AuthenticatedTransport(
        ReplayTransport((recording,)),
        (CredentialHeader("Authorization", "Token SENTINEL-NOT-A-REAL-TOKEN", ("https://influx.konzept.space",)),),
    )
    rendered = MappingProxyType(
        {p: (RenderedWindow("2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z"),) for p in PRODUCTS}
    )
    result = fetch(
        ("2135",), PRODUCTS, rendered, window("2020-01-01T00:00:00", "2020-01-01T01:00:00"), config(), replay
    )
    (payload,) = result.value
    assert isinstance(payload.origin.query, SourceQuery)
    assert "flow_ls" in payload.origin.query.statement
    assert isinstance(recording.request.body, str)
    assert payload.origin.query == SourceQuery(statement=recording.request.body, parameters=())
    assert payload.origin.request_parameters == {"org": "api.existenz.ch"}


def test_driver_selects_exclusive_flux_route_and_exact_replays_closed_window(monkeypatch) -> None:
    from datetime import timedelta

    import rivretrieve._internal.driver as driver_module
    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.engine import ObservationRequest, RequestedWindow
    from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.ch_foen.declaration import declaration
    from rivretrieve._internal.providers.registration import LiveStages

    recording = read_recording(DATA / "ch_foen_2135_flux_2020-01-01.recording.json")
    transport = AuthenticatedTransport(
        ReplayTransport((recording,)),
        (CredentialHeader("Authorization", "Token SENTINEL-NOT-A-REAL-TOKEN", ("https://influx.konzept.space",)),),
    )
    assert isinstance(declaration.observations, LiveStages)
    monkeypatch.setattr(driver_module, "_FETCH_WINDOW_PADDING", timedelta(0))
    request = ObservationRequest(
        ProviderId("ch_foen"),
        ("2135",),
        PRODUCTS,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2020, 1, 1, 0, 59, 59, 999999)),
        ),
    )
    result = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="recording", provider_id=ProviderId("ch_foen")),
        transport=transport,
    )
    assert result.canonical_rows.height == 18
    assert result.canonical_rows["time"].min() == datetime(2020, 1, 1)
    assert result.canonical_rows["time"].max() == datetime(2020, 1, 1, 0, 50)
    assert result.provenance.endpoints == ("https://influx.konzept.space/api/v2/query",)
    assert result.provenance.retrieved_at == recording.retrieved_at
    assert result.provenance.query == {"statement": recording.request.body, "parameters": ()}
    assert len(result.provenance.calls_made) == len(PRODUCTS)
    assert result.provenance.calls_made[0]["query"] == result.provenance.query
    included = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="recording", provider_id=ProviderId("ch_foen")),
        receipts=ReceiptMode.INCLUDE,
        transport=AuthenticatedTransport(
            ReplayTransport((recording,)),
            (
                CredentialHeader(
                    "Authorization",
                    "Token SENTINEL-NOT-A-REAL-TOKEN",
                    ("https://influx.konzept.space",),
                ),
            ),
        ),
    )
    assert included.provenance == result.provenance
    assert len(included.receipts.entries) == len(PRODUCTS)
    public_json = result.provenance.model_dump_json()
    assert "SENTINEL-NOT-A-REAL-TOKEN" not in public_json
    assert "authorization" not in public_json.lower()
    assert "header" not in public_json.lower()
    assert set(result.provenance.calls_made[0]) == {
        "url",
        "request_parameters",
        "status_code",
        "retrieved_at",
        "content_type",
        "source_path",
        "query",
    }
