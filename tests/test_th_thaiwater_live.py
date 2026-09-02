"""ThaiWater live adapter proofs over the recorded official graph response."""

from datetime import datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    LiveBoundaryProbe,
    WallClockExpectation,
    run_boundary_probes,
)
from rivretrieve._internal.engine import FetchWindow, RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.th_thaiwater.declaration import declaration
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_PROVIDER = ProviderId("th_thaiwater")
_PRODUCTS = (ProductId("discharge_instantaneous"), ProductId("stage_instantaneous"))
_RECORDING = read_recording(
    Path(__file__).parent / "test_data/th_thaiwater_1373273_2026-08-01_2026-08-02.recording.json"
)
assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages


def _fetch_window() -> FetchWindow:
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 8, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 8, 2, 23, 59, 59)),
    )


def _run(product: ProductId, replay: ReplayTransport) -> pl.DataFrame:
    fetched = _STAGES.fetch(
        ("1373273",),
        (product,),
        {product: (RenderedWindow("2026-08-01", "2026-08-02"),)},
        _fetch_window(),
        _STAGES.config,
        replay,
    )
    return _STAGES.parse(fetched.value[0], _STAGES.config).value


def _probe(product: ProductId) -> LiveBoundaryProbe:
    return LiveBoundaryProbe(
        provider_id=_PROVIDER,
        product_id=product,
        recordings=(_RECORDING,),
        assertions={
            READING_COUNT: 288,
            FIRST_WALL_CLOCK_TIME: WallClockExpectation("2026-08-01T00:00:00", "unknown"),
            LAST_WALL_CLOCK_TIME: WallClockExpectation("2026-08-02T23:50:00", "unknown"),
        },
        run=lambda replay: _run(product, replay),
    )


def test_each_thaiwater_product_has_an_exact_live_replay_probe() -> None:
    run_boundary_probes(
        tuple((_PROVIDER, product) for product in _PRODUCTS), tuple(_probe(product) for product in _PRODUCTS)
    )


def test_one_graph_response_coalesces_both_products() -> None:
    replay = ReplayTransport((_RECORDING,))
    rendered = (RenderedWindow("2026-08-01", "2026-08-02"),)
    fetched = _STAGES.fetch(
        ("1373273",),
        _PRODUCTS,
        dict.fromkeys(_PRODUCTS, rendered),
        _fetch_window(),
        _STAGES.config,
        replay,
    )

    assert len(fetched.value) == 1
    assert fetched.value[0].station_products == tuple(("1373273", product) for product in _PRODUCTS)
    parsed = _STAGES.parse(fetched.value[0], _STAGES.config).value
    assert parsed.group_by("product_id").len().sort("product_id").rows() == [
        ("discharge_instantaneous", 288),
        ("stage_instantaneous", 288),
    ]
    assert parsed["time_zone"].unique().to_list() == ["unknown"]
