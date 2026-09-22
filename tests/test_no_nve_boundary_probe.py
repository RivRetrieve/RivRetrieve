"""Norway exact HydAPI boundary : RecordingEnvelope → source-backed UTC rows.

The three literals of every probe below were authored from the committed recordings and
the NVE HydAPI documentation by an author with no access to the port's code or output,
as the source-recording contract requires. They are pasted verbatim.
"""

from datetime import datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    LiveBoundaryProbe,
    WallClockExpectation,
    run_manifest_boundary_probes,
)
from rivretrieve._internal.engine import (
    Payload,
    RenderedWindow,
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates, config
from rivretrieve._internal.providers.no_nve.parse import parse
from rivretrieve._internal.providers.registration import load_manifest
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.transport import TransportRequest

_PROVIDER = ProviderId("no_nve")
_STATION = "1.200.0"
_DATA = Path(__file__).parent / "test_data"
_DECLARED = load_manifest((_PROVIDER,))
_WINDOW = RenderedWindow("2025-07-08T00:00:00Z", "2025-07-14T00:00:00Z")

# Independently authored expectations, one row per recorded series.
_EXPECTED = {
    ProductId("stage_instantaneous"): (145, "2025-07-08T00:00:00", "2025-07-14T00:00:00"),
    ProductId("stage_hourly_mean"): (145, "2025-07-08T00:00:00", "2025-07-14T00:00:00"),
    ProductId("stage_daily_mean"): (6, "2025-07-08T11:00:00", "2025-07-13T11:00:00"),
    ProductId("discharge_instantaneous"): (145, "2025-07-08T00:00:00", "2025-07-14T00:00:00"),
    ProductId("discharge_hourly_mean"): (145, "2025-07-08T00:00:00", "2025-07-14T00:00:00"),
    ProductId("discharge_daily_mean"): (6, "2025-07-08T11:00:00", "2025-07-13T11:00:00"),
    ProductId("water_temperature_instantaneous"): (145, "2025-07-08T00:00:00", "2025-07-14T00:00:00"),
    ProductId("water_temperature_hourly_mean"): (145, "2025-07-08T00:00:00", "2025-07-14T00:00:00"),
    ProductId("water_temperature_daily_mean"): (6, "2025-07-08T11:00:00", "2025-07-13T11:00:00"),
}
_ZONE = "+00:00"


def recording_path(product_id: ProductId) -> Path:
    coordinates = config().products[product_id].coordinates.value
    assert isinstance(coordinates, NoNveSourceCoordinates)
    return _DATA / (
        f"no_nve_{_STATION}_{coordinates.parameter}_{coordinates.resolution_time}_2025-07-08_2025-07-14.recording.json"
    )


def _run(product_id: ProductId, replay: ReplayTransport) -> pl.DataFrame:
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 7, 8)),
        WindowEndpoint.from_datetime(datetime(2025, 7, 14)),
    )
    # Replay the exact historical omitted-version request, without claiming it is an all-version call.
    recording = read_recording(recording_path(product_id))
    request = recording.request
    response = replay.send(
        TransportRequest(
            request.method,
            request.url,
            request.parameters,
            {name: value for name, value in request.ordinary_headers.items() if name.lower() != "user-agent"},
            request.body,
        )
    )
    unknown = UnknownOriginFact()
    payload = Payload(
        config().products[product_id].coordinates,
        ((_STATION, product_id),),
        window,
        response.content,
        SourceCallOrigin(
            response.url,
            response.request_parameters,
            response.status_code,
            response.retrieved_at,
            response.content_type,
            unknown,
            unknown,
        ),
        response.prerequisite_calls,
    )
    return parse(payload, config()).rows


def _probe(product_id: ProductId) -> LiveBoundaryProbe:
    count, first, last = _EXPECTED[product_id]
    return LiveBoundaryProbe(
        provider_id=_PROVIDER,
        product_id=product_id,
        recordings=(read_recording(recording_path(product_id)),),
        assertions={
            READING_COUNT: count,
            FIRST_WALL_CLOCK_TIME: WallClockExpectation(first, _ZONE),
            LAST_WALL_CLOCK_TIME: WallClockExpectation(last, _ZONE),
        },
        run=lambda replay: _run(product_id, replay),
    )


def test_every_norwegian_product_has_an_exact_live_replay_probe() -> None:
    results = run_manifest_boundary_probes(_DECLARED, tuple(_probe(product) for product in _EXPECTED))
    assert len(results) == len(config().products)
