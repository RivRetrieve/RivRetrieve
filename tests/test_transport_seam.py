"""Transport seam : EngineRequest × ProviderStages × Transport → assembled observations."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    ProductWindowDeclarations,
    RequestedWindow,
    StopConvention,
    WindowDeclaration,
    WindowEndpoint,
)
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.recordings import (
    RecordedRequest,
    RecordingEnvelope,
    ReplayTransport,
    UnmatchedRequestError,
)
from rivretrieve._internal.transport import HttpMethod

assert isinstance(declaration.observations, LiveStages)
usgs_nwis = declaration.observations.stages

_FIXTURE = Path(__file__).parent / "test_data" / "usgs_nwis_07374000_dv_00060_2023-01-01.json"
_PRODUCT = ProductId("discharge_daily_mean")


class _ExclusiveStopUsgs:
    config = usgs_nwis.config
    fetch = staticmethod(usgs_nwis.fetch)
    parse = staticmethod(usgs_nwis.parse)
    window_declarations = ProductWindowDeclarations(
        products={
            **usgs_nwis.window_declarations.products,
            _PRODUCT: WindowDeclaration(
                granularity=usgs_nwis.window_declarations.products[_PRODUCT].granularity,
                rendering=usgs_nwis.window_declarations.products[_PRODUCT].rendering,
                stop_convention=StopConvention.EXCLUSIVE,
                size=usgs_nwis.window_declarations.products[_PRODUCT].size,
            ),
        }
    )


def _request() -> ObservationRequest:
    return ObservationRequest(
        provider_id=ProviderId("usgs_nwis"),
        stations=("07374000",),
        products=(_PRODUCT,),
        window=RequestedWindow(
            start=WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
            end=WindowEndpoint.from_datetime(datetime(2023, 1, 1, 23, 59, 59, 999999)),
        ),
    )


def _recording() -> RecordingEnvelope:
    return RecordingEnvelope(
        request=RecordedRequest(
            method=HttpMethod.GET,
            url="https://waterservices.usgs.gov/nwis/dv/",
            parameters={
                "format": "json",
                "sites": "07374000",
                "startDT": "2022-12-30",
                "endDT": "2023-01-03",
                "parameterCd": "00060",
                "statCd": "00003",
            },
            ordinary_headers={"Accept": "application/json", "User-Agent": "RivRetrieve"},
        ),
        content=_FIXTURE.read_bytes(),
        status_code=200,
        retrieved_at=datetime(2026, 8, 19, tzinfo=UTC),
        content_type="application/json",
    )


def _provenance() -> ObservationProvenance:
    return ObservationProvenance(source="recording", provider_id=ProviderId("usgs_nwis"))


def test_stop_convention_flip_misses_exact_recording() -> None:
    request = _request()
    replay = ReplayTransport([_recording()])

    baseline = drive(request, usgs_nwis, provenance=_provenance(), transport=replay)
    assert baseline.canonical_rows.height == 1

    with pytest.raises(UnmatchedRequestError) as exc_info:
        drive(request, _ExclusiveStopUsgs, provenance=_provenance(), transport=replay)

    message = str(exc_info.value)
    assert '"endDT":"2023-01-04"' in message
    assert '"endDT":"2023-01-03"' not in message
