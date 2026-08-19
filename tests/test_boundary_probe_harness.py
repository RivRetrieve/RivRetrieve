"""Boundary probes are source-backed, small, and complete for every ported product."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    BoundaryProbe,
    BoundaryProbeContractError,
    BoundaryProbeHarness,
    WallClockExpectation,
)
from rivretrieve._internal.discovery import EmptySelectionError
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.transport import HttpMethod, TransportRequest

_PROVIDER = ProviderId("provider")
_PRODUCT = ProductId("flow_instantaneous")
_ASSERTIONS = {
    READING_COUNT: 2,
    FIRST_WALL_CLOCK_TIME: WallClockExpectation("2026-01-01T23:00:00", "+01:00"),
    LAST_WALL_CLOCK_TIME: WallClockExpectation("2026-01-02T00:00:00", "+01:00"),
}


def _recording() -> RecordingEnvelope:
    return RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            "https://source.test/observations",
            {"start": "2026-01-01", "end": "2026-01-02"},
        ),
        content=b"recorded source bytes",
        status_code=200,
        retrieved_at=datetime(2026, 1, 3, 4, 5, tzinfo=UTC),
        content_type="application/json",
    )


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1, 23), datetime(2026, 1, 2)],
            "time_zone": ["+01:00", "+01:00"],
            "value": [10.0, 11.0],
        }
    )


def test_invented_payload_cannot_ground_probe_and_runner_does_not_run() -> None:
    unknown = UnknownOriginFact()
    invented_payload = Payload(
        source_coordinates=SourceCoordinates("flow"),
        station_products=(("station", _PRODUCT),),
        fetch_window=_make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 1, 2)),
        ),
        content=b"invented",
        origin=SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown),
    )
    ran = False

    def run_probe(_replay: object) -> pl.DataFrame:
        nonlocal ran
        ran = True
        return _frame()

    probe = BoundaryProbe(
        _PROVIDER,
        _PRODUCT,
        (cast("RecordingEnvelope", invented_payload),),
        _ASSERTIONS,
        run_probe,
    )
    harness = BoundaryProbeHarness(((_PROVIDER, _PRODUCT),))

    with pytest.raises(
        BoundaryProbeContractError,
        match="no RecordingEnvelope carrying a recorded request and retrieval instant",
    ):
        harness.register(probe)

    assert ran is False


def test_oversized_probe_is_refused_naming_extra_assertion_without_running() -> None:
    ran = False

    def run_probe(_replay: object) -> pl.DataFrame:
        nonlocal ran
        ran = True
        return _frame()

    probe = BoundaryProbe(
        _PROVIDER,
        _PRODUCT,
        (_recording(),),
        {**_ASSERTIONS, "first_value": 10.0},
        run_probe,
    )
    harness = BoundaryProbeHarness(((_PROVIDER, _PRODUCT),))

    with pytest.raises(BoundaryProbeContractError, match="extra assertion.*first_value"):
        harness.register(probe)

    assert ran is False


def test_unprobed_provider_product_is_refused_by_name_without_running_other_probe() -> None:
    ran = False

    def run_probe(_replay: object) -> pl.DataFrame:
        nonlocal ran
        ran = True
        return _frame()

    harness = BoundaryProbeHarness(
        (
            (_PROVIDER, _PRODUCT),
            (ProviderId("unprobed_provider"), ProductId("unprobed_product")),
        )
    )
    harness.register(BoundaryProbe(_PROVIDER, _PRODUCT, (_recording(),), _ASSERTIONS, run_probe))

    with pytest.raises(
        BoundaryProbeContractError,
        match="unprobed_provider/unprobed_product",
    ):
        harness.run()

    assert ran is False


def test_registered_probe_replays_and_checks_the_three_literals() -> None:
    def run_probe(replay: object) -> pl.DataFrame:
        # The runner resolves the recorded interaction through replay.
        assert isinstance(replay, ReplayTransport)
        replay.send(
            TransportRequest(
                HttpMethod.GET,
                "https://source.test/observations",
                params={"start": "2026-01-01", "end": "2026-01-02"},
            )
        )
        return _frame()

    harness = BoundaryProbeHarness(((_PROVIDER, _PRODUCT),))
    harness.register(BoundaryProbe(_PROVIDER, _PRODUCT, (_recording(),), _ASSERTIONS, run_probe))

    (result,) = harness.run()

    assert result.equals(_frame())


def test_ba_fhmzbih_daily_mean_absent_and_corrupting_request_refused_by_name() -> None:
    product_id = "discharge_daily_mean"
    assert product_id not in rr.products("ba_fhmzbih")
    selection = rr.find(
        provider="ba_fhmzbih",
        station="4510",
        product=product_id,
    )

    with pytest.raises(EmptySelectionError, match="discharge_daily_mean") as exc_info:
        rr.fetch(selection, start="2025-03-23", end="2025-03-26")

    assert exc_info.value.reason.product_ids == (product_id,)
    assert exc_info.value.reason.published_products == (
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    )


def test_probe_that_does_not_replay_its_recording_is_refused() -> None:
    def run_probe(_replay: object) -> pl.DataFrame:
        return _frame()

    harness = BoundaryProbeHarness(((_PROVIDER, _PRODUCT),))
    harness.register(BoundaryProbe(_PROVIDER, _PRODUCT, (_recording(),), _ASSERTIONS, run_probe))

    with pytest.raises(
        BoundaryProbeContractError,
        match="did not replay recorded request.*source.test/observations",
    ):
        harness.run()
