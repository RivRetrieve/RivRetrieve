"""Source-independent tests for ar_ina data_availability series annotations (#809)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from rivretrieve._internal.engine import (
    ObservationRequest,
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ar_ina.annotations import AR_INA_SERIES_SCHEMA
from rivretrieve._internal.providers.ar_ina.config import ArInaSeriesLookupCoordinates, config
from rivretrieve._internal.providers.ar_ina.fetch import resolve_series_lookup
from rivretrieve._internal.providers.ar_ina.parse import parse
from rivretrieve._internal.source_annotations import AnnotationScope
from tests.test_ar_ina_retrieval import (
    _SERIES_URL,
    _drive_ar_ina,
    _lookup_json,
    _lookup_row,
    _obs_row,
    _ok_response,
    _QueuedTransport,
    _window,
)


def test_ar_ina_series_schema_shape() -> None:
    assert AR_INA_SERIES_SCHEMA.schema_id == "ar_ina.series"
    assert AR_INA_SERIES_SCHEMA.provider_id == "ar_ina"
    assert AR_INA_SERIES_SCHEMA.scope is AnnotationScope.SERIES
    assert [field.name for field in AR_INA_SERIES_SCHEMA.fields] == ["data_availability"]
    assert [field.dtype for field in AR_INA_SERIES_SCHEMA.fields] == ["String"]
    field = AR_INA_SERIES_SCHEMA.fields[0]
    assert field.description
    assert field.reference_url == "https://alerta.ina.gob.ar/a5/secciones/mapa/puntual"


def test_resolve_series_lookup_builds_one_annotation_row_per_series_keeping_them_distinct() -> None:
    content = _lookup_json(
        [
            _lookup_row(station_id=8, product_id="discharge_daily_mean", series_id=26605, data_availability="C"),
            _lookup_row(station_id=8, product_id="discharge_daily_mean", series_id=26606, data_availability="H"),
        ]
    )
    resolved, annotations = resolve_series_lookup(content, "8", ProductId("discharge_daily_mean"), evidence="test")
    assert {item.identity.published_id for item in resolved} == {"26605", "26606"}
    series_by_published_id = {item.identity.published_id: item.series_id for item in resolved}
    assert annotations.row_count == 2
    by_series_id = dict(
        zip(annotations.rows["series_id"].to_list(), annotations.rows["data_availability"].to_list(), strict=True)
    )
    assert by_series_id[series_by_published_id["26605"]] == "C"
    assert by_series_id[series_by_published_id["26606"]] == "H"


def test_resolve_series_lookup_omits_rows_whose_series_lacks_published_availability() -> None:
    content = _lookup_json(
        [_lookup_row(station_id=8, product_id="discharge_daily_mean", series_id=26605, data_availability="N")]
    )
    _, annotations = resolve_series_lookup(content, "8", ProductId("discharge_daily_mean"), evidence="test")
    assert annotations.row_count == 1
    assert annotations.rows["data_availability"].to_list() == ["N"]

    row = _lookup_row(station_id=8, product_id="discharge_daily_mean", series_id=26605)
    del row["date_range"]["data_availability"]
    content_missing = _lookup_json([row])
    _, empty_annotations = resolve_series_lookup(
        content_missing, "8", ProductId("discharge_daily_mean"), evidence="test"
    )
    assert empty_annotations.row_count == 0


def test_parse_series_lookup_payload_attaches_series_annotations() -> None:
    content = _lookup_json(
        [_lookup_row(station_id=8, product_id="discharge_daily_mean", series_id=26605, data_availability="RT")]
    )
    payload = Payload(
        source_coordinates=SourceCoordinates(ArInaSeriesLookupCoordinates(40, 1)),
        station_products=(("8", ProductId("discharge_daily_mean")),),
        fetch_window=_make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
        ),
        content=content,
        origin=SourceCallOrigin(
            _SERIES_URL,
            {},
            200,
            datetime(2024, 1, 1, tzinfo=UTC),
            "application/json",
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        prerequisite_calls=(),
    )
    parsed = parse(payload, config())
    assert parsed.issues == ()
    table = parsed.annotations.series_tables["ar_ina.series"]
    assert table.row_count == 1
    assert table.rows["data_availability"].to_list() == ["RT"]


def test_driver_round_trip_carries_series_annotations_through_assembly() -> None:
    def handler(request):
        params = request.params or {}
        if request.url == _SERIES_URL and params.get("estacion_id") == "8" and params.get("var_id") == "40":
            return _ok_response(
                request,
                _lookup_json(
                    [
                        _lookup_row(
                            station_id=8,
                            product_id="discharge_daily_mean",
                            series_id=26605,
                            data_availability="C",
                        )
                    ]
                ),
            )
        if request.url.endswith("/26605/observaciones"):
            return _ok_response(
                request,
                json.dumps(
                    [
                        _obs_row(
                            obs_id=501,
                            series_id=26605,
                            timestart="2024-01-01T03:00:00.000Z",
                            timeend="2024-01-02T03:00:00.000Z",
                            valor=839.95,
                        )
                    ]
                ).encode("utf-8"),
            )
        raise AssertionError(f"Unexpected request: {request.url} {params}")

    transport = _QueuedTransport(handler)
    req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("8",),
        products=(ProductId("discharge_daily_mean"),),
        window=_window(date(2024, 1, 1), date(2024, 1, 2)),
    )
    result = _drive_ar_ina(req, transport=transport)
    table = result.annotations.series_tables["ar_ina.series"]
    assert table.row_count == 1
    assert table.rows["data_availability"].to_list() == ["C"]
