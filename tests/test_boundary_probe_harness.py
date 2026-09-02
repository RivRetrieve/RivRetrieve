"""Boundary probes are source-backed, small, and complete for every ported product."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
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
    StoreBoundaryProbe,
    WallClockExpectation,
    manifest_boundary_obligations,
    run_manifest_boundary_probes,
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
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers.registration import load_manifest
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.store import StoreQuery, StoreRoot
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
        content=b'{"values":[]}',
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
        station="4024",
        product=product_id,
    )

    with pytest.raises(EmptySelectionError, match="discharge_daily_mean") as exc_info:
        rr.fetch(selection, start="2025-03-23", end="2025-03-26")

    assert exc_info.value.reason.product_ids == (product_id,)
    assert exc_info.value.reason.published_products == ()


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


def test_manifest_declarations_define_every_observation_product_obligation() -> None:
    obligations = manifest_boundary_obligations(load_manifest(BUILTIN_PROVIDER_IDS))

    assert obligations == (
        (ProviderId("ca_eccc"), ProductId("discharge_daily_mean")),
        (ProviderId("ca_eccc"), ProductId("stage_daily_mean")),
        (ProviderId("ch_foen"), ProductId("discharge_reported")),
        (ProviderId("ch_foen"), ProductId("stage_reported")),
        (ProviderId("ch_foen"), ProductId("water_temperature_reported")),
        (ProviderId("cz_chmi"), ProductId("discharge_daily_mean")),
        (ProviderId("cz_chmi"), ProductId("discharge_hourly_mean")),
        (ProviderId("cz_chmi"), ProductId("stage_daily_mean")),
        (ProviderId("cz_chmi"), ProductId("stage_hourly_mean")),
        (ProviderId("cz_chmi"), ProductId("water_temperature_daily_mean")),
        (ProviderId("jp_mlit"), ProductId("discharge_daily")),
        (ProviderId("jp_mlit"), ProductId("discharge_hourly")),
        (ProviderId("jp_mlit"), ProductId("stage_daily")),
        (ProviderId("jp_mlit"), ProductId("stage_hourly")),
        (ProviderId("lt_lhmt"), ProductId("discharge_daily_mean")),
        (ProviderId("lt_lhmt"), ProductId("stage_daily_mean")),
        (ProviderId("pl_imgw"), ProductId("discharge_daily_mean")),
        (ProviderId("pl_imgw"), ProductId("stage_daily_mean")),
        (ProviderId("pl_imgw"), ProductId("water_temperature_daily_mean")),
        (ProviderId("th_thaiwater"), ProductId("discharge_reported")),
        (ProviderId("th_thaiwater"), ProductId("stage_reported")),
        (ProviderId("usgs_nwis"), ProductId("discharge_daily_mean")),
        (ProviderId("usgs_nwis"), ProductId("discharge_instantaneous")),
        (ProviderId("usgs_nwis"), ProductId("stage_daily_max")),
        (ProviderId("usgs_nwis"), ProductId("stage_daily_mean")),
        (ProviderId("usgs_nwis"), ProductId("stage_daily_min")),
        (ProviderId("usgs_nwis"), ProductId("stage_instantaneous")),
    )


def test_store_boundary_probe_reads_validated_store_at_declared_query() -> None:
    store = StoreRoot(Path(__file__).parent / "test_data" / "observation_store_conformance" / "valid_future_austria")
    provider_id = ProviderId("fixture_bulk")
    product_id = ProductId("level")
    query = StoreQuery(
        store=store,
        provider_id=provider_id,
        stations=("at-001",),
        products=(product_id,),
        start=datetime(2024, 1, 2, 7, 30),
        end=datetime(2024, 1, 2, 7, 30),
    )
    harness = BoundaryProbeHarness(((provider_id, product_id),))
    harness.register(
        StoreBoundaryProbe(
            provider_id=provider_id,
            product_id=product_id,
            query=query,
            assertions={
                READING_COUNT: 1,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation("2024-01-02T07:30:00", "Europe/Vienna"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation("2024-01-02T07:30:00", "Europe/Vienna"),
            },
        )
    )

    (result,) = harness.run()

    assert result.select("station_id", "product_id").row(0) == ("at-001", "level")


def test_store_probe_query_must_match_registered_provider_product() -> None:
    query = StoreQuery(
        store=StoreRoot(Path("unused")),
        provider_id=ProviderId("different"),
        stations=("station",),
        products=(_PRODUCT,),
        start=datetime(2026, 1, 1),
        end=datetime(2026, 1, 2),
    )
    probe = StoreBoundaryProbe(_PROVIDER, _PRODUCT, query, _ASSERTIONS)

    with pytest.raises(BoundaryProbeContractError, match="query provider different"):
        BoundaryProbeHarness(((_PROVIDER, _PRODUCT),)).register(probe)


def test_manifest_probe_run_refuses_missing_declared_products_by_name() -> None:
    declared = load_manifest(BUILTIN_PROVIDER_IDS)

    with pytest.raises(BoundaryProbeContractError) as exc_info:
        run_manifest_boundary_probes(declared, ())

    message = str(exc_info.value)
    assert "ca_eccc/discharge_daily_mean" in message
    assert "pl_imgw/water_temperature_daily_mean" in message
    assert "usgs_nwis/stage_instantaneous" in message


def test_manifest_obligation_refuses_wrong_evidence_kind_before_execution() -> None:
    provider_id = ProviderId("usgs_nwis")
    product_id = ProductId("discharge_instantaneous")
    store_probe = StoreBoundaryProbe(
        provider_id,
        product_id,
        StoreQuery(
            store=StoreRoot(Path("must-not-be-read")),
            provider_id=provider_id,
            stations=("09380000",),
            products=(product_id,),
            start=datetime(2020, 7, 1),
            end=datetime(2020, 7, 1, 23),
        ),
        _ASSERTIONS,
    )

    with pytest.raises(BoundaryProbeContractError, match="LiveStages.*requires ReplayTransport evidence"):
        run_manifest_boundary_probes(load_manifest(BUILTIN_PROVIDER_IDS), (store_probe,))


def test_manifest_bulk_obligation_refuses_live_replay_evidence() -> None:
    probe = BoundaryProbe(
        ProviderId("ca_eccc"),
        ProductId("discharge_daily_mean"),
        (_recording(),),
        _ASSERTIONS,
        lambda _replay: _frame(),
    )

    with pytest.raises(BoundaryProbeContractError, match="BulkStore.*requires validated-store evidence"):
        run_manifest_boundary_probes(load_manifest(BUILTIN_PROVIDER_IDS), (probe,))
