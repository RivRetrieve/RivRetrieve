"""USGS boundary probe : recorded Arizona interaction → local-window observations."""

from collections.abc import Mapping
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
    run_manifest_boundary_probes,
)
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    RenderedWindow,
    RequestedWindow,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import LiveStages, load_manifest
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.recordings import ReplayTransport, read_recording

assert isinstance(declaration.observations, LiveStages)
usgs_nwis = declaration.observations.stages

_PROVIDER = ProviderId("usgs_nwis")
_DATA = Path(__file__).parent / "test_data"
_ARIZONA_PRODUCT = ProductId("discharge_instantaneous")
_ARIZONA_RECORDING = _DATA / "usgs_nwis_09380000_iv_00060_2020-07-01.recording.json"
_DECLARED_USGS = load_manifest((_PROVIDER,))

_NEW_RECORDINGS = {
    ProductId("discharge_daily_mean"): _DATA / "usgs_nwis_07374000_dv_00060_00003_2023-01-01_2023-01-03.recording.json",
    ProductId("stage_daily_mean"): _DATA / "usgs_nwis_07374000_dv_00065_00003_2023-01-01_2023-01-03.recording.json",
    ProductId("stage_daily_max"): _DATA / "usgs_nwis_07374000_dv_00065_00001_2023-01-01_2023-01-03.recording.json",
    ProductId("stage_daily_min"): _DATA / "usgs_nwis_07374000_dv_00065_00002_2023-01-01_2023-01-03.recording.json",
    ProductId("stage_instantaneous"): _DATA / "usgs_nwis_07374000_iv_00065_2023-01-01_2023-01-03.recording.json",
}
_DAILY_PRODUCTS = (
    ProductId("discharge_daily_mean"),
    ProductId("stage_daily_mean"),
    ProductId("stage_daily_max"),
    ProductId("stage_daily_min"),
)


def _run_arizona_probe(replay: ReplayTransport):
    request = ObservationRequest(
        provider_id=_PROVIDER,
        stations=("09380000",),
        products=(_ARIZONA_PRODUCT,),
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


def _run_current_recording(product_id: ProductId, replay: ReplayTransport) -> pl.DataFrame:
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 1, 3, 23, 59, 59, 999999)),
    )
    fetched = usgs_nwis.fetch(
        ("07374000",),
        (product_id,),
        MappingProxyType({product_id: (RenderedWindow("2023-01-01", "2023-01-03"),)}),
        fetch_window,
        usgs_nwis.config,
        replay,
    )
    assert fetched.issues == ()
    return pl.concat([usgs_nwis.parse(payload, usgs_nwis.config).rows for payload in fetched.value])


def _current_probe(product_id: ProductId, assertions: Mapping[str, object]) -> BoundaryProbe:
    return BoundaryProbe(
        provider_id=_PROVIDER,
        product_id=product_id,
        recordings=(read_recording(_NEW_RECORDINGS[product_id]),),
        assertions=assertions,
        run=lambda replay: _run_current_recording(product_id, replay),
    )


_DAILY_ASSERTIONS = {
    READING_COUNT: 3,
    FIRST_WALL_CLOCK_TIME: WallClockExpectation("2023-01-01T00:00:00", "unknown"),
    LAST_WALL_CLOCK_TIME: WallClockExpectation("2023-01-03T00:00:00", "unknown"),
}
_STAGE_IV_ASSERTIONS = {
    READING_COUNT: 287,
    FIRST_WALL_CLOCK_TIME: WallClockExpectation("2023-01-01T00:00:00", "-06:00"),
    LAST_WALL_CLOCK_TIME: WallClockExpectation("2023-01-03T23:45:00", "-06:00"),
}

_USGS_NWIS_PROBES = (
    *(_current_probe(product_id, _DAILY_ASSERTIONS) for product_id in _DAILY_PRODUCTS),
    BoundaryProbe(
        provider_id=_PROVIDER,
        product_id=_ARIZONA_PRODUCT,
        recordings=(read_recording(_ARIZONA_RECORDING),),
        assertions={
            READING_COUNT: 93,
            FIRST_WALL_CLOCK_TIME: WallClockExpectation("2020-07-01T00:00:00", "-07:00"),
            LAST_WALL_CLOCK_TIME: WallClockExpectation("2020-07-01T23:00:00", "-07:00"),
        },
        run=_run_arizona_probe,
    ),
    _current_probe(ProductId("stage_instantaneous"), _STAGE_IV_ASSERTIONS),
)


def test_every_declared_usgs_product_has_exact_recorded_boundary_evidence() -> None:
    observations = run_manifest_boundary_probes(_DECLARED_USGS, _USGS_NWIS_PROBES)

    assert len(observations) == 6


def test_arizona_last_local_hour_remains_source_derived() -> None:
    observations = run_manifest_boundary_probes(_DECLARED_USGS, _USGS_NWIS_PROBES)
    discharge_instantaneous = observations[1]

    assert discharge_instantaneous.sort("time").tail(1).select("time", "time_zone").row(0) == (
        datetime(2020, 7, 1, 23),
        "-07:00",
    )
