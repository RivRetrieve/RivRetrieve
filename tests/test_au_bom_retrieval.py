"""Synthetic unit and assembled driver controls for Australia BoM retrieval."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    Payload,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.au_bom.config import (
    SHARED_ACQUISITION_PRODUCTS,
    AuBomTimeseriesListCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.au_bom.declaration import declaration
from rivretrieve._internal.providers.au_bom.fetch import fetch, resolve_timeseries_list
from rivretrieve._internal.providers.au_bom.parse import parse
from rivretrieve._internal.providers.registration import CatalogueOnly
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_DISCHARGE_DAILY = ProductId("discharge_daily_mean_24hr")
_STAGE_DAILY = ProductId("stage_daily_mean")


@dataclass(frozen=True)
class _AuBomStages:
    """Internal stage bundle for exercising BoM retrieval while declaration stays CatalogueOnly."""

    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    shared_acquisition_products: tuple[frozenset[ProductId], ...] = SHARED_ACQUISITION_PRODUCTS
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _origin(
    url: str = "https://www.bom.gov.au/waterdata/services", params: dict[str, str] | None = None
) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters=params or {},
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def _list_json(station: str, rows: list[tuple[str, str, str, str]]) -> bytes:
    header = ["ts_id", "ts_name", "parametertype_name", "ts_unitsymbol", "station_no"]
    return json.dumps(
        [header, *[[ts_id, ts_name, param, unit, station] for ts_id, ts_name, param, unit in rows]]
    ).encode("utf-8")


def _values_json(blocks: list[tuple[str, list[tuple[str, float | None, int | None, str | None]]]]) -> bytes:
    columns = "Timestamp,Value,Quality Code,Quality Code Name"
    return json.dumps(
        [
            {
                "ts_id": ts_id,
                "rows": str(len(rows)),
                "columns": columns,
                "data": [[label, value, code, name] for label, value, code, name in rows],
            }
            for ts_id, rows in blocks
        ]
    ).encode("utf-8")


def _rendered_windows(fetch_win, product: ProductId):
    from rivretrieve._internal.window_planning import plan_windows

    decl = window_declarations().products[product]
    return {product: plan_windows(fetch_win, decl)}


def test_config_declares_18_products_with_iso_instant_shared_acquisition() -> None:
    assert isinstance(declaration.observations, CatalogueOnly)
    cfg = config()
    decls = window_declarations()
    assert len(cfg.products) == 18
    assert set(decls.products) == set(cfg.products)
    for decl in decls.products.values():
        assert decl.granularity == WindowGranularity("iso-instant")
        assert decl.rendering == WindowRenderingVocabulary.ISO_INSTANT
        assert decl.stop_convention == StopConvention.INCLUSIVE
    assert cfg.products[_DISCHARGE_DAILY].unit == Unit.M3_S
    assert cfg.products[_STAGE_DAILY].unit == Unit.M
    assert len(SHARED_ACQUISITION_PRODUCTS) == 1
    assert SHARED_ACQUISITION_PRODUCTS[0] == frozenset(cfg.products)


def test_resolve_timeseries_list_disambiguates_a_shared_ts_name_by_parametertype_name() -> None:
    """Confirmed live, 2026-11-03: station 410730's DailyMean.24HR ts_name is shared

    by discharge, stage, pH, turbidity, conductivity and water temperature alike.
    """
    content = _list_json(
        "138020A",
        [
            ("470345010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec"),
            ("381776010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec"),
            ("1598010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m"),
            ("1599010", "DMQaQc.Merged.MonthlyMean.CalMonth", "Water Course Level", "m"),
        ],
    )
    resolved = resolve_timeseries_list(content, "138020A")
    assert resolved[("DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge")] == (
        ("470345010", "cumec"),
        ("381776010", "cumec"),
    )
    assert resolved[("DMQaQc.Merged.DailyMean.24HR", "Water Course Level")] == (("1598010", "m"),)
    assert resolved[("DMQaQc.Merged.MonthlyMean.CalMonth", "Water Course Level")] == (("1599010", "m"),)


def test_resolve_timeseries_list_rejects_station_mismatch() -> None:
    content = _list_json("410730", [("1573010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec")])
    with pytest.raises(UnsupportedSourceStructureError, match="contradicts requested station"):
        resolve_timeseries_list(content, "999999")


def test_fetch_combines_duplicate_ts_ids_into_one_values_call_per_product() -> None:
    station = "138020A"
    list_bytes = _list_json(
        station,
        [
            ("470345010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec"),
            ("381776010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec"),
        ],
    )
    seen: list[tuple[str, dict[str, str]]] = []

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            seen.append((params.get("request", ""), params))
            if params["request"] == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(b"[]", 200, _RETRIEVED_AT, "application/json", request.url, params)

    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 2))
    )
    result = fetch(
        (station,),
        (_DISCHARGE_DAILY,),
        _rendered_windows(fetch_win, _DISCHARGE_DAILY),
        fetch_win,
        config(),
        _Transport(),
    )
    values_calls = [params for kind, params in seen if kind == "getTimeseriesValues"]
    assert len(values_calls) == 1
    assert values_calls[0]["ts_id"] == "470345010,381776010"
    assert result.failed_requests == ()
    assert len(result.value) == 2


def test_fetch_list_failure_produces_one_failed_request_per_product_sharing_call_id() -> None:
    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=500,
                category=TransportFailureCategory.HTTP_STATUS,
            )

    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 2))
    )
    result = fetch(
        ("410730",),
        (_DISCHARGE_DAILY, _STAGE_DAILY),
        {**_rendered_windows(fetch_win, _DISCHARGE_DAILY), **_rendered_windows(fetch_win, _STAGE_DAILY)},
        fetch_win,
        config(),
        _Transport(),
    )
    assert result.value == ()
    assert len(result.failed_requests) == 2
    call_ids = {item.call_id for item in result.failed_requests}
    assert len(call_ids) == 1 and None not in call_ids


def test_fetch_skips_values_call_for_a_product_absent_from_the_list_response() -> None:
    station = "410730"
    list_bytes = _list_json(station, [("1573010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec")])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params["request"] == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            raise AssertionError("no values call should be attempted for an unresolved product")

    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 2))
    )
    result = fetch(
        (station,),
        (_STAGE_DAILY,),
        _rendered_windows(fetch_win, _STAGE_DAILY),
        fetch_win,
        config(),
        _Transport(),
    )
    assert len(result.value) == 1
    assert isinstance(result.value[0].source_coordinates.value, AuBomTimeseriesListCoordinates)


def test_parse_list_prerequisite_emits_no_match_only_for_the_unresolved_product() -> None:
    station = "410730"
    list_bytes = _list_json(station, [("1573010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec")])
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 2))
    )
    payload = Payload(
        SourceCoordinates(AuBomTimeseriesListCoordinates()),
        ((station, _DISCHARGE_DAILY), (station, _STAGE_DAILY)),
        fetch_win,
        list_bytes,
        _origin(),
        (),
    )
    parsed = parse(payload, config())
    assert parsed.rows.is_empty()
    assert parsed.series == ()
    assert len(parsed.outcomes) == 1
    assert parsed.outcomes[0].status is OutcomeStatus.NO_MATCH
    assert parsed.outcomes[0].product_id == str(_STAGE_DAILY)
    assert len(parsed.issues) == 1
    assert parsed.issues[0].code == "source.no_match"


def test_parse_values_builds_rows_preserves_published_null_and_splits_duplicate_ts_ids() -> None:
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 2))
    )
    content = _values_json(
        [
            (
                "470345010",
                [
                    ("2026-09-01T00:00:00.000+10:00", 1.887, 10, "quality-A"),
                    ("2026-09-02T00:00:00.000+10:00", None, 10, "quality-A"),
                ],
            ),
            ("381776010", []),
        ]
    )
    payload = Payload(
        config().products[_DISCHARGE_DAILY].coordinates,
        (("138020A", _DISCHARGE_DAILY),),
        fetch_win,
        content,
        _origin(),
        (),
    )
    parsed = parse(payload, config())
    assert len(parsed.series) == 2
    series_ids = [item.series_id for item in parsed.series]
    assert len(set(series_ids)) == 2

    by_status = {outcome.series_id: outcome.status for outcome in parsed.outcomes}
    live_series_id = next(item.series_id for item in parsed.series if item.identity.published_id == "470345010")
    retired_series_id = next(item.series_id for item in parsed.series if item.identity.published_id == "381776010")
    assert by_status[live_series_id] is OutcomeStatus.SUCCESS
    assert by_status[retired_series_id] is OutcomeStatus.EMPTY

    rows = parsed.rows.filter(parsed.rows["series_id"] == live_series_id).sort("time")
    assert rows.select("time", "value", "time_zone", "source_unit").rows() == [
        (datetime(2026, 9, 1, 0, 0), 1.887, "+10:00", "cumec"),
        (datetime(2026, 9, 2, 0, 0), None, "+10:00", "cumec"),
    ]


def test_parse_values_emits_info_issue_for_a_non_quality_a_code() -> None:
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 1))
    )
    content = _values_json([("1573010", [("2026-09-01T00:00:00.000+10:00", 1.5, -1, "quality-E")])])
    payload = Payload(
        config().products[_DISCHARGE_DAILY].coordinates,
        (("410730", _DISCHARGE_DAILY),),
        fetch_win,
        content,
        _origin(),
        (),
    )
    parsed = parse(payload, config())
    assert len(parsed.issues) == 1
    assert parsed.issues[0].severity == "info"
    assert parsed.issues[0].code == "source.quality_code"
    assert parsed.issues[0].details is not None
    assert parsed.issues[0].details["source_quality_code_name"] == "quality-E"


def test_parse_values_rejects_a_timestamp_without_the_plus_ten_offset() -> None:
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 1))
    )
    content = _values_json([("1573010", [("2026-09-01T00:00:00.000+00:00", 1.5, 10, "quality-A")])])
    payload = Payload(
        config().products[_DISCHARGE_DAILY].coordinates,
        (("410730", _DISCHARGE_DAILY),),
        fetch_win,
        content,
        _origin(),
        (),
    )
    with pytest.raises(UnsupportedSourceStructureError, match=r"\+10:00"):
        parse(payload, config())


def test_assembled_drive_shares_one_list_call_and_converts_units() -> None:
    station = "410730"
    list_bytes = _list_json(
        station,
        [
            ("1573010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec"),
            ("1598010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m"),
        ],
    )
    discharge_values = _values_json([("1573010", [("2026-09-01T00:00:00.000+10:00", 12.5, 10, "quality-A")])])
    stage_values = _values_json([("1598010", [("2026-09-01T00:00:00.000+10:00", 0.745, 10, "quality-A")])])
    seen_list_calls: list[str] = []

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params["request"] == "getTimeseriesList":
                seen_list_calls.append(params["station_no"])
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            if params["ts_id"] == "1573010":
                return TransportResponse(discharge_values, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(stage_values, 200, _RETRIEVED_AT, "application/json", request.url, params)

    req = ObservationRequest(
        provider_id=ProviderId("au_bom"),
        stations=(station,),
        products=(_DISCHARGE_DAILY, _STAGE_DAILY),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 1))
        ),
    )
    from tests.test_internal_driver import _provenance

    result = drive(
        req, _AuBomStages(), provenance=_provenance(req), transport=_Transport(), receipts=ReceiptMode.INCLUDE
    )

    assert seen_list_calls == [station]
    discharge_rows = result.canonical_rows.filter(result.canonical_rows["product_id"] == str(_DISCHARGE_DAILY))
    assert discharge_rows.select("value", "unit").rows() == [(12.5, "m3/s")]
    stage_rows = result.canonical_rows.filter(result.canonical_rows["product_id"] == str(_STAGE_DAILY))
    assert stage_rows.select("value", "unit").rows() == [(0.745, "m")]
