from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    RawPayload,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.usgs_nwis import fetch as fetch_module
from rivretrieve._internal.providers.usgs_nwis.issue_codes import UsgsNwisObservationIssueCodes
from rivretrieve._internal.transport import TransportRequest, TransportResponse

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json")


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


def _assert_empty_annotations(result) -> None:
    pl_testing.assert_frame_equal(
        result.row_annotations.data,
        pl.DataFrame(schema=RowAnnotationTableSchema.polars_schema),
    )
    pl_testing.assert_frame_equal(
        result.series_annotations.data,
        pl.DataFrame(schema=SeriesAnnotationTableSchema.polars_schema),
    )


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
            "station_id": ["07374000"],
            "product_id": ["discharge_daily_mean"],
            "value": [10562.183778816001],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.data, expected)
    assert result.provenance.source == "live"
    assert result.provenance.provider_id == ProviderId("usgs_nwis")
    assert result.raw == RawPayload(provider_id=ProviderId("usgs_nwis"))
    _assert_empty_annotations(result)
    params = client.requests[0].params
    assert params is not None
    assert params["startDT"] == "2023-01-01"
    assert params["endDT"] == "2023-01-01"


def test_usgs_nwis_all_missing_preserves_issue_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, b"not found", status_code=404)

    result = rr.provider("usgs_nwis").observations(
        stations="07374000",
        products="discharge_daily_mean",
        start="2023-01-01",
        end="2023-01-01",
        on_issue="ignore",
    )

    pl_testing.assert_frame_equal(result.data, pl.DataFrame(schema=ObservationDataSchema.polars_schema))
    assert [issue.code for issue in result.issues] == [str(UsgsNwisObservationIssueCodes.HTTP_NOT_FOUND)]
    _assert_empty_annotations(result)

    with pytest.raises(IssuePolicyError):
        rr.provider("usgs_nwis").observations(
            stations="07374000",
            products="discharge_daily_mean",
            start="2023-01-01",
            end="2023-01-01",
            on_issue="raise",
        )
