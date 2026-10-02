"""Public Lithuania retrieval preserves independently acquired monthly evidence."""

import calendar
import json
import warnings
from datetime import UTC, datetime

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse


@pytest.fixture
def recording(retained_evidence_root):
    return read_recording(retained_evidence_root / "tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json")


class MonthlyTransport:
    def __init__(self, recording, responses=None):
        self.recording = recording
        self.calls = []
        self.responses = responses or {}
        self.retrieved_at = datetime(2026, 9, 27, tzinfo=UTC)

    def send(self, request):
        month = request.url.rsplit("/", 1)[-1]
        self.calls.append(month)
        response = self.responses.get(month, self.recording.content if month == "2023-06" else 404)
        if isinstance(response, TransportFailureReason):
            raise TransportFailure(request, response, 3)
        return TransportResponse(
            content=response if isinstance(response, bytes) else b'{"error":"No data"}',
            status_code=200 if isinstance(response, bytes) else response,
            retrieved_at=self.retrieved_at,
            content_type="application/json",
            url=request.url,
            request_parameters={},
        )


@pytest.mark.parametrize(
    ("start", "end", "rows", "months"),
    [
        ("2023-06-01", "2023-06-05", 5, ["2023-05", "2023-06"]),
        ("2023-06-03", "2023-06-29", 27, ["2023-06", "2023-07"]),
        ("2023-06-01", "2023-06-30", 30, ["2023-05", "2023-06", "2023-07"]),
    ],
)
def test_padding_only_404_preserves_requested_rows(recording, monkeypatch, start, end, rows, months):
    transport = MonthlyTransport(recording)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    selection = rr.find(provider="lt_lhmt", station="anyksciu-vms", quantity="discharge")
    result = rr.fetch(selection, start=start, end=end, cache="bypass", receipts=True, on_issue="ignore")
    assert result.data.height == rows
    assert transport.calls == months
    assert not result.issues
    assert result.data["time"].min().date().isoformat() == start
    assert result.data["time"].max().date().isoformat() == end
    assert len(result.receipts.entries) == 1
    assert result.receipts.entries[0].content == transport.recording.content


def authored_month(transport, month, *, empty=False, null=False):
    """Controlled neighboring responses derived from the recorded June document.

    Date shifts and optional empty/null values are authored test cases, not claims
    about publisher availability. The June success uses exact recorded bytes.
    """
    document = json.loads(transport.recording.content)
    days = calendar.monthrange(*map(int, month.split("-")))[1]
    document["observations"] = [
        dict(row, observationDateUtc=f"{month}-{index:02d}")
        for index, row in enumerate(document["observations"][:days], 1)
    ]
    if empty:
        document["observations"] = []
    if null:
        document["observations"][0].update(waterLevel=None, waterDischarge=None)
    return json.dumps(document).encode()


def month_bounds(month):
    days = calendar.monthrange(*map(int, month.split("-")))[1]
    return {"start": f"{month}-01T00:00:00", "end": f"{month}-{days:02d}T23:59:59.999999", "axis": "native"}


def selection(quantity="discharge"):
    return rr.find(provider="lt_lhmt", station="anyksciu-vms", quantity=quantity, frequency="daily", statistic="mean")


def fetch(chosen=None, **kwargs):
    return rr.fetch(
        chosen if chosen is not None else selection(),
        start=kwargs.pop("start", "2023-05-03"),
        end=kwargs.pop("end", "2023-07-28"),
        cache=kwargs.pop("cache", "bypass"),
        on_issue=kwargs.pop("on_issue", "ignore"),
        **kwargs,
    )


@pytest.mark.parametrize("failed", [("2023-05",), ("2023-06",), ("2023-07",), ("2023-05", "2023-06", "2023-07")])
def test_requested_month_failures_have_precise_outcomes(recording, monkeypatch, failed):
    transport = MonthlyTransport(recording)
    months = ["2023-05", "2023-06", "2023-07"]
    transport.responses = {month: (404 if month in failed else authored_month(transport, month)) for month in months}
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = fetch()
    assert transport.calls == months
    actual = set(result.data["time"].dt.strftime("%Y-%m"))
    assert actual == set(months) - set(failed)
    failed_outcomes = [item for item in result.outcomes if item.status.value == "failed"]
    assert len(failed_outcomes) == len(failed)
    for item in failed_outcomes:
        month = item.window.start.strftime("%Y-%m")
        assert month in failed
        start = datetime.fromisoformat(month_bounds(month)["start"])
        end = datetime.fromisoformat(month_bounds(month)["end"])
        assert item.window.start == max(start, datetime(2023, 5, 3))
        assert item.window.end == min(end, datetime(2023, 7, 28, 23, 59, 59, 999999))
        assert item.reason
    assert len(result.issues) == len(failed)
    assert all(issue.details["status_code"] == 404 for issue in result.issues)
    for issue in result.issues:
        month = issue.details["request_url"].rsplit("/", 1)[-1]
        assert month in failed
        assert issue.details["window"] == month_bounds(month)
    assert not any(item.status.value == "empty" for item in result.outcomes)


