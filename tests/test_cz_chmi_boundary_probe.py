"""CHMI boundary probes : recorded annual interactions → five canonical products."""

from datetime import datetime
from pathlib import Path

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    BoundaryProbe,
    WallClockExpectation,
    run_boundary_probes,
)
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.cz_chmi.declaration import declaration
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.recordings import ReplayTransport, read_recording

assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages
_PROVIDER = ProviderId("cz_chmi")
_STATION = "0-203-1-000400"
_DATA = Path(__file__).parent / "test_data"
_DQ = read_recording(_DATA / "cz_chmi_0-203-1-000400_DQ_2023.recording.json")
_HQ = read_recording(_DATA / "cz_chmi_0-203-1-000400_HQ_2023.recording.json")
_PRODUCTS = (
    (ProductId("stage_daily_mean"), _DQ, 2, "2023-06-02T00:00:00"),
    (ProductId("discharge_daily_mean"), _DQ, 2, "2023-06-02T00:00:00"),
    (ProductId("water_temperature_daily_mean"), _DQ, 2, "2023-06-02T00:00:00"),
    (ProductId("stage_hourly_mean"), _HQ, 48, "2023-06-02T23:00:00"),
    (ProductId("discharge_hourly_mean"), _HQ, 48, "2023-06-02T23:00:00"),
)


def _runner(product: ProductId):
    def run(replay: ReplayTransport):
        request = ObservationRequest(
            provider_id=_PROVIDER,
            stations=(_STATION,),
            products=(product,),
            window=RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2023, 6, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23)),
            ),
        )
        return drive(
            request,
            _STAGES,
            provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
            transport=replay,
        ).canonical_rows

    return run


def test_all_five_products_have_recorded_live_boundary_proofs() -> None:
    keys = tuple((_PROVIDER, product) for product, _, _, _ in _PRODUCTS)
    probes = tuple(
        BoundaryProbe(
            provider_id=_PROVIDER,
            product_id=product,
            recordings=(recording,),
            assertions={
                READING_COUNT: count,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation("2023-06-01T00:00:00", "+00:00"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation(last, "+00:00"),
            },
            run=_runner(product),
        )
        for product, recording, count, last in _PRODUCTS
    )
    results = run_boundary_probes(keys, probes)
    assert [frame.height for frame in results] == [2, 48, 2, 48, 2]
