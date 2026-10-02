"""Swiss exact REST boundary : RecordingEnvelope → source-backed UTC rows."""

from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    BoundaryProbe,
    WallClockExpectation,
    run_boundary_probes,
)
from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ch_foen.config import config
from rivretrieve._internal.providers.ch_foen.fetch import fetch
from rivretrieve._internal.providers.ch_foen.parse import parse
from rivretrieve._internal.recordings import read_recording

_PROVIDER = ProviderId("ch_foen")
_PRODUCTS = tuple(config().products)


def _run(replay):
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 2))
    )
    rendered = MappingProxyType(
        {product: (RenderedWindow("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"),) for product in _PRODUCTS}
    )
    (payload,) = fetch(("2135",), _PRODUCTS, rendered, window, config(), replay).value
    return parse(payload, config()).rows


def test_every_swiss_product_has_exact_rest_boundary_proof(retained_evidence_root: Path):
    recording = read_recording(retained_evidence_root / "tests/test_data/ch_foen_2135_rest_2026-09-01.recording.json")
    probes = tuple(
        BoundaryProbe(
            _PROVIDER,
            product,
            (recording,),
            {
                READING_COUNT: 145,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation("2026-09-01T00:00:00", "+00:00"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation("2026-09-02T00:00:00", "+00:00"),
            },
            _run,
        )
        for product in _PRODUCTS
    )
    assert len(run_boundary_probes(tuple((_PROVIDER, p) for p in _PRODUCTS), probes)) == 3
