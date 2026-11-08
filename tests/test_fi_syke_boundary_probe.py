"""Finland SYKE exact Hydrologiarajapinta boundary : RecordingEnvelope -> source-backed rows.

The reading counts and first/last wall-clock labels below are read directly off
the committed recordings (one GET per product, no day-boundary splitting to
reason about -- SYKE's Aika values are plain daily labels), as the
source-recording contract requires. They are pasted verbatim.
"""

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

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
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.fi_syke.config import config
from rivretrieve._internal.providers.fi_syke.parse import parse
from rivretrieve._internal.providers.registration import load_manifest
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.transport import TransportRequest

_PROVIDER = ProviderId("fi_syke")
_DATA = Path("tests/test_data")
_DECLARED = load_manifest((_PROVIDER,))
_ZONE = "unknown"

# station, recording name, window start/end -- one real GET per product.
_STATIONS = {
    ProductId("discharge_reported"): "894",
    ProductId("stage_reported"): "2471",
    ProductId("water_temperature_reported"): "1685",
}
_WINDOWS = {
    ProductId("discharge_reported"): (datetime(2026, 10, 29), datetime(2026, 11, 7)),
    ProductId("stage_reported"): (datetime(2026, 10, 15), datetime(2026, 11, 7)),
    ProductId("water_temperature_reported"): (datetime(2026, 10, 29), datetime(2026, 11, 7)),
}
# Independently authored expectations, one row per recorded product.
_EXPECTED = {
    ProductId("discharge_reported"): (9, "2026-10-29T00:00:00", "2026-11-06T00:00:00"),
    ProductId("stage_reported"): (14, "2026-10-15T00:00:00", "2026-10-28T00:00:00"),
    ProductId("water_temperature_reported"): (10, "2026-10-29T00:00:00", "2026-11-07T00:00:00"),
}


def recording_path(product_id: ProductId) -> Path:
    station = _STATIONS[product_id]
    quantity = {
        "discharge_reported": "discharge",
        "stage_reported": "stage",
        "water_temperature_reported": "temperature",
    }[product_id]
    return _DATA / f"fi_syke_{quantity}_{station}_recent_page01.recording.json"


def _run(retained_evidence_root, product_id: ProductId, replay: ReplayTransport) -> pl.DataFrame:
    start, end = _WINDOWS[product_id]
    window = _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))
    recording = read_recording(retained_evidence_root / recording_path(product_id))
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
        ((_STATIONS[product_id], product_id),),
        window,
        response.content,
        SourceCallOrigin(
            response.url,
            response.request_parameters,
            response.status_code,
            response.retrieved_at,
            response.content_type if response.content_type is not None else unknown,
            unknown,
            unknown,
        ),
        response.prerequisite_calls,
    )
    return parse(payload, config()).rows


def _probe(retained_evidence_root, product_id: ProductId) -> LiveBoundaryProbe:
    count, first, last = _EXPECTED[product_id]
    return LiveBoundaryProbe(
        provider_id=_PROVIDER,
        product_id=product_id,
        recordings=(read_recording(retained_evidence_root / recording_path(product_id)),),
        assertions={
            READING_COUNT: count,
            FIRST_WALL_CLOCK_TIME: WallClockExpectation(first, _ZONE),
            LAST_WALL_CLOCK_TIME: WallClockExpectation(last, _ZONE),
        },
        run=lambda replay: _run(retained_evidence_root, product_id, replay),
    )


@pytest.mark.recorded(
    "tests/test_data/fi_syke_discharge_894_recent_page01.recording.json",
    "tests/test_data/fi_syke_stage_2471_recent_page01.recording.json",
    "tests/test_data/fi_syke_temperature_1685_recent_page01.recording.json",
)
def test_every_fi_syke_product_has_an_exact_live_replay_probe(retained_evidence_root) -> None:
    results = run_manifest_boundary_probes(
        _DECLARED, tuple(_probe(retained_evidence_root, product) for product in _EXPECTED)
    )
    assert len(results) == len(config().products)
