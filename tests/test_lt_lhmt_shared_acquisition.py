"""Public shared Lithuania acquisition; all transport responses are offline.

Neighboring months and the second station are authored cases derived from the
recorded June document, not claims about publisher availability.
"""

import calendar
import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse

STATION = "anyksciu-vms"
OTHER = "nemajunu-vms"
PRODUCTS = {"discharge_daily_mean", "stage_daily_mean"}


class SharedTransport:
    def __init__(self):
        self.recording = read_recording(Path(__file__).parent / "test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json")
        self.responses = {(STATION, "2023-06"): self.recording.content}
        self.calls = []
        self.retrieved_at = datetime(2026, 9, 27, tzinfo=UTC)

    def send(self, request):
        assert request.url.startswith("https://api.meteo.lt/v1/hydro-stations/")
        parts = request.url.split("/")
        key = (parts[-4], parts[-1])
        self.calls.append(key)
        response = self.responses.get(key, 404)
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

    def document(self, month="2023-06", station=STATION):
        document = json.loads(self.recording.content)
        document["station"]["code"] = station
        rows = document["observations"]
        days = calendar.monthrange(*map(int, month.split("-")))[1]
        document["observations"] = [
            dict(rows[(day - 1) % len(rows)], observationDateUtc=f"{month}-{day:02d}") for day in range(1, days + 1)
        ]
        return document

    def put(self, document, month="2023-06", station=STATION):
        self.responses[station, month] = json.dumps(document).encode()


@pytest.fixture
def transport(monkeypatch, tmp_path):
    transport = SharedTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    return transport


def selection(**kwargs):
    return rr.find(
        provider="lt_lhmt", station=kwargs.pop("station", STATION), frequency="daily", statistic="mean", **kwargs
    )


def fetch(chosen=None, **kwargs):
    return rr.fetch(
        chosen if chosen is not None else selection(),
        start=kwargs.pop("start", "2023-06-03"),
        end=kwargs.pop("end", "2023-06-28"),
        cache=kwargs.pop("cache", "bypass"),
        on_issue=kwargs.pop("on_issue", "ignore"),
        **kwargs,
    )


def assert_calls(result, transport, products=PRODUCTS):
    calls = result.provenance.calls_made
    assert len(calls) == len(transport.calls)
    assert Counter((call["url"].split("/")[-4], call["url"].split("/")[-1]) for call in calls) == Counter(
        transport.calls
    )
    for call in calls:
        station = call["url"].split("/")[-4]
        assert set(map(tuple, call["station_products"])) == {(station, product) for product in products}


@pytest.mark.parametrize("receipts", [False, True])
@pytest.mark.parametrize("quantity", [None, "discharge", "stage"])
@pytest.mark.parametrize(
    ("start", "end", "months", "days"),
    [
        ("2023-06-03", "2023-06-28", ["2023-06"], 26),
        ("2023-06-01", "2023-06-30", ["2023-05", "2023-06", "2023-07"], 30),
    ],
)
def test_one_attempt_per_station_month_with_exact_receipts(transport, receipts, quantity, start, end, months, days):
    chosen = selection(**({"quantity": quantity} if quantity else {}))
    result = fetch(chosen, start=start, end=end, receipts=receipts)
    products = PRODUCTS if quantity is None else {f"{quantity}_daily_mean"}
    assert transport.calls == [(STATION, month) for month in months]
    assert_calls(result, transport, products)
    assert not result.issues
    assert result.data.height == days * len(products)
    assert set(result.data["product_id"]) == products
    assert result.data["time_zone"].unique().to_list() == ["+00:00"]
    assert len(result.receipts.entries) == int(receipts)
    if receipts:
        receipt = result.receipts.entries[0]
        assert receipt.content == transport.recording.content
        assert receipt.authorship.value == "publisher_payload"
        assert receipt.origin.url.endswith("/anyksciu-vms/observations/historical/2023-06")
        assert receipt.origin.retrieved_at == transport.retrieved_at
    assert {outcome.status.value for outcome in result.outcomes} == {"success"}
    assert len(result.source_series) == len(products)
    assert result.inventories
    for definition in result.source_series:
        assert definition.station_id == STATION
        for fact in definition.facts:
            assert fact.frequency.value == "daily"
            assert fact.statistic.value == "mean"
            assert fact.time_zone.value == "+00:00"
            assert fact.day_definition.value is None
    for quantity_name, field, factor, source_unit, unit in [
        ("discharge", "waterDischarge", 1.0, "m3/s", "m3/s"),
        ("stage", "waterLevel", 0.01, "cm", "m"),
    ]:
        if quantity is not None and quantity != quantity_name:
            continue
        rows = json.loads(transport.recording.content)["observations"]
        expected = pl.DataFrame(
            {
                "time": [datetime.fromisoformat(row["observationDateUtc"]) for row in rows],
                "value": [float(row[field]) * factor if row[field] is not None else None for row in rows],
            }
        ).filter(pl.col("time").is_between(datetime.fromisoformat(start), datetime.fromisoformat(end)))
        actual = result.data.filter(pl.col("quantity") == quantity_name)
        pt.assert_frame_equal(actual.select("time", "value"), expected)
        assert actual["source_unit"].unique().to_list() == [source_unit]
        assert actual["unit"].unique().to_list() == [unit]


