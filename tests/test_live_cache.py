"""live cache : RecordedSourceCalls × CacheMode × RequestedWindow → ObservationResult × StoreEffects.

Source bytes come only from committed exact-request recordings. Parse-output controls
exercise engine refresh and empty-answer behavior without claiming new source evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.assembly import _AssemblyResult
from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    Payload,
    ProviderConfig,
    RequestedWindow,
    Rows,
    WindowEndpoint,
    WithIssues,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptAuthorship, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.store import ObservationStoreRefusedError, StoreReader, StoreRoot
from rivretrieve._internal.transport import (
    Transport,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_DATA = Path(__file__).parent / "test_data"
_DAILY = _DATA / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
_INSTANT = _DATA / "usgs_nwis_09380000_iv_00060_2020-07-01.recording.json"
_PROVIDER = ProviderId("usgs_nwis")
_PRODUCT = ProductId("discharge_instantaneous")
assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages


class CountedReplay:
    def __init__(self, recording: Path) -> None:
        self.replay = ReplayTransport([recording])
        self.calls: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.calls.append(request)
        return self.replay.send(request)


class RefusedTransport:
    def send(self, request: TransportRequest) -> TransportResponse:
        raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)


class ParseOutputControl:
    config = _STAGES.config
    window_declarations = _STAGES.window_declarations
    fetch = staticmethod(_STAGES.fetch)

    def __init__(self, limit: int) -> None:
        self.limit = limit

    def parse(self, payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
        parsed = _STAGES.parse(payload, config)
        return WithIssues(
            parsed.value.filter(pl.col("time").dt.date() == datetime(2020, 7, 1).date()).head(self.limit), parsed.issues
        )


def _drive(
    store: Path,
    transport: Transport,
    *,
    start: datetime = datetime(2020, 7, 1),
    end: datetime = datetime(2020, 7, 1, 23, 59, 59, 999999),
    cache: Literal["bypass", "reuse", "refresh"] = "reuse",
    control: ParseOutputControl | None = None,
) -> _AssemblyResult:
    return drive(
        ObservationRequest(
            _PROVIDER,
            ("09380000",),
            (_PRODUCT,),
            RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
        ),
        _STAGES if control is None else control,
        provenance=ObservationProvenance(source="USGS", provider_id=_PROVIDER),
        transport=transport,
        cache=cache,
        store=StoreRoot(store),
        receipts=ReceiptMode.INCLUDE,
    )


def _bytes(store: Path) -> dict[str, bytes]:
    return {path.relative_to(store).as_posix(): path.read_bytes() for path in store.rglob("*") if path.is_file()}


def test_public_daily_repeat_is_local_bypass_untouched_and_daily_axis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = CountedReplay(_DAILY)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    selection = rr.pick(rr.find(provider="usgs_nwis", product="discharge_daily_mean"), station="07374000")
    first = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", receipts=True)
    assert len(transport.calls) == 1
    second = rr.fetch(selection, start="2023-01-01T12:00", end="2023-01-01T13:00", cache="reuse", receipts=True)
    assert len(transport.calls) == 1
    assert_frame_equal(first.data, second.data)
    assert second.provenance.calls_made == ()
    assert len(second.provenance.served_intervals) == 1
    assert second.receipts.entries[0].authorship is ReceiptAuthorship.STORE_EXCERPT
    assert first.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    status = rr.cache_status("usgs_nwis")
    assert status.bytes_on_disk > 0
    assert status.coverage[0].interval == RequestedInterval(
        datetime(2023, 1, 1), datetime(2023, 1, 1, 23, 59, 59, 999999)
    )
    disk = pl.read_parquet(next(status.store.rglob("*.parquet")))
    assert disk["value"][0] != first.data["value"][0]
    assert disk.schema["time"] == pl.Datetime("us")
    before = _bytes(status.store)
    bypass = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True)
    assert len(transport.calls) == 2
    assert_frame_equal(first.data, bypass.data)
    assert _bytes(status.store) == before
    assert bypass.provenance.served_intervals == ()
    assert all(entry.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD for entry in bypass.receipts.entries)
    removed = rr.clear_cache("usgs_nwis")
    assert removed.bytes_freed == status.bytes_on_disk
    assert not rr.cache_status("usgs_nwis").exists


def test_only_remainder_is_parsed_into_mixed_result_and_receipts(tmp_path: Path) -> None:
    transport = CountedReplay(_INSTANT)
    store = tmp_path / "store"
    first = _drive(store, transport, end=datetime(2020, 7, 1, 11, 59, 59, 999999))
    mixed = _drive(store, transport)
    assert len(transport.calls) == 2
    expected = _drive(store, transport, cache="bypass")
    assert_frame_equal(mixed.canonical_rows.sort("time"), expected.canonical_rows.sort("time"))
    assert mixed.provenance.served_intervals[0].interval.end == datetime(2020, 7, 1, 11, 59, 59, 999999)
    assert len(mixed.provenance.calls_made) == 1
    assert [entry.authorship for entry in mixed.receipts.entries] == [
        ReceiptAuthorship.STORE_EXCERPT,
        ReceiptAuthorship.PUBLISHER_PAYLOAD,
    ]
    assert mixed.receipts.entries[1].content == first.receipts.entries[0].content
    coverage = StoreReader().status(StoreRoot(store), _PROVIDER).coverage
    assert [item.interval.start for item in coverage] == [datetime(2020, 7, 1), datetime(2020, 7, 1, 12)]
    repeated = _drive(store, transport)
    assert len(transport.calls) == 3
    assert_frame_equal(repeated.canonical_rows.sort("time"), expected.canonical_rows.sort("time"))


def test_failed_remainder_returns_held_rows_and_preserves_store(tmp_path: Path) -> None:
    store = tmp_path / "store"
    held = _drive(store, CountedReplay(_INSTANT), end=datetime(2020, 7, 1, 11, 59, 59, 999999))
    before = _bytes(store)
    partial = _drive(store, RefusedTransport())
    assert_frame_equal(partial.canonical_rows, held.canonical_rows)
    assert len(partial.issues) == 1
    assert partial.issues[0].severity == "error"
    assert _bytes(store) == before


@pytest.mark.parametrize("remaining", [8, 0])
def test_refresh_replaces_with_fewer_parse_rows_and_empty_answers_are_covered(tmp_path: Path, remaining: int) -> None:
    store = tmp_path / "store"
    replay = CountedReplay(_INSTANT)
    first = _drive(store, replay, control=ParseOutputControl(10))
    assert first.canonical_rows.height == 10
    refreshed = _drive(store, replay, cache="refresh", control=ParseOutputControl(remaining))
    assert refreshed.canonical_rows.height == remaining
    held = _drive(store, RefusedTransport())
    assert_frame_equal(held.canonical_rows, refreshed.canonical_rows)
    assert held.issues == ()
    assert StoreReader().status(StoreRoot(store), _PROVIDER).coverage


def test_served_intervals_retain_separate_retrieval_instants(tmp_path: Path) -> None:
    from dataclasses import replace

    from rivretrieve._internal.store.accumulation import accumulate

    store = StoreRoot(tmp_path / "store")
    _drive(store, CountedReplay(_INSTANT), end=datetime(2020, 7, 1, 11, 59, 59, 999999))
    _drive(store, CountedReplay(_INSTANT))
    status = StoreReader().status(store, _PROVIDER)
    second = replace(status.coverage[1], retrieved_at=status.coverage[1].retrieved_at + timedelta(days=1))
    from rivretrieve._internal.store import StoreQuery

    rows = (
        StoreReader()
        .query(StoreQuery(store, _PROVIDER, ("09380000",), (_PRODUCT,), second.interval.start, second.interval.end))
        .rows
    )
    accumulate(store, _PROVIDER, rows, second)
    result = _drive(store, RefusedTransport())
    assert tuple(item.retrieved_at for item in result.provenance.served_intervals) == (
        status.coverage[0].retrieved_at,
        second.retrieved_at,
    )
    assert "freshness" not in result.provenance.model_dump_json()


def test_unknown_revision_refuses_before_transport(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _drive(store, CountedReplay(_INSTANT))
    path = store / "manifest.json"
    document = json.loads(path.read_text())
    document["format_version"] = 99
    path.write_text(json.dumps(document))
    replay = CountedReplay(_INSTANT)
    with pytest.raises(ObservationStoreRefusedError, match="unsupported format revision 99"):
        _drive(store, replay)
    assert replay.calls == []


def test_interrupted_publication_refuses_before_source_call(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _drive(store, CountedReplay(_INSTANT))
    store.rename(tmp_path / ".store.backup-interrupted")
    transport = CountedReplay(_INSTANT)
    with pytest.raises(ObservationStoreRefusedError, match="interrupted store publication"):
        _drive(store, transport)
    assert transport.calls == []
    assert not store.exists()


def test_failed_second_gap_does_not_publish_part_of_a_failed_series(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _drive(store, CountedReplay(_INSTANT), start=datetime(2020, 7, 1, 12), end=datetime(2020, 7, 1, 13, 59, 59, 999999))
    before = _bytes(store)

    class FailSecondGap(CountedReplay):
        def send(self, request: TransportRequest) -> TransportResponse:
            if self.calls:
                return RefusedTransport().send(request)
            return super().send(request)

    result = _drive(store, FailSecondGap(_INSTANT))
    assert result.canonical_rows.height > 8
    assert len(result.issues) == 1
    assert _bytes(store) == before


@pytest.mark.parametrize("defect", ["zone", "product"])
def test_invalid_parse_rows_even_in_padding_do_not_modify_store(tmp_path: Path, defect: str) -> None:
    from rivretrieve._internal.issues import FatalContractError

    class InvalidParseRows(ParseOutputControl):
        def parse(self, payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
            parsed = _STAGES.parse(payload, config)
            field, value = ("time_zone", "not a zone") if defect == "zone" else ("product_id", "undeclared")
            return WithIssues(
                parsed.value.with_columns(
                    pl.when(pl.col("time") < datetime(2020, 7, 1))
                    .then(pl.lit(value))
                    .otherwise(pl.col(field))
                    .alias(field)
                )
            )

    store = tmp_path / "store"
    with pytest.raises((ValueError, FatalContractError)):
        _drive(store, CountedReplay(_INSTANT), control=InvalidParseRows(10))
    assert not store.exists()


def test_successful_series_is_written_before_public_issue_policy_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rivretrieve._internal.issues import IssuePolicyError

    class OneSeriesFails(CountedReplay):
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.params is not None and request.params["sites"] == "09380000":
                return RefusedTransport().send(request)
            return super().send(request)

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: OneSeriesFails(_DAILY))
    selection = rr.pick(rr.find(provider="usgs_nwis", product="discharge_daily_mean"), station=["07374000", "09380000"])
    with pytest.raises(IssuePolicyError):
        rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", on_issue="raise")
    status = rr.cache_status("usgs_nwis")
    assert tuple(item.station_id for item in status.coverage) == ("07374000",)


def test_returned_parse_error_issue_preserves_rows_but_does_not_accumulate_coverage(tmp_path: Path) -> None:
    """Engine WithIssues contract, not a claim that this source returned the authored issue."""
    from rivretrieve._internal.issues import Issue

    class ParseIssueControl(ParseOutputControl):
        def parse(self, payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
            parsed = _STAGES.parse(payload, config)
            return WithIssues(
                parsed.value,
                (
                    *parsed.issues,
                    Issue(
                        severity="error",
                        code="contract_test.parse_error",
                        message="Authored stage issue for the engine WithIssues contract test",
                        provider_id=_PROVIDER,
                    ),
                ),
            )

    store = tmp_path / "store"
    transport = CountedReplay(_INSTANT)
    result = _drive(store, transport, control=ParseIssueControl(10))
    assert not result.canonical_rows.is_empty()
    assert len(transport.calls) == 1
    assert any(issue.code == "contract_test.parse_error" for issue in result.issues)
    assert not store.exists()
