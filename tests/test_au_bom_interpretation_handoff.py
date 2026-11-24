"""au_bom adoption of the shared acquisition/parse interpretation handoff (#938, #949, #965)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import polars.testing as pl_testing
import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import (
    ObservationRequest,
    Payload,
    ProviderConfig,
    RequestedWindow,
    SourceAcquisition,
    WindowEndpoint,
)
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.au_bom import fetch as au_bom_fetch_mod
from rivretrieve._internal.providers.au_bom import parse as au_bom_parse_mod
from rivretrieve._internal.providers.au_bom.config import config, window_declarations
from rivretrieve._internal.transport import TransportResponse
from tests.test_internal_driver import _provenance


def _list_json(station: str, rows: list[tuple[str, str, str, str]]) -> bytes:
    header = ["ts_id", "ts_name", "parametertype_name", "ts_unitsymbol", "station_no"]
    return json.dumps(
        [header, *[[ts_id, ts_name, param, unit, station] for ts_id, ts_name, param, unit in rows]]
    ).encode("utf-8")


def _values_json(blocks: list[tuple[str, list[tuple[str, float | None, int | None, str | None]]]]) -> bytes:
    columns = "Timestamp,Value,Quality Code,Quality Code Name"
    return json.dumps(
        [
            {
                "ts_id": ts_id,
                "rows": str(len(rows)),
                "columns": columns,
                "data": [[label, value, code, name] for label, value, code, name in rows],
            }
            for ts_id, rows in blocks
        ]
    ).encode("utf-8")


def _assert_driver_results_identical(left: Any, right: Any) -> None:
    pl_testing.assert_frame_equal(left.canonical_rows, right.canonical_rows)
    assert left.source_series == right.source_series
    assert left.inventories == right.inventories
    assert left.outcomes == right.outcomes
    assert left.issues == right.issues
    assert left.provenance == right.provenance
    assert [(e.content, e.origin, e.authorship) for e in left.receipts.entries] == [
        (e.content, e.origin, e.authorship) for e in right.receipts.entries
    ]


@pytest.mark.parametrize("receipts", [ReceiptMode.OMIT, ReceiptMode.INCLUDE])
def test_au_bom_reuses_list_interpretation_and_matches_parse_baseline(
    monkeypatch: pytest.MonkeyPatch, receipts: ReceiptMode
) -> None:
    """A getTimeseriesList response is decoded exactly once (#949) and the driver's reused

    interpretation produces byte-for-byte identical results to the pre-handoff baseline
    (interpretations stripped, forcing a second, independent parse of the same payload).
    """
    station = "410730"
    list_bytes = _list_json(station, [("1598010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m")])
    values_bytes = _values_json([("1598010", [("2026-09-01T00:00:00.000+10:00", 0.745, 10, "quality-A")])])

    class _Transport:
        def send(self, request):
            params = dict(request.params or {})
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(
                    list_bytes, 200, datetime(2026, 11, 3, tzinfo=UTC), "application/json", request.url, params
                )
            return TransportResponse(
                values_bytes, 200, datetime(2026, 11, 3, tzinfo=UTC), "application/json", request.url, params
            )

    req = ObservationRequest(
        provider_id=ProviderId("au_bom"),
        stations=(station,),
        products=(ProductId("stage_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 9, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 9, 1, 23, 59, 59)),
        ),
    )

    decode_calls = 0
    real_resolve = au_bom_parse_mod.resolve_timeseries_list

    def counted_resolve(content: bytes, station_id: str):
        nonlocal decode_calls
        decode_calls += 1
        return real_resolve(content, station_id)

    monkeypatch.setattr(au_bom_parse_mod, "resolve_timeseries_list", counted_resolve)
    monkeypatch.setattr(au_bom_fetch_mod, "resolve_timeseries_list", counted_resolve)

    parse_coords: list[type[object]] = []
    real_parse = au_bom_parse_mod.parse

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        parse_coords.append(type(payload.source_coordinates.value))
        return real_parse(payload, cfg)

    captured: list[SourceAcquisition] = []

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()

    def _recording_fetch(*args: Any, **kwargs: Any) -> SourceAcquisition:
        acquisition = au_bom_fetch_mod.fetch(*args, **kwargs)
        assert isinstance(acquisition, SourceAcquisition)
        assert len(acquisition.interpretations) == 1
        captured.append(acquisition)
        return acquisition

    _Stages.fetch = staticmethod(_recording_fetch)
    _Stages.parse = staticmethod(spied_parse)

    result = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_Transport(), receipts=receipts)

    assert decode_calls == 1, f"getTimeseriesList was decoded {decode_calls} times, expected exactly 1"
    assert au_bom_fetch_mod.AuBomTimeseriesListCoordinates not in parse_coords, (
        "the driver re-parsed the list payload instead of reusing fetch.py's handoff"
    )

    class _BaselineStages:
        pass

    _BaselineStages.config = config()
    _BaselineStages.window_declarations = window_declarations()
    _BaselineStages.fetch = staticmethod(lambda *args, **kwargs: replace(captured[0], interpretations=()))
    _BaselineStages.parse = staticmethod(real_parse)

    baseline = driver_module.drive(req, _BaselineStages(), provenance=_provenance(req), receipts=receipts)
    _assert_driver_results_identical(result, baseline)


def test_au_bom_reuses_malformed_list_interpretation_and_matches_parse_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed getTimeseriesList response's FAILED-outcome interpretation is also handed off once."""
    station = "410730"

    class _Transport:
        def send(self, request):
            params = dict(request.params or {})
            return TransportResponse(
                b"not valid json {{{", 200, datetime(2026, 11, 3, tzinfo=UTC), "application/json", request.url, params
            )

    req = ObservationRequest(
        provider_id=ProviderId("au_bom"),
        stations=(station,),
        products=(ProductId("stage_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 9, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 9, 1, 23, 59, 59)),
        ),
    )

    real_parse = au_bom_parse_mod.parse
    parse_coords: list[type[object]] = []

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        parse_coords.append(type(payload.source_coordinates.value))
        return real_parse(payload, cfg)

    captured: list[SourceAcquisition] = []

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()

    def _recording_fetch(*args: Any, **kwargs: Any) -> SourceAcquisition:
        acquisition = au_bom_fetch_mod.fetch(*args, **kwargs)
        assert len(acquisition.interpretations) == 1
        captured.append(acquisition)
        return acquisition

    _Stages.fetch = staticmethod(_recording_fetch)
    _Stages.parse = staticmethod(spied_parse)

    result = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_Transport())

    assert au_bom_fetch_mod.AuBomTimeseriesListCoordinates not in parse_coords
    assert result.canonical_rows.height == 0
    assert any(issue.code == "source.unsupported_structure" for issue in result.issues)

    class _BaselineStages:
        pass

    _BaselineStages.config = config()
    _BaselineStages.window_declarations = window_declarations()
    _BaselineStages.fetch = staticmethod(lambda *args, **kwargs: replace(captured[0], interpretations=()))
    _BaselineStages.parse = staticmethod(real_parse)

    baseline = driver_module.drive(req, _BaselineStages(), provenance=_provenance(req))
    _assert_driver_results_identical(result, baseline)