@pytest.mark.parametrize("failure", [404, 500, TransportFailureReason.RETRY_EXHAUSTED])
def test_multiple_stations_and_months_keep_independent_failures(transport, failure):
    for station in (STATION, OTHER):
        transport.put(transport.document("2023-05", station), "2023-05", station)
    transport.responses[OTHER, "2023-06"] = failure
    result = fetch(selection(station=(STATION, OTHER)), start="2023-05-03")
    assert Counter(transport.calls) == Counter(
        (station, month) for station in (STATION, OTHER) for month in ("2023-05", "2023-06")
    )
    assert_calls(result, transport)
    failures = [item for item in result.outcomes if item.status.value == "failed"]
    assert len(failures) == 2
    assert all(item.reason and item.window.start.month == item.window.end.month == 6 for item in failures)
    assert set(result.data.filter(pl.col("station_id") == OTHER)["time"].dt.month()) == {5}
    assert set(result.data.filter(pl.col("station_id") == STATION)["time"].dt.month()) == {5, 6}
    failed_calls = [
        call
        for call in result.provenance.calls_made
        if call["url"].split("/")[-4] == OTHER and call["url"].endswith("2023-06")
    ]
    assert len(failed_calls) == 1
    assert all(item.calls == (failed_calls[0]["call_id"],) for item in failures)
    assert {item.product_id for item in failures} == PRODUCTS
    assert result.issues
    assert not any(item.status.value == "empty" for item in result.outcomes)


def test_malformed_stage_keeps_discharge_and_separate_outcomes(transport):
    document = transport.document()
    document["observations"][0]["waterLevel"] = "not a number"
    transport.put(document)
    result = fetch(cache="reuse", receipts=True)
    assert transport.calls == [(STATION, "2023-06")]
    assert_calls(result, transport)
    assert result.data.height == 26
    assert set(result.data["quantity"]) == {"discharge"}
    assert {item.status.value for item in result.outcomes} == {"success", "unsupported"}
    assert any("waterLevel" in item.reason for item in result.outcomes if item.reason)
    assert result.receipts.entries[0].content == transport.responses[STATION, "2023-06"]
    coverage = rr.cache_status("lt_lhmt").coverage
    assert coverage
    assert {item.series_id for item in coverage} == set(result.data["series_id"])


def test_empty_null_absent_and_failed_months_are_distinct(transport):
    empty = transport.document("2023-05")
    empty["observations"] = []
    transport.put(empty, "2023-05")
    document = transport.document()
    document["observations"][2]["waterLevel"] = None
    document["observations"].pop(3)
    transport.put(document)
    result = fetch(start="2023-05-03", end="2023-07-28", cache="reuse")
    assert transport.calls == [(STATION, month) for month in ("2023-05", "2023-06", "2023-07")]
    assert_calls(result, transport)
    assert Counter(item.status.value for item in result.outcomes) == {"empty": 2, "success": 2, "failed": 2}
    assert result.data.height == 58
    assert result.data.filter(pl.col("time") == datetime(2023, 6, 4)).is_empty()
    null_day = result.data.filter(pl.col("time") == datetime(2023, 6, 3))
    assert null_day.filter(pl.col("quantity") == "stage")["value"].to_list() == [None]
    assert null_day.filter(pl.col("quantity") == "discharge")["value"].null_count() == 0
    coverage = rr.cache_status("lt_lhmt").coverage
    assert {item.interval.start.month for item in coverage} == {5, 6}
    assert len({item.series_id for item in coverage}) == 2


