"""dk_vanda fetch/parse wired through the shared engine's window planning,
unit conversion and assembly (`driver.drive`), independent of
`BUILTIN_PROVIDER_IDS` registration.

`dk_vanda` is deliberately not yet in `BUILTIN_PROVIDER_IDS` (its catalogue has
never been published: `source.provider.terms`/`source.provider.attribution`
remain unestablished, see `declaration.py` and
research/dk-vanda-source-access.md in the evidence repository). `driver.drive`
itself never looks up the provider manifest -- it only requires a
`ProviderStages`-shaped object (`config`, `window_declarations`, `fetch`,
`parse`), exactly like `test_internal_driver.py`'s own `provider_id=
"throwaway"` stub providers. This module builds that object from dk_vanda's
real, already-implemented `config()`/`window_declarations()`/`fetch`/`parse`
(Effort #799, step 4) -- the same shape `lt_lhmt.__init__.py`'s `_Stages`
class wires into `LiveStages` -- and drives it through `driver.drive` with a
synthetic transport, so the shared window-planning, unit-conversion and
clipping/assembly machinery the real `LiveStages` registration would use is
exercised today, without a packaged catalogue and without touching
`provider_manifest.BUILTIN_PROVIDER_IDS`.
"""

import json
from datetime import UTC, datetime

import pytest

from rivretrieve._internal import driver as driver_module
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.dk_vanda.config import config, window_declarations
from rivretrieve._internal.providers.dk_vanda.fetch import fetch
from rivretrieve._internal.providers.dk_vanda.parse import parse
from rivretrieve._internal.transport import TransportResponse


class _Stages:
    """The exact `ProviderStages` shape a future `LiveStages(stages=_Stages)` would wire,
    built directly from step 4's real dk_vanda modules."""

    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


class _UrlRoutedTransport:
    """Return a canned body keyed by request URL, so callers need not assume
    `drive`'s per-product fetch call order."""

    def __init__(self, bodies_by_url_suffix: dict[str, bytes]) -> None:
        self._bodies = bodies_by_url_suffix
        self.requests: list[object] = []

    def send(self, request: object) -> TransportResponse:
        self.requests.append(request)
        for suffix, body in self._bodies.items():
            if request.url.endswith(suffix):  # type: ignore[attr-defined]
                return TransportResponse(
                    content=body,
                    status_code=200,
                    retrieved_at=datetime(2026, 11, 13, tzinfo=UTC),
                    content_type="application/json",
                    url=request.url,  # type: ignore[attr-defined]
                    request_parameters=request.params,  # type: ignore[attr-defined]
                )
        raise AssertionError(f"Unexpected request URL in test transport: {request.url}")  # type: ignore[attr-defined]


def _result_row(sc: int, measurement_date_time: str, result: float | None, *, corrected: float | None = None) -> dict:
    return {
        "measurementPointNumber": 1,
        "parameterSc": 1233,
        "parameter": "x",
        "examinationTypeSc": sc,
        "examinationType": "x",
        "measurementDateTime": measurement_date_time,
        "depthM": None,
        "result": result,
        "resultElevationCorrected": corrected,
        "unitSc": 19,
        "unit": "x",
        "reasonSc": None,
        "reason": None,
    }


def _envelope(station: str, rows: list[dict]) -> bytes:
    return json.dumps([{"stationId": station, "operatorStationId": "", "results": rows}]).encode()


def _request(station: str, product: str, start: datetime, end: datetime) -> ObservationRequest:
    return ObservationRequest(
        provider_id=ProviderId("dk_vanda"),
        stations=(station,),
        products=(ProductId(product),),
        window=RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
    )


def _provenance() -> ObservationProvenance:
    return ObservationProvenance(source="test", provider_id=ProviderId("dk_vanda"), request={})


def _drive(request: ObservationRequest, transport: _UrlRoutedTransport):
    return driver_module.drive(
        request, _Stages(), provenance=_provenance(), transport=transport, receipts=ReceiptMode.OMIT
    )


def test_discharge_converts_l_s_to_m3_s_through_shared_engine():
    """Issue #800's l/s -> m3/s discharge conversion, exercised through plan_windows
    -> fetch -> parse -> convert -> assemble, not just unit-tested in isolation."""
    body = _envelope("19000467", [_result_row(27, "2020-01-01T00:00:00.00Z", 123.4)])
    transport = _UrlRoutedTransport({"water-flows": body})
    request = _request("19000467", "discharge", datetime(2020, 1, 1), datetime(2020, 1, 1, 23, 59, 59))

    result = _drive(request, transport)

    rows = result.canonical_rows.to_dicts()
    assert len(rows) == 1
    assert rows[0]["quantity"] == "discharge"
    assert rows[0]["source_unit"] == "l/s"
    assert rows[0]["unit"] == "m3/s"
    assert rows[0]["value"] == pytest.approx(0.1234)