@pytest.mark.parametrize("receipts", [False, True])
def test_call_evidence_independent_of_receipts(recording, monkeypatch, receipts):
    transport = MonthlyTransport(recording)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = fetch(start="2023-06-01", end="2023-06-30", receipts=receipts, on_issue="warn")
    assert not caught
    calls = result.provenance.calls_made
    assert len(calls) == 3
    assert {call["url"].rsplit("/", 1)[-1]: call["status_code"] for call in calls} == {
        "2023-05": 404,
        "2023-06": 200,
        "2023-07": 404,
    }
    assert all(call["retrieved_at"] == transport.retrieved_at for call in calls)
    assert all(call["content_type"] == "application/json" for call in calls)
    for call in calls:
        month = call["url"].rsplit("/", 1)[-1]
        assert call["url"] == f"https://api.meteo.lt/v1/hydro-stations/anyksciu-vms/observations/historical/{month}"
        if call["status_code"] == 404:
            assert call["window"] == month_bounds(month)
    assert len(result.receipts.entries) == int(receipts)
    if receipts:
        assert result.receipts.entries[0].content == transport.recording.content


@pytest.mark.parametrize(
    ("quantity", "field", "factor"), [("discharge", "waterDischarge", 1), ("stage", "waterLevel", 0.01)]
)
def test_empty_null_and_failed_months_are_distinct(recording, monkeypatch, quantity, field, factor):
    transport = MonthlyTransport(recording)
    transport.responses = {
        "2023-05": authored_month(transport, "2023-05", empty=True),
        "2023-06": authored_month(transport, "2023-06", null=True),
        "2023-07": 404,
    }
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = fetch(selection(quantity))
    rows = json.loads(transport.responses["2023-06"])["observations"]
    expected = pl.DataFrame(
        {
            "time": [datetime.fromisoformat(row["observationDateUtc"]) for row in rows],
            "value": [None if row[field] is None else row[field] * factor for row in rows],
        }
    )
    pt.assert_frame_equal(result.data.select("time", "value"), expected)
    assert {item.status.value for item in result.outcomes} == {"empty", "success", "failed"}
    assert result.data["time_zone"].unique().to_list() == ["+00:00"]


@pytest.mark.parametrize("failure", [401, 403, 500, b"not JSON", TransportFailureReason.RETRY_EXHAUSTED])
def test_non_absence_failures_keep_diagnostics_and_sibling_rows(recording, monkeypatch, failure):
    transport = MonthlyTransport(recording, {"2023-05": failure})
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = fetch(start="2023-06-01", end="2023-06-05")
    assert result.data.height == 5
    assert result.issues
    assert transport.calls == ["2023-05", "2023-06"]
    if isinstance(failure, int):
        assert result.issues[0].details["status_code"] == failure
    elif isinstance(failure, bytes):
        assert "JSON" in result.issues[0].message
    else:
        assert "timeout" in result.issues[0].message


def test_requested_failure_obeys_warning_and_raise_policy(recording, monkeypatch):
    from rivretrieve._internal.issues import IssuePolicyError

    transport = MonthlyTransport(recording)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    with pytest.warns(RuntimeWarning, match="404"):
        result = fetch(start="2023-05-03", end="2023-06-28", on_issue="warn")
    assert result.data.height == 28
    with pytest.raises(IssuePolicyError):
        fetch(start="2023-05-03", end="2023-06-28", on_issue="raise")


