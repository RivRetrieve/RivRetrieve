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
