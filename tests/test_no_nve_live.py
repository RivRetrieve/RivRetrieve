"""Norway live adapter proofs over the recorded credentialed HydAPI responses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import cast

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.discovery import EmptySelectionError
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    RenderedWindow,
    RequestedWindow,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.observations import ObservationRequest as PublicObservationRequest
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates, config
from rivretrieve._internal.providers.no_nve.declaration import declaration
from rivretrieve._internal.providers.no_nve.fetch import fetch
from rivretrieve._internal.providers.no_nve.parse import parse
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader

_PROVIDER = ProviderId("no_nve")
_STATION = "1.200.0"
_DATA = Path(__file__).parent / "test_data"
_URL = "https://hydapi.nve.no/api/v1/Observations"
_SENTINEL = "SENTINEL-NOT-A-REAL-KEY"
_PRODUCTS = tuple(config().products)
_RECORDED_WINDOW = RenderedWindow("2025-07-08T00:00:00Z", "2025-07-14T00:00:00Z")

assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages


def _recording_path(station_id: str, product_id: ProductId, window: str) -> Path:
    coordinates = config().products[product_id].coordinates.value
    assert isinstance(coordinates, NoNveSourceCoordinates)
    name = f"no_nve_{station_id}_{coordinates.parameter}_{coordinates.resolution_time}_{window}.recording.json"
    return _DATA / name


def _recording(product_id: ProductId):
    return read_recording(_recording_path(_STATION, product_id, "2025-07-08_2025-07-14"))


def _credentialed(*recordings) -> AuthenticatedTransport:
    return AuthenticatedTransport(
        ReplayTransport(recordings),
        (CredentialHeader("X-API-Key", _SENTINEL, ("https://hydapi.nve.no",)),),
    )


def _fetch_window(start: str, end: str):
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
    )


def _requested_window() -> RequestedWindow:
    return RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime(2025, 7, 10)),
        end=WindowEndpoint.from_datetime(datetime(2025, 7, 12)),
    )


def _drive(transport, receipts: ReceiptMode = ReceiptMode.OMIT):
    return drive(
        ObservationRequest(
            provider_id=_PROVIDER,
            stations=(_STATION,),
            products=_PRODUCTS,
            window=_requested_window(),
        ),
        _STAGES,
        provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
        receipts=receipts,
        transport=transport,
    )


def test_the_engine_padded_window_renders_the_exact_recorded_reference_time() -> None:
    result = _drive(_credentialed(*(_recording(product) for product in _PRODUCTS)))

    counts = dict(result.canonical_rows.group_by("product_id").len().sort("product_id").rows())
    assert counts == {
        "discharge_daily_mean": 3,
        "discharge_hourly_mean": 49,
        "discharge_instantaneous": 49,
        "stage_daily_mean": 3,
        "stage_hourly_mean": 49,
        "stage_instantaneous": 49,
        "water_temperature_daily_mean": 3,
        "water_temperature_hourly_mean": 49,
        "water_temperature_instantaneous": 49,
    }
    daily = result.canonical_rows.filter(pl.col("product_id") == "stage_daily_mean")
    assert daily["time"].min() == datetime(2025, 7, 10, 11)
    assert daily["time"].max() == datetime(2025, 7, 12, 11)
    hourly = result.canonical_rows.filter(pl.col("product_id") == "stage_hourly_mean")
    assert hourly["time"].min() == datetime(2025, 7, 10)
    assert hourly["time"].max() == datetime(2025, 7, 12)
    assert set(result.canonical_rows["time_zone"].unique().to_list()) == {"+00:00"}


def test_receipts_carry_the_exact_recorded_bytes_for_every_product() -> None:
    result = _drive(
        _credentialed(*(_recording(product) for product in _PRODUCTS)),
        receipts=ReceiptMode.INCLUDE,
    )

    recorded = {_recording(product).content for product in _PRODUCTS}
    assert {entry.content for entry in result.receipts.entries} == recorded
    assert len(result.receipts.entries) == len(_PRODUCTS)


def test_provenance_is_complete_and_names_no_credential() -> None:
    result = _drive(_credentialed(*(_recording(product) for product in _PRODUCTS)))

    assert result.provenance.endpoints == (_URL,)
    assert len(result.provenance.calls_made) == len(_PRODUCTS)
    assert result.provenance.retrieved_at == max(_recording(product).retrieved_at for product in _PRODUCTS)
    for call in result.provenance.calls_made:
        assert set(call) == {
            "url",
            "request_parameters",
            "status_code",
            "retrieved_at",
            "content_type",
            "source_path",
            "query",
        }
    public_json = result.provenance.model_dump_json()
    assert _SENTINEL not in public_json
    assert "api-key" not in public_json.lower()
    assert "header" not in public_json.lower()


def test_the_credential_header_name_survives_only_as_recorded_evidence() -> None:
    for product in _PRODUCTS:
        document = json.loads(_recording_path(_STATION, product, "2025-07-08_2025-07-14").read_text(encoding="utf-8"))
        assert document["request"]["credential_header_names"] == ["X-API-Key"]
        assert "X-API-Key" not in document["request"]["ordinary_headers"]
        remainder = dict(document)
        remainder["request"] = {
            key: value for key, value in document["request"].items() if key != "credential_header_names"
        }
        assert "X-API-Key" not in json.dumps(remainder)


def test_one_request_per_station_product_window_carries_its_exact_parameters() -> None:
    product = ProductId("discharge_hourly_mean")
    replay = _credentialed(_recording(product))
    result = fetch(
        (_STATION,),
        (product,),
        MappingProxyType({product: (_RECORDED_WINDOW,)}),
        _fetch_window("2025-07-08T00:00:00", "2025-07-14T00:00:00"),
        config(),
        replay,
    )

    (payload,) = result.value
    assert result.issues == ()
    assert payload.station_products == ((_STATION, product),)
    assert not isinstance(payload.origin.request_parameters, UnknownOriginFact)
    assert dict(payload.origin.request_parameters) == {
        "StationId": _STATION,
        "Parameter": "1001",
        "ResolutionTime": "60",
        "ReferenceTime": "2025-07-08T00:00:00Z/2025-07-14T00:00:00Z",
    }
    assert payload.origin.url == _URL


def test_source_quality_and_correction_codes_are_surfaced_without_interpretation() -> None:
    product = ProductId("water_temperature_daily_mean")
    replay = _credentialed(_recording(product))
    (payload,) = fetch(
        (_STATION,),
        (product,),
        MappingProxyType({product: (_RECORDED_WINDOW,)}),
        _fetch_window("2025-07-08T00:00:00", "2025-07-14T00:00:00"),
        config(),
        replay,
    ).value
    parsed = parse(payload, config())

    assert parsed.value.height == 6
    assert {issue.code for issue in parsed.issues} == {"source_quality_code", "source_correction_code"}
    assert {issue.severity for issue in parsed.issues} == {"info"}
    quality = next(issue for issue in parsed.issues if issue.code == "source_quality_code")
    assert quality.details is not None
    assert quality.details["source_quality_code"] == 1
    assert quality.details["count"] == 6


def test_a_missing_series_becomes_an_engine_warning_and_no_rows() -> None:
    product = ProductId("water_temperature_daily_mean")
    station = "12.210.0"
    recording = read_recording(_recording_path(station, product, "2025-07-08_2025-07-14"))
    assert recording.status_code == 404
    result = drive(
        ObservationRequest(
            provider_id=_PROVIDER,
            stations=(station,),
            products=(product,),
            window=RequestedWindow(
                start=WindowEndpoint.from_datetime(datetime(2025, 7, 10)),
                end=WindowEndpoint.from_datetime(datetime(2025, 7, 12)),
            ),
        ),
        _STAGES,
        provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
        transport=_credentialed(recording),
    )

    assert result.canonical_rows.is_empty()
    (issue,) = result.issues
    assert issue.code == "source.http_not_found"
    assert issue.severity == "warning"
    assert issue.details is not None
    assert issue.details["station_id"] == station


def test_an_empty_series_parses_to_no_rows_and_one_missing_data_issue() -> None:
    product = ProductId("stage_daily_mean")
    recording = read_recording(_recording_path(_STATION, product, "1900-01-01_1900-01-07"))
    window = RenderedWindow("1900-01-01T00:00:00Z", "1900-01-07T00:00:00Z")
    (payload,) = fetch(
        (_STATION,),
        (product,),
        MappingProxyType({product: (window,)}),
        _fetch_window("1900-01-01T00:00:00", "1900-01-07T00:00:00"),
        config(),
        _credentialed(recording),
    ).value
    parsed = parse(payload, config())

    assert parsed.value.is_empty()
    (issue,) = parsed.issues
    assert issue.code == "missing_data"
    assert issue.severity == "warning"


def test_norway_stays_publicly_unselectable_until_its_catalogue_is_certified() -> None:
    assert _PROVIDER in rr.providers().get_column("provider_id").to_list()
    selection = rr.find(provider=_PROVIDER)
    assert selection.series == ()
    with pytest.raises(EmptySelectionError) as error:
        rr.fetch(selection, start="2025-07-10", end="2025-07-12")
    assert "no_nve" in str(error.value)


def test_a_bare_date_public_request_renders_an_end_of_day_instant_the_source_accepts() -> None:
    product = ProductId("stage_daily_mean")
    recording = read_recording(_recording_path(_STATION, product, "2025-07-08_2025-07-14-eod"))
    public = PublicObservationRequest.from_inputs(
        provider_id=_PROVIDER, stations=(_STATION,), products=(product,), start="2025-07-10", end="2025-07-12"
    )
    result = drive(
        ObservationRequest(
            provider_id=_PROVIDER,
            stations=(_STATION,),
            products=(product,),
            window=RequestedWindow(start=public.start, end=public.end),
        ),
        _STAGES,
        provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
        transport=_credentialed(recording),
    )

    (call,) = result.provenance.calls_made
    parameters = cast("Mapping[str, object]", call["request_parameters"])
    assert parameters["ReferenceTime"] == "2025-07-08T00:00:00Z/2025-07-14T23:59:59.999999Z"
    assert call["status_code"] == 200
    assert result.canonical_rows["time"].to_list() == [
        datetime(2025, 7, 10, 11),
        datetime(2025, 7, 11, 11),
        datetime(2025, 7, 12, 11),
    ]


def _parsed(product: ProductId, station: str, window_name: str, window: RenderedWindow, start: str, end: str):
    recording = read_recording(_recording_path(station, product, window_name))
    (payload,) = fetch(
        (station,),
        (product,),
        MappingProxyType({product: (window,)}),
        _fetch_window(start, end),
        config(),
        _credentialed(recording),
    ).value
    return payload, parse(payload, config())


def test_the_recorded_stop_convention_is_inclusive_on_the_instant_axis() -> None:
    product = ProductId("stage_daily_mean")
    _, midnight_end = _parsed(
        product,
        _STATION,
        "2023-03-23_2023-03-27",
        RenderedWindow("2023-03-23T00:00:00Z", "2023-03-27T00:00:00Z"),
        "2023-03-23T00:00:00",
        "2023-03-27T00:00:00",
    )
    _, end_of_day = _parsed(
        product,
        _STATION,
        "2023-03-23_2023-03-27-eod",
        RenderedWindow("2023-03-23T00:00:00Z", "2023-03-27T23:59:59.999999Z"),
        "2023-03-23T00:00:00",
        "2023-03-27T23:59:59.999999",
    )

    assert midnight_end.value["time"].to_list()[-1] == datetime(2023, 3, 26, 11)
    assert midnight_end.value.height == 4
    assert end_of_day.value["time"].to_list()[-1] == datetime(2023, 3, 27, 11)
    assert end_of_day.value.height == 5


def test_a_published_null_value_is_carried_as_a_null_reading() -> None:
    product = ProductId("stage_daily_mean")
    _, parsed = _parsed(
        product,
        _STATION,
        "2023-03-23_2023-03-27",
        RenderedWindow("2023-03-23T00:00:00Z", "2023-03-27T00:00:00Z"),
        "2023-03-23T00:00:00",
        "2023-03-27T00:00:00",
    )

    assert parsed.value.height == 4
    assert parsed.value["value"].null_count() == 4
    quality = next(issue for issue in parsed.issues if issue.code == "source_quality_code")
    assert quality.details is not None
    assert quality.details["source_quality_code"] == 2
    assert quality.details["count"] == 4


def test_a_series_whose_published_method_differs_from_the_product_is_refused() -> None:
    product = ProductId("water_temperature_hourly_mean")
    recording = read_recording(_recording_path("103.3.0", product, "2025-07-08_2025-07-14"))
    (payload,) = fetch(
        ("103.3.0",),
        (product,),
        MappingProxyType({product: (_RECORDED_WINDOW,)}),
        _fetch_window("2025-07-08T00:00:00", "2025-07-14T00:00:00"),
        config(),
        _credentialed(recording),
    ).value

    with pytest.raises(FatalContractError, match="method differs"):
        parse(payload, config())


def test_a_series_whose_published_unit_differs_from_the_declared_unit_is_refused() -> None:
    product = ProductId("stage_daily_mean")
    payload, _ = _parsed(
        product,
        _STATION,
        "2025-07-08_2025-07-14",
        _RECORDED_WINDOW,
        "2025-07-08T00:00:00",
        "2025-07-14T00:00:00",
    )
    # Mutated copy of the committed body: the published unit is rewritten from "m" to "cm".
    assert b'"unit":"m"' in payload.content
    mutated = replace(payload, content=payload.content.replace(b'"unit":"m"', b'"unit":"cm"', 1))

    with pytest.raises(FatalContractError, match="unit differs"):
        parse(mutated, config())
