"""USGS boundary probe : recorded Arizona interaction → local-window observations."""

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
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.recordings import ReplayTransport, read_recording

assert isinstance(declaration.observations, LiveStages)
usgs_nwis = declaration.observations.stages

_PROVIDER = ProviderId("usgs_nwis")
_PRODUCT = ProductId("discharge_instantaneous")
_RECORDING = Path(__file__).parent / "test_data" / "usgs_nwis_09380000_iv_00060_2020-07-01.recording.json"
_PORTED_PROVIDER_PRODUCTS = ((_PROVIDER, _PRODUCT),)


def _run_arizona_probe(replay: ReplayTransport):
    request = ObservationRequest(
        provider_id=_PROVIDER,
        stations=("09380000",),
        products=(_PRODUCT,),
        window=RequestedWindow(
            start=WindowEndpoint.from_datetime(datetime(2020, 7, 1)),
            end=WindowEndpoint.from_datetime(datetime(2020, 7, 1, 23)),
        ),
    )
    result = drive(
        request,
        usgs_nwis,
        provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
        transport=replay,
    )
    return result.canonical_rows


_USGS_NWIS_PROBES = (
    BoundaryProbe(
        provider_id=_PROVIDER,
        product_id=_PRODUCT,
        recordings=(read_recording(_RECORDING),),
        assertions={
            READING_COUNT: 93,
            FIRST_WALL_CLOCK_TIME: WallClockExpectation("2020-07-01T00:00:00", "-07:00"),
            LAST_WALL_CLOCK_TIME: WallClockExpectation("2020-07-01T23:00:00", "-07:00"),
        },
        run=_run_arizona_probe,
    ),
)


def test_arizona_last_local_hour() -> None:
    (observations,) = run_boundary_probes(_PORTED_PROVIDER_PRODUCTS, _USGS_NWIS_PROBES)

    assert observations.sort("time").tail(1).select("time", "time_zone").row(0) == (
        datetime(2020, 7, 1, 23),
        "-07:00",
    )
