"""Independent MLIT intervals keep failed dependencies beside healthy evidence."""

from dataclasses import replace
from datetime import datetime

import pytest

from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.jp_mlit.config import config
from rivretrieve._internal.providers.jp_mlit.fetch import fetch
from rivretrieve._internal.providers.jp_mlit.parse import parse
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason
from tests.test_jp_mlit_observations import _PATHS, _STATION


class _Chunks:
    def __init__(self, failed, role):
        self.failed = failed
        self.role = role
        self.calls = []
        self.replay = ReplayTransport(_PATHS)
        self.chunk = None

    def send(self, request):
        role = "html" if request.params else "dat"
        if role == "html":
            self.chunk = int(str(request.params["BGNDATE"])[:4])
        self.calls.append((self.chunk, role))
        if self.chunk in self.failed and role == self.role:
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 3, status_code=503)
        # Authored year shifts retain the recorded source structure and all bytes
        # except dates. Independent January requests avoid invented monthly rows.
        replay_request = request
        if role == "html":
            replay_request = replace(
                request,
                params={
                    **request.params,
                    "BGNDATE": str(request.params["BGNDATE"]).replace(str(self.chunk), "2023"),
                    "ENDDATE": str(request.params["ENDDATE"]).replace(str(self.chunk), "2023"),
                },
            )
        response = self.replay.send(replay_request)
        return replace(
            response,
            content=(
                response.content if role == "html" else response.content.replace(b"2023", str(self.chunk).encode())
            ),
            request_parameters=request.params or {},
        )


def _windows(product):
    return tuple(
        RenderedWindow(
            f"{year}-01-01",
            f"{year}-01-31" if "hourly" in product else f"{year}-12-31",
            bounds=_make_fetch_window(
                WindowEndpoint.from_datetime(datetime(year, 1, 1)),
                WindowEndpoint.from_datetime(
                    datetime(year, 1, 31, 23, 59, 59, 999999)
                    if "hourly" in product
                    else datetime(year, 12, 31, 23, 59, 59, 999999)
                ),
            ),
        )
        for year in (2021, 2022, 2023)
    )


@pytest.mark.parametrize("product", ["stage_hourly", "stage_daily", "discharge_hourly", "discharge_daily"])
@pytest.mark.parametrize("role", ["html", "dat"])
@pytest.mark.parametrize("failed", [(2021,), (2022,), (2023,), (2021, 2022, 2023)])
def test_independent_chunks_retain_bounds_failures_and_prerequisites(product, role, failed):
    product = ProductId(product)
    windows = _windows(product)
    transport = _Chunks(failed, role)
    result = fetch((_STATION,), (product,), {product: windows}, windows[0].bounds, config(), transport)
    assert [year for year, kind in transport.calls if kind == "html"] == [2021, 2022, 2023]
    assert len(result.failed_requests) == len(failed)
    for failure in result.failed_requests:
        year = failure.window.start.year
        assert year in failed
        bounds = windows[year - 2021].bounds
        assert failure.window.start.isoformat() == bounds.start.isoformat()
        assert failure.window.end.isoformat() == bounds.end.isoformat()
        assert failure.failure.status_code == 503
        assert failure.failure.attempts == 3
        assert ("DspWaterData" in failure.request.url) == (role == "html")
    successful = []
    for payload in result.value:
        year = int(payload.fetch_window.start.isoformat()[:4])
        assert payload.fetch_window == windows[year - 2021].bounds
        parsed = parse(payload, config())
        if payload.source_coordinates.value.role == "html":
            assert parsed.outcomes == ()
            assert parsed.rows.is_empty()
        else:
            assert parsed.rows.height > 0
            assert len(parsed.outcomes) == 1
            successful.append(year)
    assert successful == [year for year in (2021, 2022, 2023) if year not in failed]
    assert len(result.value) == 6 - len(failed) * (2 if role == "html" else 1)


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_dat_failure_retains_html_and_cache_coverage(monkeypatch, tmp_path):
    # One public composition covers receipts, partial persistence, and retry. The
    # cheap stage matrix above exercises all independent positions and products.
    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = _Chunks((2022,), "dat")
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    selection = rr.find(provider="jp_mlit", station=_STATION, quantity="stage", frequency="daily")
    selection = rr.pick(selection, series_id=tuple(series.series_id for series in selection.series))
    result = rr.fetch(
        selection, start="2021-01-03", end="2023-12-29", cache="refresh", receipts=True, on_issue="ignore"
    )
    assert set(result.data["time"].dt.year()) == {2021, 2023}
    assert len(result.receipts.entries) == 5
    assert sorted(o.status.value for o in result.outcomes) == ["failed", "success", "success"]
    assert len(result.provenance.calls_made) == 6
    before = len(transport.calls)
    held = rr.fetch(selection, start="2021-01-03", end="2021-12-29", cache="reuse", on_issue="ignore")
    assert held.data.height == 361
    assert len(transport.calls) == before
    transport.failed = ()
    second = rr.fetch(selection, start="2022-01-03", end="2022-12-29", cache="reuse", on_issue="ignore")
    assert set(second.data["time"].dt.year()) == {2022}
    assert transport.calls[before:] == [(2022, "html"), (2022, "dat")]


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_hour_24_month_end_survives_failed_or_empty_neighbor_and_reuse(monkeypatch, tmp_path):
    import polars as pl
    from polars.testing import assert_frame_equal

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from tests.test_jp_mlit_html_outcomes import _negative_derivative

    class Months:
        def __init__(self):
            self.replay = ReplayTransport(_PATHS)
            self.calls = []
            self.january_failed = False
            self.february_empty = False

        def send(self, request):
            self.calls.append(request)
            if request.params:
                february = request.params["BGNDATE"] == "20230201"
                if (february and not self.february_empty) or (not february and self.january_failed):
                    raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
                if february:
                    recorded_request = replace(
                        request, params={**request.params, "BGNDATE": "20230101", "ENDDATE": "20230131"}
                    )
                    response = self.replay.send(recorded_request)
                    return replace(
                        response,
                        content=_negative_derivative(response.content, "no-data-marker"),
                        request_parameters=request.params,
                    )
            return self.replay.send(request)

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = Months()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    selected = rr.find(provider="jp_mlit", station=_STATION, quantity="stage", frequency="hourly")
    selected = rr.pick(selected, series_id=tuple(series.series_id for series in selected.series))

    def retrieve(end, cache):
        return rr.fetch(selected, start=datetime(2023, 1, 3), end=end, cache=cache, on_issue="ignore")

    result = retrieve(datetime(2023, 2, 1), "refresh")
    assert result.data.height == 697
    assert result.data["time"].max() == datetime(2023, 2, 1)
    stored = pl.concat([pl.read_parquet(path) for path in (tmp_path / "jp_mlit/store").rglob("*.parquet")])
    assert stored.height == result.data.height
    assert stored["time"].max() == datetime(2023, 2, 1)
    before = len(transport.calls)
    assert_frame_equal(retrieve(datetime(2023, 2, 1), "reuse").data, result.data)
    assert len(transport.calls) == before

    transport.january_failed = True
    transport.february_empty = True
    refreshed = retrieve(datetime(2023, 2, 2), "refresh")
    assert_frame_equal(refreshed.data, result.data)
    empty = next(item for item in refreshed.outcomes if item.status == "empty")
    assert empty.window.start == datetime(2023, 2, 1, 0, 0, 0, 1)
    before = len(transport.calls)
    assert_frame_equal(retrieve(datetime(2023, 2, 2), "reuse").data, result.data)
    assert len(transport.calls) == before
