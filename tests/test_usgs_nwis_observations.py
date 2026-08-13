from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest
from pydantic import BaseModel

import rivretrieve as rr
from rivretrieve._internal.engine import (
    StopConvention,
    UnknownOriginFact,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
)
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    RawMode,
    RawPayload,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.usgs_nwis import fetch as fetch_module
from rivretrieve._internal.providers.usgs_nwis import module as usgs_nwis_module
from rivretrieve._internal.providers.usgs_nwis.issue_codes import UsgsNwisObservationIssueCodes
from rivretrieve._internal.registry import _registry
from rivretrieve._internal.transport import TransportRequest, TransportResponse

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json")
INSTANT_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_iv_00060_2023-01-01.json")
ARIZONA_INSTANT_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_09380000_iv_00060_2020-07-01.json")


class RecordingHttpClient:
    def __init__(self, content: bytes, status_code: int) -> None:
        self.content = content
        self.status_code = status_code
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return TransportResponse(
            content=self.content,
            status_code=self.status_code,
            retrieved_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            content_type=("text/plain" if self.status_code == 404 else "application/json; charset=utf-8"),
            url=request.url,
            request_parameters={} if request.params is None else request.params,
        )


class SequentialRecordingHttpClient:
    def __init__(self, response_bodies: tuple[bytes, ...]) -> None:
        self.response_bodies = response_bodies
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        content = self.response_bodies[len(self.requests)]
        self.requests.append(request)
        return TransportResponse(
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            content_type="application/json; charset=utf-8",
            url=request.url,
            request_parameters={} if request.params is None else request.params,
        )


