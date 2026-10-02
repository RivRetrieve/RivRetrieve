"""Monthly partition bounds and retained source failure contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rivretrieve._internal import engine, window_planning
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceResponseMeaning,
    attempt_series_request,
)
from rivretrieve._internal.source_series import PhysicalFacts, SeriesWindow, SourceIdentity, SourceSeries
from rivretrieve._internal.time_axis import TimeAxis
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)


def _fetch(start: str, end: str) -> engine.FetchWindow:
    return engine._make_fetch_window(
        engine.WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        engine.WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
    )


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2023-12-30", "2024-01-02", (("2023-12-01", "2023-12-31"), ("2024-01-01", "2024-01-31"))),
        ("2024-02-28", "2024-03-01", (("2024-02-01", "2024-02-29"), ("2024-03-01", "2024-03-31"))),
        ("2023-02-15", "2023-02-15", (("2023-02-01", "2023-02-28"),)),
    ],
)
@pytest.mark.parametrize(
    "rendering", [engine.WindowRenderingVocabulary.YEAR_MONTH, engine.WindowRenderingVocabulary.DATE]
)
@pytest.mark.parametrize("stop", list(engine.StopConvention))
def test_month_bounds_are_full_closed_calendar_partitions(start, end, expected, rendering, stop):
    declaration = engine.WindowDeclaration(engine.WindowGranularity("year-month"), rendering, stop)
    windows = window_planning.plan_windows(_fetch(start, end), declaration)
    assert tuple((window.bounds.start.isoformat(), window.bounds.end.isoformat()) for window in windows) == tuple(
        (f"{first}T00:00:00", f"{last}T23:59:59.999999") for first, last in expected
    )
    for window in windows:
        assert isinstance(window.bounds, engine.FetchWindow)
        assert window == engine.RenderedWindow(window.start, window.stop)
        with pytest.raises(FrozenInstanceError):
            window.bounds = None


def test_rendered_bounds_are_optional_and_typed():
    assert engine.RenderedWindow("2024-02", None).bounds is None
    with pytest.raises(TypeError, match="bounds must be a FetchWindow"):
        engine.RenderedWindow("2024-02", None, "2024-02")
    endpoint = engine.WindowEndpoint.from_datetime(datetime(2024, 2, 1))
    with pytest.raises(TypeError, match="engine-owned"):
        engine.FetchWindow(start=endpoint, end=endpoint)
    with pytest.raises(ValueError, match="start must not be after end"):
        _fetch("2024-03-01", "2024-02-01")
    with pytest.raises(TypeError, match="must not carry a time zone"):
        engine.WindowEndpoint.from_datetime(datetime(2024, 2, 1, tzinfo=UTC))


def test_nonmonthly_planner_does_not_claim_partition_bounds():
    declaration = engine.WindowDeclaration(
        engine.WindowGranularity("date"), engine.WindowRenderingVocabulary.DATE, engine.StopConvention.INCLUSIVE
    )
    assert window_planning.plan_windows(_fetch("2024-02-01", "2024-02-02"), declaration)[0].bounds is None


def _series() -> SourceSeries:
    return SourceSeries(
        series_id="station:discharge",
        provider_id="probe",
        station_id="station",
        product_id="discharge",
        identity=SourceIdentity(namespace="probe", published_id="discharge", origin="response", evidence=("fixture",)),
        facts=(PhysicalFacts(facts_id="discharge:facts"),),
    )


class _FailingTransport:
    def __init__(self, failure: TransportFailure):
        self.failure = failure

    def send(self, request: TransportRequest) -> TransportResponse:
        raise self.failure


@pytest.mark.parametrize("meaning", list(SourceResponseMeaning))
def test_failed_request_keeps_meaning_bounds_and_received_metadata(meaning):
    request = TransportRequest(HttpMethod.GET, "https://example.test/2024-02")
    response = TransportResponse(
        b'{"error":"Not Found"}',
        404,
        datetime(2024, 3, 1, tzinfo=UTC),
        "application/json",
        request.url,
        {"month": "2024-02"},
        attempts=2,
    )
    failure = TransportFailure(request, TransportFailureReason.HTTP_STATUS, 2, status_code=404, response=response)
    window = SeriesWindow(start=datetime(2024, 2, 1), end=datetime(2024, 2, 29, 23, 59, 59, 999999))
    result = attempt_series_request(_FailingTransport(failure), request, _series(), window, meaning=meaning)
    assert isinstance(result, FailedSourceRequest)
    assert result.meaning is meaning
    assert result.window == window
    assert result.request is request
    assert result.failure is failure
    assert result.failure.response is response
    assert result.event_id


def test_default_failure_does_not_infer_absence_or_fabricate_response():
    request = TransportRequest(HttpMethod.GET, "https://example.test/2024-02")
    failure = TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=404)
    window = SeriesWindow(start=datetime(2024, 2, 1), end=datetime(2024, 2, 29))
    result = attempt_series_request(_FailingTransport(failure), request, _series(), window)
    assert isinstance(result, FailedSourceRequest)
    assert result.meaning is SourceResponseMeaning.UNSPECIFIED
    assert failure.response is None
    with pytest.raises(TypeError, match="source response meaning"):
        FailedSourceRequest("event", _series(), window, request, failure, "no_observations")
    with pytest.raises(TypeError, match="failure response"):
        TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, response=b"not a response")


@pytest.mark.parametrize(
    "reason,status,expected",
    [
        (TransportFailureReason.HTTP_STATUS, 404, SourceResponseMeaning.NO_OBSERVATIONS),
        (TransportFailureReason.HTTP_STATUS, 500, SourceResponseMeaning.UNSPECIFIED),
        (TransportFailureReason.HTTP_STATUS, None, SourceResponseMeaning.UNSPECIFIED),
        (TransportFailureReason.HTTP_STATUS, 401, SourceResponseMeaning.UNSPECIFIED),
        (TransportFailureReason.RETRY_EXHAUSTED, 404, SourceResponseMeaning.UNSPECIFIED),
        (TransportFailureReason.RETRY_DELAY_EXCEEDED, 404, SourceResponseMeaning.UNSPECIFIED),
        (TransportFailureReason.REPLAY_UNSAFE, 404, SourceResponseMeaning.UNSPECIFIED),
    ],
)
def test_declared_http_meaning_requires_exact_response_status(reason, status, expected):
    from rivretrieve._internal.source_acquisition import http_response_meaning

    request = TransportRequest(HttpMethod.GET, "https://example.test/month")
    failure = TransportFailure(request, reason, 1, status_code=status)
    assert http_response_meaning(failure, {404: SourceResponseMeaning.NO_OBSERVATIONS}) is expected
    assert http_response_meaning(failure, {}) is SourceResponseMeaning.UNSPECIFIED


def test_authentication_status_does_not_establish_source_absence():
    from rivretrieve._internal.authentication import AuthenticationFailureReason, CredentialExchangeError
    from rivretrieve._internal.source_acquisition import http_response_meaning

    request = TransportRequest(HttpMethod.GET, "https://example.test/token")
    failure = CredentialExchangeError(request, AuthenticationFailureReason.EXCHANGE_HTTP_STATUS, status_code=404)
    assert (
        http_response_meaning(failure, {404: SourceResponseMeaning.NO_OBSERVATIONS})
        is SourceResponseMeaning.UNSPECIFIED
    )


@pytest.mark.parametrize("failure_carrier", ["outcomes", "failed_requests", "both", "parsed_outcomes"])
@pytest.mark.parametrize("failure_status", ["failed", "unsupported", "unresolved"])
@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_refresh_restores_disjoint_failed_intervals_without_reviving_successful_empty(
    tmp_path, failure_carrier, failure_status, retained_evidence_root: Path
):
    """Authored partitions of recorded rows exercise shared cache restoration."""
    from dataclasses import replace
    from datetime import timedelta

    import polars as pl
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.observations import ReceiptAuthorship
    from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome
    from rivretrieve._internal.store import StoreReader, StoreRoot
    from tests.test_live_cache import _END, _INSTANT, _PROVIDER, _STAGES, _START, CountedReplay, _drive

    tick = timedelta(microseconds=1)
    boundaries = [_START + timedelta(hours=6 * part) for part in range(4)]
    intervals = tuple(
        SeriesWindow(start=start, end=boundaries[index + 1] - tick if index < 3 else _END, axis=TimeAxis.UTC)
        for index, start in enumerate(boundaries)
    )
    store = tmp_path / "store"
    held = _drive(store, CountedReplay(_INSTANT, retained_evidence_root=retained_evidence_root), cache="refresh")
    old_at = held.provenance.retrieved_at
    new_at = old_at + timedelta(days=1)

    class LaterReplay(CountedReplay):
        def send(self, request):
            return replace(super().send(request), retrieved_at=new_at)

    class PartitionedStages:
        config = _STAGES.config
        window_declarations = _STAGES.window_declarations

        @staticmethod
        def fetch(*args, **kwargs):
            fetched = _STAGES.fetch(*args, **kwargs)
            payload = fetched.value[0]
            parsed = _STAGES.parse(payload, _STAGES.config)
            series = parsed.series[0]
            facts = tuple(fact.facts_id for fact in series.facts)
            failures = tuple(
                RetrievalOutcome(
                    outcome_id=f"failure-{part}",
                    series_id=series.series_id,
                    station_id=series.station_id,
                    product_id=series.product_id,
                    window=intervals[part],
                    status=OutcomeStatus(failure_status),
                    reason="authored partition failure",
                )
                for part in (0, 2)
            )
            events = tuple(
                FailedSourceRequest(
                    f"event-{part}",
                    series,
                    intervals[part],
                    request := TransportRequest(HttpMethod.GET, f"https://example.test/partition/{part}"),
                    TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503),
                )
                for part in (0, 2)
            )
            empty = RetrievalOutcome(
                outcome_id="empty-final",
                series_id=series.series_id,
                station_id=series.station_id,
                product_id=series.product_id,
                window=intervals[3],
                status=OutcomeStatus.EMPTY,
                facts_ids=facts,
                retrieved_at=new_at,
            )
            successful_bounds = _fetch(intervals[1].start.isoformat(), intervals[1].end.isoformat())
            return engine.SourceAcquisition(
                value=(replace(payload, fetch_window=successful_bounds),),
                series=parsed.series,
                inventories=parsed.inventories,
                outcomes=(*failures, empty) if failure_carrier in ("outcomes", "both") else (empty,),
                failed_requests=events if failure_carrier in ("failed_requests", "both") else (),
            )

        @staticmethod
        def parse(payload, config):
            parsed = _STAGES.parse(payload, config)
            outcomes = parsed.outcomes
            if failure_carrier == "parsed_outcomes":
                outcomes = (
                    *outcomes,
                    *(
                        outcomes[0].model_copy(
                            update={
                                "outcome_id": f"parsed-failure-{part}",
                                "window": intervals[part],
                                "status": OutcomeStatus(failure_status),
                                "reason": "authored parsed partition failure",
                            }
                        )
                        for part in (0, 2)
                    ),
                )
            return replace(
                parsed,
                outcomes=outcomes,
                rows=parsed.rows.filter(
                    pl.col("time").is_between(intervals[1].start, intervals[1].end, closed="both")
                ).with_columns(pl.col("value") * 2),
            )

    refreshed = _drive(
        store,
        LaterReplay(_INSTANT, retained_evidence_root=retained_evidence_root),
        cache="refresh",
        control=PartitionedStages(),
    )
    expected = held.canonical_rows.filter(pl.col("time") < boundaries[3]).with_columns(
        pl.when(pl.col("time").is_between(intervals[1].start, intervals[1].end, closed="both"))
        .then(pl.col("value") * 2)
        .otherwise(pl.col("value"))
        .alias("value")
    )
    assert_frame_equal(refreshed.canonical_rows.sort("time"), expected.sort("time"))
    assert refreshed.canonical_rows.height == refreshed.canonical_rows.unique(["time", "series_id"]).height
    assert len(refreshed.provenance.served_intervals) == 2
    assert sum(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in refreshed.receipts.entries) == 2
    assert all(item.retrieved_at == old_at for item in refreshed.provenance.served_intervals)
    assert {(item.interval.start, item.interval.end) for item in refreshed.provenance.served_intervals} == {
        (intervals[part].start, intervals[part].end) for part in (0, 2)
    }
    status = StoreReader().status(StoreRoot(store), _PROVIDER)
    # UTC acquisitions certify their full fetched interval, including padding.
    # Refresh changes only the authored partitions; untouched padding keeps its vintage.
    assert all(item.interval.axis is TimeAxis.UTC for item in status.coverage)
    assert {(item.interval.start, item.interval.end, item.retrieved_at) for item in status.coverage} == {
        (_START - timedelta(days=2), intervals[0].end, old_at),
        (intervals[1].start, intervals[1].end, new_at),
        (intervals[2].start, intervals[2].end, old_at),
        (intervals[3].start, intervals[3].end, new_at),
        (_END + tick, _END + timedelta(days=2), old_at),
    }
    reused = _drive(store, CountedReplay(_INSTANT, retained_evidence_root=retained_evidence_root))
    assert_frame_equal(reused.canonical_rows.sort("time"), expected.sort("time"))
