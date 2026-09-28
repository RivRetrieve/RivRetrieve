"""Lithuania live adapter proofs over the recorded official monthly response."""

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
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    FetchWindow,
    ObservationRequest,
    RequestedWindow,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.lt_lhmt.declaration import declaration
from rivretrieve._internal.providers.registration import LiveStages, load_manifest
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.window_planning import plan_windows

_PROVIDER = ProviderId("lt_lhmt")
_PRODUCTS = (ProductId("discharge_daily_mean"), ProductId("stage_daily_mean"))
_DECLARED = load_manifest((_PROVIDER,))
_RECORDING_PATH = Path(__file__).parent / "test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json"
_RECORDING = read_recording(_RECORDING_PATH)

assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages


def _fetch_window() -> FetchWindow:
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 6, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 6, 30)),
    )


def _run(product: ProductId, replay: ReplayTransport) -> pl.DataFrame:
    fetched = _STAGES.fetch(
        ("anyksciu-vms",),
        (product,),
        {product: plan_windows(_fetch_window(), _STAGES.window_declarations.products[product])},
        _fetch_window(),
        _STAGES.config,
        replay,
    )
    return _STAGES.parse(fetched.value[0], _STAGES.config).rows


def _probe(product: ProductId) -> LiveBoundaryProbe:
    return LiveBoundaryProbe(
        provider_id=_PROVIDER,
        product_id=product,
        recordings=(_RECORDING,),
        assertions={
            READING_COUNT: 30,
            FIRST_WALL_CLOCK_TIME: WallClockExpectation("2023-06-01T00:00:00", "+00:00"),
            LAST_WALL_CLOCK_TIME: WallClockExpectation("2023-06-30T00:00:00", "+00:00"),
        },
        run=lambda replay: _run(product, replay),
    )


def test_each_lithuania_product_has_an_exact_live_replay_probe() -> None:
    run_manifest_boundary_probes(_DECLARED, tuple(_probe(product) for product in _PRODUCTS))


def test_both_product_series_share_one_monthly_response_and_receipt() -> None:
    replay = ReplayTransport((_RECORDING,))
    result = drive(
        ObservationRequest(
            provider_id=_PROVIDER,
            stations=("anyksciu-vms",),
            products=_PRODUCTS,
            window=RequestedWindow(
                start=WindowEndpoint.from_datetime(datetime(2023, 6, 3)),
                end=WindowEndpoint.from_datetime(datetime(2023, 6, 28)),
            ),
        ),
        _STAGES,
        provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
        receipts=ReceiptMode.INCLUDE,
        transport=replay,
    )

    assert result.canonical_rows.group_by("product_id").len().sort("product_id").rows() == [
        ("discharge_daily_mean", 26),
        ("stage_daily_mean", 26),
    ]
    assert len(result.receipts.entries) == 1
    assert result.receipts.entries[0].content == _RECORDING.content
