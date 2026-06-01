from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars as pl

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.usgs_nwis.observation_client import (
    UsgsNwisObservationClient,
    UsgsNwisTransportRequest,
    UsgsNwisTransportResponse,
)
from rivretrieve._internal.providers.usgs_nwis.retrieval import retrieve_observations

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json")
STATION_ID = "07374000"

_CFS_TO_M3S = 0.0283168466


def _make_client(responses: dict[str, bytes]) -> UsgsNwisObservationClient:
    def transport(request: UsgsNwisTransportRequest) -> UsgsNwisTransportResponse:
        content = responses.get(request.url, b"")
        return UsgsNwisTransportResponse(
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        )

    return UsgsNwisObservationClient(transport=transport)


def _dv_url(station_id: str, start: str, end: str, param: str, stat: str) -> str:
    return (
        f"https://waterservices.usgs.gov/nwis/dv/?format=json"
        f"&sites={station_id}&startDT={start}&endDT={end}"
        f"&parameterCd={param}&statCd={stat}"
    )


def test_usgs_nwis_discharge_observations_fixture_backed() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({url: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert not result.data.is_empty()
    assert set(result.data.columns) == {"time", "station_id", "product_id", "value"}
    assert result.data["product_id"].unique().to_list() == ["discharge_daily_mean"]
    assert result.data["station_id"].unique().to_list() == [STATION_ID]
    assert result.data["time"].dtype == pl.Datetime(time_unit="us", time_zone="UTC")


def test_usgs_nwis_discharge_unit_conversion() -> None:
    """373000 cfs × 0.0283168466 = 10562.18... m3/s"""
    fixture_content = FIXTURE_PATH.read_bytes()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({url: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    first_val = result.data.sort("time")["value"][0]
    expected = 373000.0 * _CFS_TO_M3S
    assert abs(first_val - expected) < 1e-3


def test_usgs_nwis_observations_time_is_utc() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({url: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert result.data["time"].dtype == pl.Datetime(time_unit="us", time_zone="UTC")


def test_usgs_nwis_series_annotation_resolved_timezone() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({url: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    ann = result.series_annotations.data
    tz_row = ann.filter(pl.col("annotation") == "resolved_timezone")
    assert tz_row.height >= 1
    assert tz_row["value"].to_list()[0] == "UTC"


def test_usgs_nwis_series_annotation_timezone_source() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({url: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    ann = result.series_annotations.data
    src_row = ann.filter(pl.col("annotation") == "timezone_source")
    assert src_row.height >= 1
    assert src_row["value"].to_list()[0] == "provider_timestamp_offset"


def test_usgs_nwis_row_annotation_native_field() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({url: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    ann = result.row_annotations.data
    native_field_rows = ann.filter(pl.col("annotation") == "native_field")
    assert native_field_rows.height >= 1
    assert native_field_rows["value"].to_list()[0] == "00060"


def test_usgs_nwis_empty_response_returns_issue() -> None:
    client = _make_client({})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert result.data.is_empty()
    assert len(result.issues) >= 1


def test_usgs_nwis_bulk_two_products() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    dv_url_discharge = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({dv_url_discharge: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products=["discharge_daily_mean", "stage_daily_mean"],
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    product_ids = set(result.data["product_id"].to_list())
    assert "discharge_daily_mean" in product_ids


def test_usgs_nwis_provenance_fields() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({url: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert result.provenance.provider_id == "usgs_nwis"
    assert result.provenance.source == "live"
    assert len(result.provenance.endpoints) >= 1


def test_usgs_nwis_raw_value_annotation_correct() -> None:
    """raw_value annotation should match the pre-conversion cfs value."""
    fixture_content = FIXTURE_PATH.read_bytes()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-10", "00060", "00003")
    client = _make_client({url: fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-10"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    ann = result.row_annotations.data
    raw_rows = ann.filter(pl.col("annotation") == "raw_value")
    assert raw_rows.height >= 1
    first_raw = float(raw_rows["value"][0])
    assert abs(first_raw - 373000.0) < 1e-3


def test_last_day_not_dropped_for_non_utc_station() -> None:
    """Regression: USGS DV timestamps for CST stations land at T06:00Z, not T00:00Z.
    A filter of '<= end_date midnight UTC' drops the entire last day.  The correct
    filter is '< midnight UTC of (end_date + 1 day)'."""
    import json

    # Craft a fixture whose only value is on the last requested day (2023-01-05),
    # timestamp 2023-01-05T00:00:00.000-06:00 → 2023-01-05T06:00:00Z
    single_day = {
        "value": {
            "timeSeries": [
                {
                    "variable": {"noDataValue": -999999.0},
                    "values": [
                        {
                            "value": [
                                {
                                    "value": "100000",
                                    "qualifiers": ["A"],
                                    "dateTime": "2023-01-05T00:00:00.000-06:00",
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    }
    content = json.dumps(single_day).encode()
    url = _dv_url(STATION_ID, "2023-01-01", "2023-01-05", "00060", "00003")
    client = _make_client({url: content})

    request = ObservationRequest.from_inputs(
        provider_id="usgs_nwis",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-01-05"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert not result.data.is_empty(), (
        "Last day dropped: CST midnight (T06:00Z) was excluded by '<= end_date T00:00Z' filter"
    )
    assert result.data.height == 1
    t = result.data["time"][0]
    assert t.hour == 6, f"Expected 06:00Z (CST midnight converted to UTC), got {t}"
