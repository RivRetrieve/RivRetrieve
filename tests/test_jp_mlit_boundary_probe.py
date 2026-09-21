"""MLIT source-boundary probes cover all four corrected products."""

from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import polars as pl

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    BoundaryProbe,
    WallClockExpectation,
    run_boundary_probes,
)
from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.jp_mlit.config import config
from rivretrieve._internal.providers.jp_mlit.fetch import fetch
from rivretrieve._internal.providers.jp_mlit.parse import parse
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_DATA = Path(__file__).parent / "test_data"
_PROVIDER = ProviderId("jp_mlit")
_STATION = "301011281104010"
_CASES = (
    (ProductId("stage_hourly"), 744, "2023-01-01T01:00:00", "2023-02-01T00:00:00"),
    (ProductId("stage_daily"), 365, "2023-01-01T00:00:00", "2023-12-31T00:00:00"),
    (ProductId("discharge_hourly"), 192, "2023-01-01T01:00:00", "2023-01-31T12:00:00"),
    (ProductId("discharge_daily"), 365, "2023-01-01T00:00:00", "2023-12-31T00:00:00"),
)


def _recordings(product: ProductId):
    return (
        read_recording(_DATA / f"jp_mlit_{product}_2023_html.recording.json"),
        read_recording(_DATA / f"jp_mlit_{product}_2023_dat.recording.json"),
    )


def _runner(product: ProductId):
    def run(replay: ReplayTransport):
        hourly = "hourly" in product
        start, stop = "2023-01-01", "2023-01-31" if hourly else "2023-12-31"
        window = _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2023, 1, 31) if hourly else datetime(2023, 12, 31)),
        )
        payloads = fetch(
            (_STATION,),
            (product,),
            MappingProxyType({product: (RenderedWindow(start, stop),)}),
            window,
            config(),
            replay,
        ).value
        return pl.concat([parse(payload, config()).rows for payload in payloads])

    return run


def test_every_product_has_exact_two_call_source_boundary_probe() -> None:
    probes = tuple(
        BoundaryProbe(
            provider_id=_PROVIDER,
            product_id=product,
            recordings=_recordings(product),
            assertions={
                READING_COUNT: count,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation(first, "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation(last, "unknown"),
            },
            run=_runner(product),
        )
        for product, count, first, last in _CASES
    )
    results = run_boundary_probes(tuple((_PROVIDER, product) for product, *_ in _CASES), probes)
    assert sorted(frame.height for frame in results) == [192, 365, 365, 744]