def test_warm_reuse_deduplicates_shared_historical_call(transport):
    seed = fetch(cache="reuse")
    chosen = rr.pick(selection(), series_id=tuple(seed.data["series_id"].unique()))
    assert transport.calls == [(STATION, "2023-06")]
    transport.calls.clear()
    transport.retrieved_at = datetime(2026, 9, 28, tzinfo=UTC)
    held = fetch(chosen, cache="reuse", receipts=True)
    assert not transport.calls
    pt.assert_frame_equal(held.data, seed.data)
    assert len(held.provenance.calls_made) == 1
    assert held.provenance.calls_made[0]["retrieved_at"] == datetime(2026, 9, 27, tzinfo=UTC)
    assert set(map(tuple, held.provenance.calls_made[0]["station_products"])) == {
        (STATION, product) for product in PRODUCTS
    }
    assert held.provenance.served_intervals
    assert all(item.retrieved_at == datetime(2026, 9, 27, tzinfo=UTC) for item in held.provenance.served_intervals)


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
def test_mixed_cache_eligibility_does_not_refresh_reused_series(transport, quantity):
    seed = fetch(selection(quantity=quantity), cache="reuse")
    old_vintage = transport.retrieved_at
    transport.calls.clear()
    transport.retrieved_at = datetime(2026, 9, 28, tzinfo=UTC)
    document = transport.document()
    for row in document["observations"]:
        row["waterDischarge"] *= 2
        row["waterLevel"] *= 2
    transport.put(document)
    # Discover both concrete identities without writing additional cache coverage.
    identities = fetch()
    transport.calls.clear()
    chosen = rr.pick(selection(), series_id=tuple(identities.data["series_id"].unique()))
    result = fetch(chosen, cache="reuse", receipts=True)
    assert transport.calls == [(STATION, "2023-06")]
    pt.assert_frame_equal(result.data.filter(pl.col("quantity") == quantity), seed.data)
    fresh_product = "stage_daily_mean" if quantity == "discharge" else "discharge_daily_mean"
    fresh_calls = [call for call in result.provenance.calls_made if call["retrieved_at"] == transport.retrieved_at]
    assert len(fresh_calls) == 1
    assert set(map(tuple, fresh_calls[0]["station_products"])) == {(STATION, fresh_product)}
    publisher_receipts = [
        entry for entry in result.receipts.entries if entry.content == transport.responses[STATION, "2023-06"]
    ]
    assert len(publisher_receipts) == 1
    assert publisher_receipts[0].authorship.value == "publisher_payload"
    coverage = rr.cache_status("lt_lhmt").coverage
    assert {item.retrieved_at for item in coverage if item.series_id in set(seed.data["series_id"])} == {old_vintage}


@pytest.mark.parametrize("failure", [404, "malformed-stage"])
def test_refresh_retains_failed_series_original_values_and_vintage(transport, failure):
    seed = fetch(cache="reuse")
    old_vintage = transport.retrieved_at
    transport.calls.clear()
    transport.retrieved_at = datetime(2026, 9, 28, tzinfo=UTC)
    if failure == 404:
        transport.responses[STATION, "2023-06"] = 404
    else:
        document = transport.document()
        for row in document["observations"]:
            row["waterDischarge"] *= 2
        document["observations"][0]["waterLevel"] = "bad"
        transport.put(document)
    result = fetch(cache="refresh")
    assert transport.calls == [(STATION, "2023-06")]
    retained = pl.lit(True) if failure == 404 else pl.col("quantity") == "stage"
    pt.assert_frame_equal(result.data.filter(retained), seed.data.filter(retained))
    if failure != 404:
        pt.assert_frame_equal(
            result.data.filter(~retained).select("value"), seed.data.filter(~retained).select(pl.col("value") * 2)
        )
    assert result.issues
    assert result.provenance.served_intervals
    assert all(item.retrieved_at == old_vintage for item in result.provenance.served_intervals)
    held_ids = set(seed.data.filter(retained)["series_id"])
    assert tuple(item for item in result.source_series if item.series_id in held_ids) == tuple(
        item for item in seed.source_series if item.series_id in held_ids
    )
    coverage = rr.cache_status("lt_lhmt").coverage
    assert {item.retrieved_at for item in coverage if item.series_id in held_ids} == {old_vintage}
    transport.calls.clear()
    chosen = rr.pick(selection(), series_id=tuple(seed.data["series_id"].unique()))
    again = fetch(chosen, cache="reuse")
    assert not transport.calls
    pt.assert_frame_equal(again.data, result.data)


