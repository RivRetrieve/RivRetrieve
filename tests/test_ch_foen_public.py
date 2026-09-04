from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_RECORDING = read_recording(Path(__file__).parent / "test_data" / "ch_foen_2135_rest_engine_2026-09-01.recording.json")


def test_public_selection_uses_anonymous_rest_and_returns_five_columns_with_raw_receipt(
    monkeypatch: pytest.MonkeyPatch,
):
    replay = ReplayTransport((_RECORDING,))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider="ch_foen", station="2135", product="discharge_reported")
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-02", receipts=True, on_issue="ignore")
    assert result.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert dict(result.data.group_by("product_id").len().iter_rows()) == {"discharge_reported": 244}
    assert result.data["time"].min() == datetime(2026, 9, 1)
    assert result.data["time"].max() == datetime(2026, 9, 2, 16, 30)
    assert len(result.receipts.entries) == 1
    assert result.receipts.entries[0].content == _RECORDING.content
    assert result.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    utc = rr.to_utc(result)
    assert set(utc.data["time_zone"]) == {"+00:00"}


def test_public_unknown_zone_refusal_is_atomic_and_identifies_swiss_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((_RECORDING,)))
    fetched = rr.fetch(
        rr.find(provider="ch_foen", station="2135", product="discharge_reported"),
        start="2026-09-01",
        end="2026-09-02",
        receipts=False,
        on_issue="ignore",
    )
    assert fetched.data["time_zone"].unique().to_list() == ["+00:00"]
    mutated_data = (
        fetched.data.with_row_index()
        .with_columns(
            pl.when(pl.col("index") == 0).then(pl.lit("unknown")).otherwise(pl.col("time_zone")).alias("time_zone")
        )
        .drop("index")
    )
    result = fetched.model_copy(update={"data": mutated_data})
    untouched = result.data.clone()
    conversion_calls: list[object] = []

    def fail_if_conversion_starts(*args: object) -> None:
        conversion_calls.append(args)
        raise AssertionError("per-row conversion ran before the unknown-zone refusal")

    monkeypatch.setattr("rivretrieve._internal.utc._convert_wall_clock", fail_if_conversion_starts)

    with pytest.raises(FatalContractError) as raised:
        rr.to_utc(result)

    assert str(raised.value) == (
        "Cannot convert 1 observation rows for provider 'ch_foen' to UTC because time_zone is 'unknown'"
    )
    assert conversion_calls == []
    pl_testing.assert_frame_equal(result.data, untouched, check_exact=True)


def test_public_receipts_false_omits_publisher_bytes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((_RECORDING,)))
    result = rr.fetch(
        rr.find(provider="ch_foen", station="2135", product="discharge_reported"),
        start="2026-09-01",
        end="2026-09-02",
        receipts=False,
        on_issue="ignore",
    )
    assert result.receipts.entries == ()
    assert result.provenance.endpoints == ("https://api.existenz.ch/apiv1/hydro/daterange",)
    assert result.provenance.retrieved_at == _RECORDING.retrieved_at
    assert len(result.provenance.calls_made) == 1
    assert result.provenance.calls_made[0]["request_parameters"] == dict(_RECORDING.request.parameters or {})
    assert result.provenance.calls_made[0]["query"] == {
        "status": "unknown",
        "reason": "unknown",
    }