def test_stage_converts_cm_to_m_through_shared_engine_for_both_fields():
    """Issue #800's cm -> m stage conversion, for both admitted stage fields
    (raw `result` and `resultElevationCorrected`), through the full pipeline."""
    body = _envelope("19000468", [_result_row(25, "2020-01-01T00:00:00.00Z", 24.3, corrected=82.0)])
    transport = _UrlRoutedTransport({"water-levels": body})
    request = _request("19000468", "stage", datetime(2020, 1, 1), datetime(2020, 1, 1, 23, 59, 59))

    result = _drive(request, transport)

    rows = {row["quantity"] + ":" + str(round(row["value"], 6)) for row in result.canonical_rows.to_dicts()}
    assert len(result.canonical_rows) == 2
    assert all(row["source_unit"] == "cm" and row["unit"] == "m" for row in result.canonical_rows.to_dicts())
    assert rows == {"stage:0.243", "stage:0.82"}


def test_temperature_quantity_is_admitted_not_a_fatal_contract_error():
    """Regression guard: `series.py`'s temperature `SeriesMapping` quantity must be
    the literal "temperature" admission-table key (`source_series.py`'s
    `_UNIT_DIMENSIONS`/`_TARGET_UNITS`), matching fr_hubeau/cz_chmi/no_nve/ch_foen's
    own water-temperature mappings. A prior "water_temperature" value there made
    `admission()` reject every dk_vanda temperature fact as dimensionally
    incompatible, which made `conversion.convert` raise `FatalContractError` for
    any live temperature retrieval -- reproduced end-to-end through this exact
    `driver.drive` call before the fix. Temperature itself needs no unit
    conversion (degC in, degC out); this only guards that admission succeeds.
    """
    body = _envelope("70000277", [_result_row(29, "2020-01-01T00:00:00.00Z", 5.2)])
    transport = _UrlRoutedTransport({"measurements/results/current": body})
    request = _request("70000277", "temperature", datetime(2020, 1, 1), datetime(2020, 1, 1, 23, 59, 59))

    result = _drive(request, transport)

    rows = result.canonical_rows.to_dicts()
    assert len(rows) == 1
    assert rows[0]["quantity"] == "temperature"
    assert rows[0]["source_unit"] == "degC"
    assert rows[0]["unit"] == "degC"
    assert rows[0]["value"] == pytest.approx(5.2)


def test_requested_window_clips_padded_fetch_window_rows_through_shared_engine():
    """The shared engine always pads the fetch window beyond the requested window
    (`driver._FETCH_WINDOW_PADDING`) before rendering it for the source request
    (architecture.md's "window arithmetic" / "clipping"). A provider fetches the
    wider padded window -- VandA has no narrower option (fetch.py's module
    docstring) -- but `convert` must still clip assembled rows back to exactly
    the requested window. This exercises that for dk_vanda specifically, not just
    the shared `conversion.convert` unit tests.
    """
    station = "19000467"
    rows = [
        _result_row(27, "2020-01-03T00:00:00.00Z", 1.0),  # before the requested window: padded-in, must be clipped
        _result_row(27, "2020-01-05T12:00:00.00Z", 2.0),  # inside the requested window: must be kept
        _result_row(27, "2020-01-07T00:00:00.00Z", 3.0),  # after the requested window: padded-in, must be clipped
    ]
    body = _envelope(station, rows)
    transport = _UrlRoutedTransport({"water-flows": body})
    request = _request(station, "discharge", datetime(2020, 1, 5, 0, 0), datetime(2020, 1, 5, 23, 59, 59))

    result = _drive(request, transport)

    kept = result.canonical_rows.to_dicts()
    assert len(kept) == 1
    assert kept[0]["value"] == pytest.approx(0.002)
    assert kept[0]["time"] == datetime(2020, 1, 5, 12, 0, 0)
    # The rendered VandA request window (plan_windows via fetch.py) covers the
    # padded fetch window, confirming the wider request actually happened and
    # clipping -- not a narrower source request -- is what excluded the other rows.
    assert len(transport.requests) == 1
    params = dict(transport.requests[0].params)
    assert params["from"] < "2020-01-05T00:00:00Z"
    assert params["to"] > "2020-01-05T23:59:59Z"