@pytest.mark.parametrize("policy", ["ignore", "warn", "raise"])
def test_shared_internal_parser_contract_errors_still_raise(transport, monkeypatch, policy):
    from rivretrieve._internal.providers.lt_lhmt.declaration import declaration

    original = declaration.observations.stages
    lookup = discovery._provider_lookup

    class BrokenParse:
        config = original.config
        window_declarations = original.window_declarations
        fetch = staticmethod(original.fetch)

        @staticmethod
        def parse(payload, config):
            raise FatalContractError("authored shared parser defect")

    monkeypatch.setattr(
        discovery, "_provider_lookup", lambda provider: replace(lookup(provider), _stages=BrokenParse())
    )
    with pytest.raises(FatalContractError, match="authored shared parser defect"):
        fetch(on_issue=policy)


@pytest.mark.parametrize("advance_clock", [False, True])
def test_refresh_keeps_same_url_attempts_distinct(transport, advance_clock):
    first = fetch(cache="reuse")
    old = transport.retrieved_at
    if advance_clock:
        transport.retrieved_at = datetime(2026, 9, 28, tzinfo=UTC)
    second = fetch(cache="refresh")
    assert transport.calls == [(STATION, "2023-06"), (STATION, "2023-06")]
    assert len(first.provenance.calls_made) == len(second.provenance.calls_made) == 1
    earlier, later = first.provenance.calls_made[0], second.provenance.calls_made[0]
    assert earlier["url"] == later["url"]
    assert earlier["call_id"] != later["call_id"]
    manifest = rr.cache_status("lt_lhmt").manifest
    assert manifest is not None
    assert {call["call_id"] for call in manifest.source_calls} == {earlier["call_id"], later["call_id"]}
    assert len(manifest.source_calls) == 2
    assert earlier["retrieved_at"] == old
    assert later["retrieved_at"] == transport.retrieved_at
    assert {item.retrieved_at for item in rr.cache_status("lt_lhmt").coverage} == {transport.retrieved_at}
    pt.assert_frame_equal(first.data, second.data)


@pytest.mark.parametrize("failure", [401, 403, 500, b"not JSON", TransportFailureReason.RETRY_EXHAUSTED])
@pytest.mark.parametrize("requested", [False, True])
def test_shared_non_absence_failure_preserves_other_month(transport, failure, requested):
    transport.responses[STATION, "2023-05"] = failure
    result = fetch(start="2023-05-03" if requested else "2023-06-01", end="2023-06-05")
    assert transport.calls == [(STATION, "2023-05"), (STATION, "2023-06")]
    assert_calls(result, transport)
    assert result.data.height == 10
    assert set(result.data["quantity"]) == {"discharge", "stage"}
    assert result.issues
    if isinstance(failure, int):
        assert all(issue.details["status_code"] == failure for issue in result.issues)
    elif isinstance(failure, bytes):
        assert any("JSON" in issue.message for issue in result.issues)
    else:
        assert any("timeout" in issue.message for issue in result.issues)
    if requested:
        failures = [item for item in result.outcomes if item.status.value in {"failed", "unsupported"}]
        assert len(failures) == 2
        assert {item.product_id for item in failures} == PRODUCTS
        assert all(item.reason and item.window.start.month == item.window.end.month == 5 for item in failures)


