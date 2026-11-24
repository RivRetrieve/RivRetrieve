"""Step 6 verification replay of Ireland OPW (`ie_opw`) EStreams 10-gauge sample, deep reach, and cache audit."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.providers.ie_opw.annotations import IE_OPW_SERIES_SCHEMA
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_ie_opw_recorded_public import _select_products
from tests.test_ie_opw_retrieval_recorded import _envelope_from_capture

_SCOPE = "maintenance/observations/ie_opw/retrieval"

_VERIFICATION_SLUGS: tuple[tuple[str, str, int, datetime, datetime], ...] = (
    ("14009", "estreams-01-14009-q-year-json", 14427, datetime(1980, 1, 1), datetime(2025, 11, 17)),
    ("06013", "estreams-02-06013-q-year-json", 18322, datetime(1975, 10, 29), datetime(2026, 11, 23)),
    ("19109", "estreams-03-19109-q-year-json", 2218, datetime(2020, 7, 6), datetime(2026, 8, 5)),
    ("18117", "estreams-04-18117-q-year-json", 6765, datetime(2007, 9, 13), datetime(2026, 7, 3)),
    ("18003", "estreams-05-18003-q-year-json", 19261, datetime(1972, 1, 1), datetime(2026, 9, 1)),
    ("15001", "estreams-06-15001-q-year-json", 19197, datetime(1972, 1, 1), datetime(2026, 3, 14)),
    ("14006", "estreams-07-14006-q-year-json", 19346, datetime(1972, 1, 1), datetime(2026, 5, 21)),
    ("35011", "estreams-08-35011-q-year-json", 23291, datetime(1957, 10, 9), datetime(2026, 11, 23)),
    ("12001", "estreams-09-12001-q-year-json", 24967, datetime(1955, 9, 5), datetime(2026, 7, 13)),
    ("26021", "estreams-10-26021-q-year-json", 18850, datetime(1972, 10, 1), datetime(2026, 11, 23)),
    ("07012", "deep-01-07012-q-year-json", 31271, datetime(1940, 6, 27), datetime(2026, 8, 11)),
    ("06025", "deep-02-06025-q-year-json", 2094, datetime(1972, 1, 10), datetime(2004, 12, 31)),
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


class _ForbidSendTransport:
    def send(self, request: TransportRequest) -> TransportResponse:
        raise AssertionError(f"cache reuse must not send HTTP requests: {request.url}")


@pytest.mark.recorded(_SCOPE)
def test_recorded_verification_10_estreams_gauges_deep_1940s_and_historic_only(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(
        tuple(
            _envelope_from_capture(retained_evidence_root, slug, subdir="verification/web")
            for _, slug, *_ in _VERIFICATION_SLUGS
        )
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    for station_id, _, expected_rows, min_dt, max_dt in _VERIFICATION_SLUGS:
        sel = _select_products(station_id, "discharge_daily_mean")
        res = rr.fetch(sel, start="1939-01-01", end="2026-11-23", cache="reuse", receipts=True)
        assert res.issues == ()
        assert res.data.height == expected_rows
        assert res.data["unit"].unique().to_list() == ["m3/s"]
        assert res.data["source_unit"].unique().to_list() == ["cumec"]
        assert res.data["time_zone"].unique().to_list() == ["+00:00"]
        assert res.data["time"].min() == min_dt
        assert res.data["time"].max() == max_dt
        assert res.outcomes[0].status is OutcomeStatus.SUCCESS

        if station_id == "06025":
            ann = rr.annotations(res, schema=IE_OPW_SERIES_SCHEMA.schema_id)
            assert ann.filter(pl.col("measured").not_()).height == 17956

    # Offline subset cache reuse over historical 07012 must not touch HttpClient.send().
    monkeypatch.setattr(discovery, "HttpClient", _ForbidSendTransport)
    boyne_1940 = rr.fetch(
        _select_products("07012", "discharge_daily_mean"),
        start="1940-06-27",
        end="1940-12-31",
        cache="reuse",
    )
    assert boyne_1940.data.height == 188
    assert_frame_equal(
        boyne_1940.data,
        rr.fetch(
            _select_products("07012", "discharge_daily_mean"), start="1940-06-27", end="1940-12-31", cache="reuse"
        ).data,
    )
