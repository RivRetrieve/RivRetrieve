from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.engine import StopConvention, WindowDeclaration, WindowGranularity, WindowRenderingVocabulary
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    RawPayload,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.usgs_nwis import fetch as fetch_module
from rivretrieve._internal.providers.usgs_nwis import module as usgs_nwis_module
from rivretrieve._internal.providers.usgs_nwis.issue_codes import UsgsNwisObservationIssueCodes
from rivretrieve._internal.transport import TransportRequest, TransportResponse

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json")
INSTANT_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_iv_00060_2023-01-01.json")
ARIZONA_INSTANT_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_09380000_iv_00060_2020-07-01.json")


class RecordingHttpClient:
    def __init__(self, response: TransportResponse) -> None:
        self.response = response
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return self.response


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    status_code: int = 200,
) -> RecordingHttpClient:
    client = RecordingHttpClient(
        TransportResponse(
            content=content,
            status_code=status_code,
            retrieved_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(fetch_module, "HttpClient", lambda: client)
    return client


def _assert_result_shape(result) -> None:
    assert tuple(type(result).model_fields) == ("data", "provenance", "issues", "raw")


def test_usgs_nwis_registry_dispatch_uses_engine_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_client(monkeypatch, FIXTURE_PATH.read_bytes())

    result = rr.provider("usgs_nwis").observations(
        stations="07374000",
        products="discharge_daily_mean",
        start="2023-01-01",
        end="2023-01-01",
        on_issue="ignore",
    )

    expected = pl.DataFrame(
        {
            "time": [datetime(2023, 1, 1)],
            "time_zone": ["-06:00"],
            "station_id": ["07374000"],
            "product_id": ["discharge_daily_mean"],
            "value": [10562.183778816001],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.data, expected, check_exact=True)
    assert result.provenance.source == "live"
    assert result.provenance.provider_id == ProviderId("usgs_nwis")
    assert result.raw == RawPayload(provider_id=ProviderId("usgs_nwis"))
    _assert_result_shape(result)
    params = client.requests[0].params
    assert params is not None
    assert params["startDT"] == "2022-12-30"
    assert params["endDT"] == "2023-01-03"
    assert usgs_nwis_module.window_declarations.products[ProductId("discharge_daily_mean")] == WindowDeclaration(
        WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE
    )


def test_usgs_nwis_bare_date_returns_full_local_day_for_instant_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use a constructed, source-shaped fixture with synthetic queryURL, criteria, station metadata, and values—not a captured USGS response."""
    client = _patch_client(monkeypatch, INSTANT_FIXTURE_PATH.read_bytes())

    result = rr.provider("usgs_nwis").observations(
        stations="07374000",
        products="discharge_instantaneous",
        start="2023-01-01",
        end="2023-01-01",
        on_issue="ignore",
    )

    expected = pl.DataFrame(
        {
            "time": [datetime(2023, 1, 1) + timedelta(minutes=15 * index) for index in range(96)],
            "time_zone": ["-06:00"] * 96,
            "station_id": ["07374000"] * 96,
            "product_id": ["discharge_instantaneous"] * 96,
            "value": [source_value * 0.028316846592 for source_value in range(373000, 382501, 100)],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.data, expected, check_exact=True)
    assert result.data["time_zone"].null_count() == 0
    assert "unknown" not in result.data["time_zone"].to_list()
    assert result.issues == ()
    assert result.provenance.source == "live"
    assert result.provenance.provider_id == ProviderId("usgs_nwis")
    assert result.raw == RawPayload(provider_id=ProviderId("usgs_nwis"))
    _assert_result_shape(result)

    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.url == "https://waterservices.usgs.gov/nwis/iv/"
    assert request.params == {
        "format": "json",
        "sites": "07374000",
        "startDT": "2022-12-30",
        "endDT": "2023-01-03",
        "parameterCd": "00060",
    }
    assert request.headers == {"Accept": "application/json"}


def test_usgs_nwis_arizona_explicit_local_day_returns_24_hourly_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use a constructed, source-shaped fixture with synthetic queryURL, criteria, station metadata, and values—not a captured USGS response."""
    client = _patch_client(monkeypatch, ARIZONA_INSTANT_FIXTURE_PATH.read_bytes())

    result = rr.provider("usgs_nwis").observations(
        stations="09380000",
        products="discharge_instantaneous",
        start="2020-07-01 00:00",
        end="2020-07-01 23:00",
        on_issue="ignore",
    )

    expected_times = [datetime(2020, 7, 1, hour) for hour in range(24)]
    assert result.data.height == 24
    assert result.data["time"].to_list() == expected_times
    assert result.data["time"][0] == datetime(2020, 7, 1, 0, 0)
    assert result.data["time"][-1] == datetime(2020, 7, 1, 23, 0)
    assert result.data["station_id"].unique(maintain_order=True).to_list() == ["09380000"]
    assert result.data["product_id"].unique(maintain_order=True).to_list() == ["discharge_instantaneous"]

    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.url == "https://waterservices.usgs.gov/nwis/iv/"
    assert request.params == {
        "format": "json",
        "sites": "09380000",
        "startDT": "2020-06-29",
        "endDT": "2020-07-03",
        "parameterCd": "00060",
    }
    assert request.headers == {"Accept": "application/json"}


def test_usgs_nwis_all_missing_preserves_issue_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, b"not found", status_code=404)

    result = rr.provider("usgs_nwis").observations(
        stations="07374000",
        products="discharge_daily_mean",
        start="2023-01-01",
        end="2023-01-01",
        on_issue="ignore",
    )

    pl_testing.assert_frame_equal(
        result.data,
        pl.DataFrame(schema=ObservationDataSchema.polars_schema),
        check_exact=True,
    )
    assert [issue.code for issue in result.issues] == [str(UsgsNwisObservationIssueCodes.HTTP_NOT_FOUND)]
    _assert_result_shape(result)

    with pytest.raises(IssuePolicyError):
        rr.provider("usgs_nwis").observations(
            stations="07374000",
            products="discharge_daily_mean",
            start="2023-01-01",
            end="2023-01-01",
            on_issue="raise",
        )
