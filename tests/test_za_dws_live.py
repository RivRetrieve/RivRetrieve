"""South Africa live adapter proofs : exact recordings → driver and public results.

These tests replay the recordings named in ``tests/test_za_dws_boundary_probe.py`` and fail
loudly while those files are absent; they never skip.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.za_dws.declaration import declaration
from rivretrieve._internal.recordings import RecordingEnvelope, ReplayTransport, read_recording
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_za_dws_boundary_probe import _CAPTURE_COMMANDS, _DAILY_RECORDING, _POINT_RECORDING

_PROVIDER = ProviderId("za_dws")
_STATION = "X3H001"
_DAILY = ProductId("discharge_daily_mean")
_POINT_PRODUCTS = (ProductId("discharge_instantaneous"), ProductId("stage_instantaneous"))
_POINT_WINDOW = ("2020-01-05", "2020-01-06")
_DAILY_WINDOW = ("2019-12-30", "2020-01-02")

assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages


class _CountingReplay(ReplayTransport):
    def __init__(self, recordings: tuple[RecordingEnvelope, ...]) -> None:
        super().__init__(recordings)
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        response = super().send(request)
        self.requests.append(request)
        return response


def _recording(path: Path) -> RecordingEnvelope:
    if not path.is_file():
        commands = "\n".join(_CAPTURE_COMMANDS)
        pytest.fail(f"za_dws recording is absent: {path}\nCapture it with:\n{commands}")
    return read_recording(path)


def _window(start: str, end: str) -> RequestedWindow:
    return RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        end=WindowEndpoint.from_datetime(datetime.fromisoformat(end).replace(hour=23, minute=59, second=59)),
    )


def _drive(recording: RecordingEnvelope, products: tuple[ProductId, ...], start: str, end: str):
    replay = _CountingReplay((recording,))
    result = drive(
        ObservationRequest(provider_id=_PROVIDER, stations=(_STATION,), products=products, window=_window(start, end)),
        _STAGES,
        provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
        receipts=ReceiptMode.INCLUDE,
        transport=replay,
    )
    return replay, result


def test_one_point_response_feeds_both_instantaneous_products_with_one_receipt() -> None:
    recording = _recording(_POINT_RECORDING)
    replay, result = _drive(recording, _POINT_PRODUCTS, *_POINT_WINDOW)

    assert len(replay.requests) == 1
    assert len(result.receipts.entries) == 1
    assert result.receipts.entries[0].content == recording.content
    assert result.receipts.entries[0].origin.retrieved_at == recording.retrieved_at
    rows = result.canonical_rows
    assert set(rows["product_id"]) == set(_POINT_PRODUCTS)
    assert rows["time_zone"].unique().to_list() == ["unknown"]
    assert rows["time"].min() >= datetime(2020, 1, 5)
    assert rows["time"].max() <= datetime(2020, 1, 6, 23, 59, 59)
    assert rows.group_by("product_id").len()["len"].n_unique() == 1
    assert result.provenance.calls_made and len(result.provenance.calls_made) == 1
    assert result.provenance.endpoints == (recording.request.url,)
    assert result.provenance.retrieved_at == recording.retrieved_at


def test_daily_closed_window_survives_the_year_edge() -> None:
    recording = _recording(_DAILY_RECORDING)
    replay, result = _drive(recording, (_DAILY,), *_DAILY_WINDOW)

    assert len(replay.requests) == 1
    assert dict(replay.requests[0].params or {}) == dict(recording.request.parameters or {})
    rows = result.canonical_rows
    assert set(rows["product_id"]) <= {_DAILY}
    assert rows["time_zone"].unique().to_list() == ["unknown"]
    assert all(datetime(2019, 12, 30) <= value <= datetime(2020, 1, 2) for value in rows["time"])
    assert all(value.time() == datetime.min.time() for value in rows["time"])
    assert result.receipts.entries[0].content == recording.content


@pytest.mark.parametrize(
    ("product", "recording_path", "start", "end"),
    [
        (_POINT_PRODUCTS[0], _POINT_RECORDING, *_POINT_WINDOW),
        (_POINT_PRODUCTS[1], _POINT_RECORDING, *_POINT_WINDOW),
        (_DAILY, _DAILY_RECORDING, *_DAILY_WINDOW),
    ],
)
def test_public_fetch_routes_south_africa_through_the_engine(
    monkeypatch: pytest.MonkeyPatch, product: ProductId, recording_path: Path, start: str, end: str
) -> None:
    recording = _recording(recording_path)
    replay = _CountingReplay((recording,))
    monkeypatch.setattr(driver_module, "HttpClient", lambda: replay)

    selection = rr.find(provider="za_dws", station=_STATION, product=product)
    result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="ignore")

    assert result.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert set(result.data["product_id"]) <= {product}
    assert len(replay.requests) == 1
    assert len(result.receipts.entries) == 1
    assert result.receipts.entries[0].content == recording.content
    assert result.provenance.provider_id == "za_dws"
