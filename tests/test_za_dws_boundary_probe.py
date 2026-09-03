"""South Africa boundary probes : recorded HyData.aspx interactions → source-wall-clock rows.

Evidence manifest
-----------------
Each declared product is proven over one recording captured through the engine transport by
the maintainer command documented in ``docs/provider_ports/za_dws.md`` (``_CAPTURE_COMMANDS``
below). The recorded request is exactly what ``drive`` issues for the requested window named
beside it: two days of outward padding, the ``n-year-chunk`` planner and the exclusive stop.

Independent literals
--------------------
The three literals per product are authored from the recording bytes and the DWS format legend
by someone who has not run this adapter (ADR 0024). Counting rule for the author: every
whitespace-delimited row between the ``DATE ...`` header and the ``ZZZZZZZZZZZZ`` terminator is
one reading, including rows whose value is the ``99999.999`` marker; a Point row is one reading
for each of the two Point products; ``time`` is the row's ``CCYYMMDD`` date (Daily, labelled
``00:00:00``) or ``CCYYMMDD HHMMSS`` (Point); ``time_zone`` is ``unknown`` because the source
states no time standard.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import LiveStages, load_manifest
from rivretrieve._internal.providers.za_dws.declaration import declaration
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_PROVIDER = ProviderId("za_dws")
_STATION = "X3H001"
_DATA = Path(__file__).parent / "test_data"
_DAILY = ProductId("discharge_daily_mean")
_POINT_PRODUCTS = (ProductId("discharge_instantaneous"), ProductId("stage_instantaneous"))

assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages

# Recording file per product, the rendered source window it holds, and the fetch window the
# engine planned it from. The Point recording feeds both Point products from one source call.
_DAILY_RECORDING = _DATA / "za_dws_X3H001_Daily_2019-12-28_2020-01-05.recording.json"
_POINT_RECORDING = _DATA / "za_dws_X3H001_Point_2020-01-03_2020-01-09.recording.json"
_RECORDINGS: dict[ProductId, Path] = {
    _DAILY: _DAILY_RECORDING,
    _POINT_PRODUCTS[0]: _POINT_RECORDING,
    _POINT_PRODUCTS[1]: _POINT_RECORDING,
}
_RENDERED: dict[ProductId, RenderedWindow] = {
    _DAILY: RenderedWindow("2019-12-28", "2020-01-05"),
    _POINT_PRODUCTS[0]: RenderedWindow("2020-01-03", "2020-01-09"),
    _POINT_PRODUCTS[1]: RenderedWindow("2020-01-03", "2020-01-09"),
}
_FETCH_WINDOWS: dict[ProductId, tuple[datetime, datetime]] = {
    _DAILY: (datetime(2019, 12, 28), datetime(2020, 1, 4, 23, 59, 59, 999999)),
    _POINT_PRODUCTS[0]: (datetime(2020, 1, 3), datetime(2020, 1, 8, 23, 59, 59, 999999)),
    _POINT_PRODUCTS[1]: (datetime(2020, 1, 3), datetime(2020, 1, 8, 23, 59, 59, 999999)),
}
_CAPTURE_COMMANDS = (
    "uv run python -m rivretrieve._internal.record_observations --provider za_dws --station X3H001 "
    "--product discharge_daily_mean --start 2019-12-30 --end 2020-01-02 "
    "--out-dir tests/test_data --name za_dws_X3H001_Daily_2019-12-28_2020-01-05",
    "uv run python -m rivretrieve._internal.record_observations --provider za_dws --station X3H001 "
    "--product discharge_instantaneous --product stage_instantaneous --start 2020-01-05 --end 2020-01-06 "
    "--out-dir tests/test_data --name za_dws_X3H001_Point_2020-01-03_2020-01-09",
)

# Independently authored three-literal expectations: READING_COUNT, FIRST_WALL_CLOCK_TIME and
# LAST_WALL_CLOCK_TIME per product. ``None`` means the recording does not exist yet and the
# literals have not been authored; the test then fails rather than passing on absent evidence.
# Template for the independent author (replace each None; times are naive ISO strings):
#     _DAILY: {
#         READING_COUNT: 9,
#         FIRST_WALL_CLOCK_TIME: WallClockExpectation("2019-12-28T00:00:00", "unknown"),
#         LAST_WALL_CLOCK_TIME: WallClockExpectation("2020-01-04T00:00:00", "unknown"),
#     },
#     _POINT_PRODUCTS[0]: {
#         READING_COUNT: 123,
#         FIRST_WALL_CLOCK_TIME: WallClockExpectation("2020-01-03T00:00:00", "unknown"),
#         LAST_WALL_CLOCK_TIME: WallClockExpectation("2020-01-08T23:48:00", "unknown"),
#     },
_EXPECTATIONS: dict[ProductId, Mapping[str, object] | None] = {
    _DAILY: None,
    _POINT_PRODUCTS[0]: None,
    _POINT_PRODUCTS[1]: None,
}
_LITERAL_NAMES = (READING_COUNT, FIRST_WALL_CLOCK_TIME, LAST_WALL_CLOCK_TIME)
_ZONE_LABEL = WallClockExpectation("1970-01-01T00:00:00", "unknown").time_zone


def _require_evidence() -> None:
    missing = sorted({str(path) for path in _RECORDINGS.values() if not path.is_file()})
    if missing:
        commands = "\n".join(_CAPTURE_COMMANDS)
        pytest.fail(
            "za_dws boundary recordings are absent (the DWS host answers HTTP 403 from the porting "
            f"network): {missing}\nCapture them from an egress the source accepts with:\n{commands}"
        )
    pending = sorted(str(product) for product, expectation in _EXPECTATIONS.items() if expectation is None)
    if pending:
        pytest.fail(f"za_dws boundary literals await independent authorship for: {pending}")


def _run(product: ProductId, replay: ReplayTransport) -> pl.DataFrame:
    start, end = _FETCH_WINDOWS[product]
    fetched = _STAGES.fetch(
        (_STATION,),
        (product,),
        {product: (_RENDERED[product],)},
        _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
        _STAGES.config,
        replay,
    )
    assert fetched.issues == ()
    return pl.concat([_STAGES.parse(payload, _STAGES.config).value for payload in fetched.value])


def _probe(product: ProductId) -> LiveBoundaryProbe:
    expectation = _EXPECTATIONS[product]
    assert expectation is not None
    assert set(expectation) == set(_LITERAL_NAMES)
    return LiveBoundaryProbe(
        provider_id=_PROVIDER,
        product_id=product,
        recordings=(read_recording(_RECORDINGS[product]),),
        assertions=expectation,
        run=lambda replay: _run(product, replay),
    )


def test_every_south_africa_product_has_an_exact_live_replay_probe() -> None:
    _require_evidence()
    observations = run_manifest_boundary_probes(load_manifest((_PROVIDER,)), tuple(_probe(p) for p in _RECORDINGS))

    assert len(observations) == 3
    assert all(frame.get_column("time_zone").unique().to_list() == [_ZONE_LABEL] for frame in observations)