def _normalize_for_secret_search(value: object) -> object:
    if isinstance(value, UnknownOriginFact):
        return {"unknown": True}
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="python")
        return {name: _normalize_for_secret_search(dumped[name]) for name in type(value).model_fields}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _normalize_for_secret_search(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _normalize_for_secret_search(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_normalize_for_secret_search(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("latin-1")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


def _serialized_contains_token(value: object, token: str) -> bool:
    normalized = _normalize_for_secret_search(value)
    serialized = json.dumps(normalized, ensure_ascii=False).encode("utf-8")
    return token.encode("utf-8") in serialized


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    status_code: int = 200,
) -> RecordingHttpClient:
    client = RecordingHttpClient(content, status_code)
    monkeypatch.setattr(fetch_module, "HttpClient", lambda: client)
    return client


def _assert_result_shape(result) -> None:
    assert tuple(type(result).model_fields) == ("data", "provenance", "issues", "raw")


def test_usgs_nwis_registry_dispatch_uses_engine_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_client(monkeypatch, FIXTURE_PATH.read_bytes())

    rr.providers()
    result = _registry.get("usgs_nwis").observations(
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
    assert result.raw == RawPayload(provider_id=ProviderId("usgs_nwis"), entries=())
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

    rr.providers()
    result = _registry.get("usgs_nwis").observations(
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
    assert [issue.code for issue in result.issues] == [
        "provenance.license_not_established",
        "provenance.citation_not_established",
    ]
    assert result.provenance.source == "live"
    assert result.provenance.provider_id == ProviderId("usgs_nwis")
    assert result.raw == RawPayload(provider_id=ProviderId("usgs_nwis"), entries=())
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

    rr.providers()
    result = _registry.get("usgs_nwis").observations(
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


def test_usgs_nwis_include_retains_ordered_http_receipts_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    response_bodies = (fixture_bytes + b" ", fixture_bytes + b"\n")
    client = SequentialRecordingHttpClient(response_bodies)
    token = "RIVRETRIEVE_TEST_SECRET_7A91"
    real_request = fetch_module._request
    real_parse = usgs_nwis_module.parse
    parse_contents: list[bytes] = []

    def authenticated_request(*args: object, **kwargs: object) -> TransportRequest:
        request = real_request(*args, **kwargs)
        return TransportRequest(
            method=request.method,
            url=request.url,
            params=request.params,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer RIVRETRIEVE_TEST_SECRET_7A91",
            },
            body=request.body,
        )

    def recording_parse(payload, config):
        parse_contents.append(payload.content)
        return real_parse(payload, config)

    monkeypatch.setattr(fetch_module, "HttpClient", lambda: client)
    monkeypatch.setattr(fetch_module, "_request", authenticated_request)
    monkeypatch.setattr(usgs_nwis_module, "parse", recording_parse)

    rr.providers()
    result = _registry.get("usgs_nwis").observations(
        stations=["07374000", "07374000"],
        products="discharge_daily_mean",
        start="2023-01-01",
        end="2023-01-01",
        on_issue="ignore",
        raw=RawMode.INCLUDE,
    )

    expected_parameters = {
        "format": "json",
        "sites": "07374000",
        "startDT": "2022-12-30",
        "endDT": "2023-01-03",
        "parameterCd": "00060",
        "statCd": "00003",
    }
    assert len(result.raw.entries) == 2
    assert tuple(entry.content for entry in result.raw.entries) == response_bodies
    assert tuple(parse_contents) == response_bodies
    for entry, parse_content in zip(result.raw.entries, parse_contents, strict=True):
        assert entry.content is parse_content
        assert entry.origin.url == "https://waterservices.usgs.gov/nwis/dv/"
        assert entry.origin.request_parameters == expected_parameters
        assert entry.origin.status_code == 200
        assert entry.origin.retrieved_at == datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        assert entry.origin.content_type == "application/json; charset=utf-8"
        assert isinstance(entry.origin.source_path, UnknownOriginFact)
        assert isinstance(entry.origin.query, UnknownOriginFact)
    assert [request.headers for request in client.requests] == [
        {
            "Accept": "application/json",
            "Authorization": "Bearer RIVRETRIEVE_TEST_SECRET_7A91",
        },
        {
            "Accept": "application/json",
            "Authorization": "Bearer RIVRETRIEVE_TEST_SECRET_7A91",
        },
    ]
    positive_raw = replace(result.raw.entries[0], content=token.encode("utf-8"))
    assert _serialized_contains_token(positive_raw, token)
    positive_calls_made = (
        {
            "url": "https://waterservices.usgs.gov/nwis/dv/",
            "authorization": "Bearer RIVRETRIEVE_TEST_SECRET_7A91",
        },
    )
    positive_provenance = result.provenance.model_copy(update={"calls_made": positive_calls_made})
    assert _serialized_contains_token(positive_provenance, token)
    assert not _serialized_contains_token((result.raw.entries, result.provenance), token)
    assert tuple(type(result.provenance).model_fields) == (
        "source",
        "provider_id",
        "rivretrieve_version",
        "catalogue_version",
        "license",
        "citation",
        "requested_at",
        "retrieved_at",
        "request",
        "calls_made",
        "time_windows",
        "decomposition",
        "endpoints",
        "query",
        "response_version",
        "metadata",
        "source_vintage",
        "publisher_artifact_checksum",
    )
    assert result.provenance.request == {
        "stations": ["07374000", "07374000"],
        "products": ["discharge_daily_mean"],
        "start": "2023-01-01T00:00:00",
        "end": "2023-01-01T23:59:59.999999",
    }


def test_usgs_nwis_all_missing_preserves_issue_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, b"not found", status_code=404)

    rr.providers()
    result = _registry.get("usgs_nwis").observations(
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
    assert [issue.code for issue in result.issues] == [
        str(UsgsNwisObservationIssueCodes.HTTP_NOT_FOUND),
        "provenance.license_not_established",
        "provenance.citation_not_established",
    ]
    _assert_result_shape(result)

    with pytest.raises(IssuePolicyError):
        rr.providers()
        _registry.get("usgs_nwis").observations(
            stations="07374000",
            products="discharge_daily_mean",
            start="2023-01-01",
            end="2023-01-01",
            on_issue="raise",
        )