@pytest.mark.parametrize("exhausted", [False, True])
def test_shared_http_retries_report_attempt_count_not_invented_intermediate_calls(transport, monkeypatch, exhausted):
    from rivretrieve._internal.transport import TRANSPORT_POLICY, HttpClient, SenderResponse

    attempts = []

    def sender(request, timeout):
        attempts.append(request)
        if exhausted or len(attempts) == 1:
            return SenderResponse(b'{"error":"temporarily unavailable"}', 503, "application/json")
        return SenderResponse(transport.recording.content, 200, "application/json")

    client = HttpClient(sender=sender, sleeper=lambda delay: None)
    monkeypatch.setattr(discovery, "HttpClient", lambda: client)
    result = fetch(receipts=True)
    count = TRANSPORT_POLICY.max_attempts if exhausted else 2
    assert len(attempts) == count
    assert len({request.url for request in attempts}) == 1
    calls = result.provenance.calls_made
    # The transport exposes the final response and total attempts, not the
    # timestamps or response metadata of intermediate retry attempts.
    assert len(calls) == 1
    assert calls[0]["attempts"] == count
    assert calls[0]["status_code"] == (503 if exhausted else 200)
    assert set(map(tuple, calls[0]["station_products"])) == {(STATION, product) for product in PRODUCTS}
    if exhausted:
        assert result.data.is_empty()
        assert len(result.outcomes) == 2
        assert all(item.status.value == "failed" and item.calls == (calls[0]["call_id"],) for item in result.outcomes)
        assert result.issues
        assert not result.receipts.entries
    else:
        assert result.data.height == 52
        assert not result.issues
        assert len(result.receipts.entries) == 1
        assert result.receipts.entries[0].content == transport.recording.content


def test_unrestricted_incomplete_inventory_reacquires_once_for_both_products(transport):
    seed = fetch(cache="reuse")
    assert all(item.completeness.value == "incomplete" for item in seed.inventories)
    transport.calls.clear()
    result = fetch(cache="reuse")
    assert transport.calls == [(STATION, "2023-06")]
    assert_calls(result, transport)
    pt.assert_frame_equal(seed.data, result.data)


def test_shared_multimonth_refresh_preserves_failed_month_and_replaces_success(transport):
    transport.put(transport.document("2023-05"), "2023-05")
    seed = fetch(start="2023-05-03", cache="reuse")
    chosen = rr.pick(selection(), series_id=tuple(seed.data["series_id"].unique()))
    old_vintage = transport.retrieved_at
    transport.calls.clear()
    transport.retrieved_at = datetime(2026, 9, 28, tzinfo=UTC)
    transport.responses[STATION, "2023-05"] = 404
    document = transport.document()
    for row in document["observations"]:
        row["waterDischarge"] *= 2
        row["waterLevel"] *= 2
    transport.put(document)
    result = fetch(chosen, start="2023-05-03", cache="refresh")
    assert transport.calls == [(STATION, "2023-05"), (STATION, "2023-06")]
    may = pl.col("time").dt.month() == 5
    pt.assert_frame_equal(result.data.filter(may), seed.data.filter(may))
    pt.assert_frame_equal(result.data.filter(~may), seed.data.filter(~may).with_columns(pl.col("value") * 2))
    assert result.source_series == seed.source_series
    failures = [item for item in result.outcomes if item.status.value == "failed"]
    assert len(failures) == 2
    assert {item.product_id for item in failures} == PRODUCTS
    assert all(item.reason and item.window.start.month == item.window.end.month == 5 for item in failures)
    failed_calls = [call for call in result.provenance.calls_made if call.get("status_code") == 404]
    assert len(failed_calls) == 1
    assert all(item.calls == (failed_calls[0]["call_id"],) for item in failures)
    fresh_calls = [call for call in result.provenance.calls_made if call["retrieved_at"] == transport.retrieved_at]
    assert len(fresh_calls) == 2
    assert all(
        set(map(tuple, call["station_products"])) == {(STATION, product) for product in PRODUCTS}
        for call in fresh_calls
    )
    assert result.provenance.served_intervals
    assert all(
        item.retrieved_at == old_vintage and item.interval.start.month == item.interval.end.month == 5
        for item in result.provenance.served_intervals
    )
    coverage = rr.cache_status("lt_lhmt").coverage
    assert {item.series_id for item in coverage} == set(seed.data["series_id"])
    assert {item.interval.start.month for item in coverage} == {5, 6}
    assert all(item.retrieved_at == old_vintage for item in coverage if item.interval.start.month == 5)
    assert all(item.retrieved_at == transport.retrieved_at for item in coverage if item.interval.start.month == 6)
    # Monthly inventories do not claim a complete combined multi-month scope.
    # Each independently covered month can still serve explicit series locally.
    transport.calls.clear()
    for month in (5, 6):
        start = f"2023-{month:02d}-03"
        end = f"2023-{month:02d}-28"
        held = fetch(chosen, start=start, end=end, cache="reuse")
        assert not transport.calls
        expected = result.data.filter(
            pl.col("time").is_between(datetime.fromisoformat(start), datetime.fromisoformat(end))
        )
        pt.assert_frame_equal(held.data, expected)
        assert held.source_series == result.source_series
