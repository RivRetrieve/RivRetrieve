"""Annual source failures do not discard or replace independent annual evidence."""

import json
from datetime import UTC, datetime

import polars.testing as pt
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.transport import TransportResponse
from tests.test_cz_chmi_observations import _DQ, _STATION

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


class AnnualTransport:
    def __init__(self, responses=None, value=1):
        self.responses = responses or {}
        self.value = value
        self.calls = []
        self.document = json.loads(read_recording(_DQ).content)

    def send(self, request):
        year = int(request.url.rsplit("_", 1)[-1].split(".")[0])
        self.calls.append(year)
        response = self.responses.get(year)
        if response is None:
            document = json.loads(json.dumps(self.document))
            for member in document["tsList"]:
                member["tsData"]["data"]["values"] = [[f"{year}-06-01T00:00:00Z", self.value]]
            response = json.dumps(document).encode()
        return TransportResponse(
            content=response if isinstance(response, bytes) else b"missing",
            status_code=200 if isinstance(response, bytes) else response,
            retrieved_at=datetime(2026, 9, 28, tzinfo=UTC),
            content_type="application/json",
            url=request.url,
            request_parameters={},
        )


def selection():
    found = rr.find(provider="cz_chmi", station=_STATION, quantity="discharge", frequency="daily")
    return rr.pick(found, series_id=[series.series_id for series in found.series])


def fetch(**kwargs):
    return rr.fetch(selection(), start="2021-03-01", end="2023-09-01", on_issue="ignore", **kwargs)


@pytest.mark.parametrize("failed", [(2021,), (2022,), (2023,), (2021, 2022, 2023)])
def test_independent_annual_failure_positions(monkeypatch, failed):
    transport = AnnualTransport(dict.fromkeys(failed, 404))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = fetch(cache="bypass", receipts=True)
    assert transport.calls == [2021, 2022, 2023]
    assert set(result.data["time"].dt.year()) == {2021, 2022, 2023} - set(failed)
    assert len(result.receipts.entries) == 3 - len(failed)
    failures = [item for item in result.outcomes if item.status == "failed"]
    assert len(failures) == len(failed)
    assert {item.window.start.year for item in failures} == set(failed)
    assert all(item.window.start.year == item.window.end.year for item in failures)
    assert len(result.provenance.calls_made) == 3


@pytest.mark.parametrize("failed", [2021, 2023])
def test_partial_refresh_persists_healthy_year_and_preserves_held_year(monkeypatch, tmp_path, failed):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = AnnualTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    fetch(cache="refresh")
    transport.value = 2
    transport.responses = {failed: b"malformed"}
    result = fetch(cache="refresh")
    assert result.data.sort("time")["value"].to_list() == [1 if year == failed else 2 for year in (2021, 2022, 2023)]
    manifest = json.loads((tmp_path / "cz_chmi/store/manifest.json").read_text())
    assert manifest["coverage"]
    transport.calls.clear()
    reused = fetch(cache="reuse")
    assert not transport.calls
    pt.assert_frame_equal(result.data.sort("time"), reused.data.sort("time"))


def test_uncached_partial_success_persists_and_failed_interval_retries(monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = AnnualTransport({2022: 503})
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = fetch(cache="refresh")
    assert result.data.height == 2
    manifest = json.loads((tmp_path / "cz_chmi/store/manifest.json").read_text())
    assert len(manifest["coverage"]) == 2
    transport.calls.clear()
    fetch(cache="reuse")
    assert transport.calls == [2021, 2022, 2023]


def test_padding_only_missing_year_remains_diagnostic(monkeypatch):
    transport = AnnualTransport({2022: 404})
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = rr.fetch(selection(), start="2023-01-01", end="2023-06-02", cache="bypass", on_issue="ignore")
    assert result.data.height == 1
    assert transport.calls == [2022, 2023]
    assert result.issues
    assert any(call.get("status_code") == 404 for call in result.provenance.calls_made)


def test_shared_annual_failure_has_one_call_and_distinct_series_events():
    from rivretrieve._internal.engine import RenderedWindow
    from rivretrieve._internal.providers.cz_chmi.config import config
    from rivretrieve._internal.providers.cz_chmi.fetch import fetch as acquire
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason
    from tests.test_cz_chmi_observations import _PRODUCTS, _window

    class FailureTransport:
        def send(self, request):
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=404)

    products = _PRODUCTS[:3]
    bounds = _window()
    result = acquire(
        (_STATION,),
        products,
        {p: (RenderedWindow("2023", None, bounds),) for p in products},
        bounds,
        config(),
        FailureTransport(),
    )
    assert len(result.failed_requests) == 3
    assert len({item.event_id for item in result.failed_requests}) == 3
    assert len({item.call_id for item in result.failed_requests}) == 1
    assert len({item.series.series_id for item in result.failed_requests}) == 3


def test_valid_empty_annual_refresh_replaces_only_its_year(monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = AnnualTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    fetch(cache="refresh")
    empty = json.loads(json.dumps(transport.document))
    for member in empty["tsList"]:
        member["tsData"]["data"]["values"] = []
    transport.responses = {2022: json.dumps(empty).encode()}
    result = fetch(cache="refresh")
    assert result.data["time"].dt.year().sort().to_list() == [2021, 2023]
    assert any(item.status == "empty" and item.window.start.year == 2022 for item in result.outcomes)
