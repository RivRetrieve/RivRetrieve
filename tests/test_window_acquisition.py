from datetime import datetime, timedelta

from rivretrieve._internal.engine import RenderedWindow, SourceAcquisition, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome, SeriesWindow


def test_recovered_overflow_keeps_children_not_parent_terminal_failure():
    from rivretrieve._internal.window_acquisition import WindowAcquisition, WindowResponseMeaning, acquire_window

    window = RenderedWindow(
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:04Z",
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 1, 0, 0, 3, 999999)),
        ),
    )
    requests = []

    def acquire(child):
        requests.append((child.start, child.stop))
        overflow = len(requests) == 1
        failed = overflow or len(requests) == 3
        outcome = RetrievalOutcome(
            outcome_id=str(len(requests)),
            series_id="series",
            facts_ids=("facts",),
            station_id="station",
            product_id="product",
            window=SeriesWindow(
                start=datetime.fromisoformat(child.bounds.start.isoformat()),
                end=datetime.fromisoformat(child.bounds.end.isoformat()),
            ),
            status=OutcomeStatus.FAILED if failed else OutcomeStatus.EMPTY,
            reason="overflow" if overflow else "unrelated failure" if failed else None,
        )
        return WindowAcquisition(
            SourceAcquisition((), outcomes=(outcome,)),
            WindowResponseMeaning.OVERFLOW if overflow else WindowResponseMeaning.COMPLETE,
            (outcome.outcome_id,) if overflow else (),
        )

    result = acquire_window(window, precision=timedelta(seconds=1), acquire=acquire)
    assert requests == [
        ("2025-01-01T00:00:00Z", "2025-01-01T00:00:04Z"),
        ("2025-01-01T00:00:00Z", "2025-01-01T00:00:02Z"),
        ("2025-01-01T00:00:02Z", "2025-01-01T00:00:04Z"),
    ]
    assert [(outcome.status, outcome.reason) for outcome in result.outcomes] == [
        (OutcomeStatus.EMPTY, None),
        (OutcomeStatus.FAILED, "unrelated failure"),
    ]
    assert result.outcomes[1].window.start == datetime(2025, 1, 1, 0, 0, 2)


def test_unsplittable_overflow_retains_failure_without_success_coverage():
    from rivretrieve._internal.window_acquisition import WindowAcquisition, WindowResponseMeaning, acquire_window

    start = datetime(2025, 1, 1)
    end = datetime(2025, 1, 1, 0, 0, 0, 999999)
    window = RenderedWindow(
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:01Z",
        _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
    )
    failure = RetrievalOutcome(
        outcome_id="overflow",
        series_id=None,
        station_id="station",
        product_id="product",
        window=SeriesWindow(start=start, end=end),
        status=OutcomeStatus.FAILED,
        reason="overflow at source precision",
    )
    acquisition = SourceAcquisition((), outcomes=(failure,))
    result = acquire_window(
        window,
        precision=timedelta(seconds=1),
        acquire=lambda _: WindowAcquisition(acquisition, WindowResponseMeaning.OVERFLOW, (failure.outcome_id,)),
    )
    assert result == acquisition
    assert result.value == ()
    assert result.outcomes == (failure,)
