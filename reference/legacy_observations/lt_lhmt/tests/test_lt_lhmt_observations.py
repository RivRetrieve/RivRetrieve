from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars as pl

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.lt_lhmt.observation_client import (
    LtLhmtObservationClient,
    LtLhmtTransportRequest,
    LtLhmtTransportResponse,
)
from rivretrieve._internal.providers.lt_lhmt.retrieval import retrieve_observations

FIXTURE_PATH = Path(__file__).parent / "test_data" / "lithuania_anyksciu_vms_2023_06.json"
STATION_ID = "anyksciu-vms"


def _make_client(responses: dict[str, bytes]) -> LtLhmtObservationClient:
    def transport(request: LtLhmtTransportRequest) -> LtLhmtTransportResponse:
        content = responses.get(request.url, b'{"observations":[]}')
        return LtLhmtTransportResponse(
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC),
        )

    return LtLhmtObservationClient(transport=transport)


def _jun23_url(station_id: str) -> str:
    return f"https://api.meteo.lt/v1/hydro-stations/{station_id}/observations/historical/2023-06"


def test_lt_lhmt_discharge_observations_fixture_backed() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    client = _make_client({_jun23_url(STATION_ID): fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="lt_lhmt",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-06-01"),
        end=pd.Timestamp("2023-06-30"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert not result.data.is_empty()
    assert set(result.data.columns) == {"time", "station_id", "product_id", "value"}
    assert result.data["product_id"].unique().to_list() == ["discharge_daily_mean"]
    assert result.data["station_id"].unique().to_list() == [STATION_ID]
    assert result.data["time"].dtype == pl.Datetime(time_unit="us", time_zone="UTC")
    assert result.data["value"].min() > 0


def test_lt_lhmt_stage_unit_conversion_fixture_backed() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    client = _make_client({_jun23_url(STATION_ID): fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="lt_lhmt",
        stations=STATION_ID,
        products="stage_daily_mean",
        start=pd.Timestamp("2023-06-01"),
        end=pd.Timestamp("2023-06-30"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert not result.data.is_empty()
    raw = json.loads(fixture_content)
    raw_stage_values = [o["waterLevel"] for o in raw["observations"] if "waterLevel" in o]
    expected_sorted = sorted(v / 100.0 for v in raw_stage_values)
    actual_sorted = sorted(result.data["value"].to_list())
    for a, e in zip(actual_sorted, expected_sorted, strict=True):
        assert abs(a - e) < 1e-9, f"stage conversion failed: {a} != {e}"


def test_lt_lhmt_observations_data_time_is_utc() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    client = _make_client({_jun23_url(STATION_ID): fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="lt_lhmt",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-06-01"),
        end=pd.Timestamp("2023-06-30"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert result.data["time"].dtype == pl.Datetime(time_unit="us", time_zone="UTC")
    for t in result.data["time"].to_list():
        assert t.tzinfo is not None or result.data["time"].dtype.time_zone == "UTC"


def test_lt_lhmt_series_annotation_resolved_timezone() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    client = _make_client({_jun23_url(STATION_ID): fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="lt_lhmt",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-06-01"),
        end=pd.Timestamp("2023-06-30"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    ann = result.series_annotations.data
    tz_row = ann.filter(pl.col("annotation") == "resolved_timezone")
    assert tz_row.height >= 1
    assert tz_row["value"].to_list()[0] == "UTC"


def test_lt_lhmt_series_annotation_date_only_flag() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    client = _make_client({_jun23_url(STATION_ID): fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="lt_lhmt",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-06-01"),
        end=pd.Timestamp("2023-06-30"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    ann = result.series_annotations.data
    flag_row = ann.filter(pl.col("annotation") == "date_only_timestamp_flag")
    assert flag_row.height >= 1
    assert flag_row["value"].to_list()[0] == "true"


def test_lt_lhmt_bulk_two_products_fixture_backed() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    client = _make_client({_jun23_url(STATION_ID): fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="lt_lhmt",
        stations=STATION_ID,
        products=["discharge_daily_mean", "stage_daily_mean"],
        start=pd.Timestamp("2023-06-01"),
        end=pd.Timestamp("2023-06-30"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    product_ids = set(result.data["product_id"].to_list())
    assert "discharge_daily_mean" in product_ids
    assert "stage_daily_mean" in product_ids


def test_lt_lhmt_empty_response_returns_issue() -> None:
    client = _make_client({})

    request = ObservationRequest.from_inputs(
        provider_id="lt_lhmt",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-06-01"),
        end=pd.Timestamp("2023-06-30"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert result.data.is_empty()
    assert len(result.issues) >= 1


def test_lt_lhmt_provenance_fields() -> None:
    fixture_content = FIXTURE_PATH.read_bytes()
    client = _make_client({_jun23_url(STATION_ID): fixture_content})

    request = ObservationRequest.from_inputs(
        provider_id="lt_lhmt",
        stations=STATION_ID,
        products="discharge_daily_mean",
        start=pd.Timestamp("2023-06-01"),
        end=pd.Timestamp("2023-06-30"),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=lambda: client)

    assert result.provenance.provider_id == "lt_lhmt"
    assert result.provenance.source == "live"
    assert "lt_lhmt" in str(result.provenance.endpoints) or len(result.provenance.endpoints) >= 1