def test_explicit_series_partial_cache_retries_failed_month(recording, monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = MonthlyTransport(recording)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    seed = fetch(start="2023-06-03", end="2023-06-28")
    explicit = rr.pick(selection(), series_id=tuple(seed.data["series_id"].unique()), on_issue="ignore")
    partial = fetch(explicit, start="2023-05-03", end="2023-06-28", cache="reuse")
    pt.assert_frame_equal(seed.data, partial.data.filter(pl.col("time") >= datetime(2023, 6, 3)))
    coverage = rr.cache_status("lt_lhmt").coverage
    assert coverage
    assert all(item.interval.start.month == item.interval.end.month == 6 for item in coverage)
    assert min(item.interval.start for item in coverage) == datetime(2023, 6, 1)
    assert max(item.interval.end for item in coverage).date().isoformat() == "2023-06-28"
    transport.calls.clear()
    held = fetch(explicit, start="2023-06-03", end="2023-06-28", cache="reuse")
    assert transport.calls == []
    pt.assert_frame_equal(seed.data, held.data)
    transport.responses["2023-05"] = authored_month(transport, "2023-05")
    recovered = fetch(explicit, start="2023-05-03", end="2023-06-28", cache="reuse")
    assert "2023-05" in transport.calls
    assert recovered.data.height == 56
    transport.calls.clear()
    again = fetch(explicit, start="2023-05-03", end="2023-06-28", cache="reuse")
    # Multi-month inventory is not inferred from monthly snapshots.
    pt.assert_frame_equal(recovered.data, again.data)


def test_failed_refresh_keeps_held_month_and_original_vintage(recording, monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = MonthlyTransport(recording)
    transport.responses["2023-05"] = authored_month(transport, "2023-05")
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    seed = fetch(start="2023-05-03", end="2023-06-28", cache="reuse")
    explicit = rr.pick(selection(), series_id=tuple(seed.data["series_id"].unique()), on_issue="ignore")
    old_vintage = transport.retrieved_at
    transport.retrieved_at = datetime(2026, 9, 28, tzinfo=UTC)
    transport.responses["2023-05"] = 404
    document = json.loads(transport.recording.content)
    for row in document["observations"]:
        row["waterDischarge"] *= 2
    transport.responses["2023-06"] = json.dumps(document).encode()
    refreshed = fetch(explicit, start="2023-05-03", end="2023-06-28", cache="refresh")
    may = pl.col("time").dt.month() == 5
    pt.assert_frame_equal(refreshed.data.filter(may), seed.data.filter(may))
    pt.assert_frame_equal(
        refreshed.data.filter(~may).select("value"), seed.data.filter(~may).select(pl.col("value") * 2)
    )
    assert refreshed.issues
    assert refreshed.provenance.served_intervals
    assert all(
        item.retrieved_at == old_vintage and item.interval.start.month == item.interval.end.month == 5
        for item in refreshed.provenance.served_intervals
    )
    coverage = rr.cache_status("lt_lhmt").coverage
    assert all(item.retrieved_at == old_vintage for item in coverage if item.interval.start.month == 5)
    assert all(item.retrieved_at == transport.retrieved_at for item in coverage if item.interval.start.month == 6)
    transport.calls.clear()
    held = fetch(explicit, start="2023-05-03", end="2023-06-28", cache="reuse")
    pt.assert_frame_equal(refreshed.data, held.data)


@pytest.mark.parametrize("policy", ["ignore", "warn", "raise"])
def test_internal_parse_contract_failure_is_fatal(recording, monkeypatch, policy):
    from dataclasses import replace

    from rivretrieve._internal.issues import FatalContractError

    transport = MonthlyTransport(recording)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    from rivretrieve._internal.providers.lt_lhmt.declaration import declaration

    lookup = discovery._provider_lookup
    original = declaration.observations.stages

    class BrokenParse:
        config = original.config
        window_declarations = original.window_declarations
        fetch = staticmethod(original.fetch)

        @staticmethod
        def parse(payload, config):
            raise FatalContractError("authored internal contract failure")

    monkeypatch.setattr(
        discovery, "_provider_lookup", lambda provider: replace(lookup(provider), _stages=BrokenParse())
    )
    with pytest.raises(FatalContractError, match="authored internal contract failure"):
        fetch(start="2023-06-03", end="2023-06-28", on_issue=policy)


def test_malformed_requested_month_preserves_sibling_months(recording, monkeypatch):
    transport = MonthlyTransport(recording)
    transport.responses = {
        "2023-05": authored_month(transport, "2023-05"),
        "2023-06": b"not JSON",
        "2023-07": authored_month(transport, "2023-07"),
    }
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = fetch()
    assert set(result.data["time"].dt.month()) == {5, 7}
    assert len(result.issues) == 1
    assert "JSON" in result.issues[0].message
    failures = [item for item in result.outcomes if item.status.value == "unsupported"]
    assert len(failures) == 1
    assert failures[0].window.start.month == failures[0].window.end.month == 6
