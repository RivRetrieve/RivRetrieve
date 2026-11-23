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
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ar_ina.annotations import AR_INA_SERIES_SCHEMA
from rivretrieve._internal.providers.ar_ina.config import ArInaSeriesLookupCoordinates, config
from rivretrieve._internal.providers.ar_ina.fetch import resolve_series_lookup
from rivretrieve._internal.providers.ar_ina.parse import parse
from rivretrieve._internal.providers.ar_ina.series import source_series
from rivretrieve._internal.source_annotations import AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportFailure, TransportFailureCategory, TransportFailureReason
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


def test_driver_round_trip_carries_series_annotations_through_known_series_catalogue_path() -> None:
    """Regression for #862: known_series skips identity lookup but must still surface data_availability."""
    known = source_series("8", "discharge_daily_mean", published_series_id=26605)

    def handler(request):
        params = request.params or {}
        if request.url == _SERIES_URL:
            return _ok_response(
                request,
                _lookup_json(
                    [
                        _lookup_row(
                            station_id=8,
                            product_id="discharge_daily_mean",
                            series_id=26605,
                            data_availability="RT",
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
        known_series=(known,),
    )
    result = _drive_ar_ina(req, transport=transport)
    assert [o.status for o in result.outcomes] == [OutcomeStatus.SUCCESS]
    table = result.annotations.series_tables["ar_ina.series"]
    assert table.row_count == 1
    assert table.rows["data_availability"].to_list() == ["RT"]


def test_known_series_catalogue_path_keeps_measurements_when_annotation_lookup_fails() -> None:
    """A failed best-effort annotation lookup must not block an already-established fetch."""
    known = source_series("8", "discharge_daily_mean", published_series_id=26605)

    def handler(request):
        if request.url == _SERIES_URL:
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        assert request.url.endswith("/26605/observaciones")
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

    transport = _QueuedTransport(handler)
    req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("8",),
        products=(ProductId("discharge_daily_mean"),),
        window=_window(date(2024, 1, 1), date(2024, 1, 2)),
        known_series=(known,),
    )
    result = _drive_ar_ina(req, transport=transport)
    assert [o.status for o in result.outcomes] == [OutcomeStatus.SUCCESS]
    assert result.canonical_rows["value"].to_list() == [839.95]
    assert any(issue.code == "source.annotation_unavailable" for issue in result.issues)
    assert result.annotations.series_tables.get("ar_ina.series") is None or (
        result.annotations.series_tables["ar_ina.series"].row_count == 0
    )


def test_driver_reuses_prerequisite_lookup_interpretation_without_second_decode(monkeypatch) -> None:
    """Driver reuses lookup ParsedSeries (series + data_availability) without re-decoding lookup JSON."""
    from dataclasses import replace

    import polars.testing as pl_testing

    import rivretrieve._internal.providers.ar_ina.fetch as ar_ina_fetch
    import rivretrieve._internal.providers.ar_ina.parse as ar_ina_parse
    from rivretrieve._internal.driver import drive
    from tests.test_ar_ina_retrieval import _ArInaStages
    from tests.test_internal_driver import _provenance

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

    json_loads_calls = 0
    real_loads = json.loads

    def counted_loads(*args, **kwargs):
        nonlocal json_loads_calls
        json_loads_calls += 1
        return real_loads(*args, **kwargs)

    resolve_calls = 0
    real_parse_resolve = ar_ina_parse.resolve_series_lookup
    real_fetch_resolve = ar_ina_fetch.resolve_series_lookup

    def counted_parse_resolve(*args, **kwargs):
        nonlocal resolve_calls
        resolve_calls += 1
        return real_parse_resolve(*args, **kwargs)

    def counted_fetch_resolve(*args, **kwargs):
        nonlocal resolve_calls
        resolve_calls += 1
        return real_fetch_resolve(*args, **kwargs)

    driver_parse_calls = 0

    class ReusedStages(_ArInaStages):
        @staticmethod
        def parse(payload, provider_config):
            nonlocal driver_parse_calls
            driver_parse_calls += 1
            return ar_ina_parse.parse(payload, provider_config)

    class BaselineStages(_ArInaStages):
        @staticmethod
        def fetch(*args, **kwargs):
            return replace(ar_ina_fetch.fetch(*args, **kwargs), interpretations=())

    monkeypatch.setattr(json, "loads", counted_loads)
    monkeypatch.setattr(ar_ina_parse, "resolve_series_lookup", counted_parse_resolve)
    monkeypatch.setattr(ar_ina_fetch, "resolve_series_lookup", counted_fetch_resolve)

    req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("8",),
        products=(ProductId("discharge_daily_mean"),),
        window=_window(date(2024, 1, 1), date(2024, 1, 2)),
    )
    reused = drive(
        req,
        ReusedStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.INCLUDE,
        transport=_QueuedTransport(handler),
        cache="bypass",
    )
    assert driver_parse_calls == 1
    assert resolve_calls == 1
    assert json_loads_calls == 2

    monkeypatch.undo()
    baseline = drive(
        req,
        BaselineStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.INCLUDE,
        transport=_QueuedTransport(handler),
        cache="bypass",
    )
    pl_testing.assert_frame_equal(reused.canonical_rows, baseline.canonical_rows)
    pl_testing.assert_frame_equal(
        reused.annotations.series_tables["ar_ina.series"].rows,
        baseline.annotations.series_tables["ar_ina.series"].rows,
    )

    def normalize_evidence(entries):
        normalized = []
        for entry in entries:
            prefix, sep, _ = entry.partition(":")
            normalized.append(
                f"{prefix}:<id>"
                if sep and prefix in ("source-call", "source-inventory", "retrieval-outcome")
                else entry
            )
        return tuple(normalized)

    def normalize_series(items):
        return [
            item.model_copy(
                update={
                    "identity": item.identity.model_copy(
                        update={"evidence": normalize_evidence(item.identity.evidence)}
                    )
                }
            )
            for item in items
        ]

    def normalize_inventories(items):
        return [
            (
                item.scope,
                item.members,
                item.member_facts,
                item.completeness,
                item.access,
                item.origin,
                item.window,
                normalize_evidence(item.evidence),
                item.reason,
            )
            for item in items
        ]

    def normalize_outcomes(items):
        return [
            (
                item.series_id,
                item.station_id,
                item.product_id,
                item.window,
                item.status,
                item.facts_ids,
                item.reason,
                item.retrieved_at,
                len(item.calls),
            )
            for item in items
        ]

    assert normalize_series(reused.source_series) == normalize_series(baseline.source_series)
    assert normalize_outcomes(reused.outcomes) == normalize_outcomes(baseline.outcomes)
    assert normalize_inventories(reused.inventories) == normalize_inventories(baseline.inventories)
    assert reused.issues == baseline.issues
    assert [(e.authorship, e.origin.url, e.content) for e in reused.receipts.entries] == [
        (e.authorship, e.origin.url, e.content) for e in baseline.receipts.entries
    ]


def test_prerequisite_lookup_reuse_preserves_evidence_when_observations_fail(monkeypatch) -> None:
    """When /observaciones fails, reused lookup evidence still preserves calls, receipts, and data_availability."""
    from dataclasses import replace

    import polars.testing as pl_testing

    import rivretrieve._internal.providers.ar_ina.fetch as ar_ina_fetch
    import rivretrieve._internal.providers.ar_ina.parse as ar_ina_parse
    from rivretrieve._internal.driver import drive
    from tests.test_ar_ina_retrieval import _ArInaStages
    from tests.test_internal_driver import _provenance

    def handler(request):
        if request.url == _SERIES_URL:
            return _ok_response(
                request,
                _lookup_json(
                    [
                        _lookup_row(
                            station_id=8,
                            product_id="discharge_daily_mean",
                            series_id=26605,
                            data_availability="RT",
                        )
                    ]
                ),
            )
        if request.url.endswith("/26605/observaciones"):
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    json_loads_calls = 0
    real_loads = json.loads

    def counted_loads(*args, **kwargs):
        nonlocal json_loads_calls
        json_loads_calls += 1
        return real_loads(*args, **kwargs)

    driver_parse_calls = 0

    class ReusedStages(_ArInaStages):
        @staticmethod
        def parse(payload, provider_config):
            nonlocal driver_parse_calls
            driver_parse_calls += 1
            return ar_ina_parse.parse(payload, provider_config)

    class BaselineStages(_ArInaStages):
        @staticmethod
        def fetch(*args, **kwargs):
            return replace(ar_ina_fetch.fetch(*args, **kwargs), interpretations=())

    monkeypatch.setattr(json, "loads", counted_loads)
    req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("8",),
        products=(ProductId("discharge_daily_mean"),),
        window=_window(date(2024, 1, 1), date(2024, 1, 2)),
    )
    reused = drive(
        req,
        ReusedStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.INCLUDE,
        transport=_QueuedTransport(handler),
        cache="bypass",
    )
    assert driver_parse_calls == 0
    assert json_loads_calls == 1

    monkeypatch.undo()
    baseline = drive(
        req,
        BaselineStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.INCLUDE,
        transport=_QueuedTransport(handler),
        cache="bypass",
    )

    def normalize_series(items):
        return [
            item.model_copy(
                update={
                    "identity": item.identity.model_copy(
                        update={
                            "evidence": tuple(
                                "source-call:<id>" if e.startswith("source-call:") else e
                                for e in item.identity.evidence
                            )
                        }
                    )
                }
            )
            for item in items
        ]

    assert normalize_series(reused.source_series) == normalize_series(baseline.source_series)
    assert reused.source_series[0].identity.published_id == "26605"
    pl_testing.assert_frame_equal(
        reused.annotations.series_tables["ar_ina.series"].rows,
        baseline.annotations.series_tables["ar_ina.series"].rows,
    )
    assert reused.annotations.series_tables["ar_ina.series"].rows["data_availability"].to_list() == ["RT"]
    assert [(o.series_id, o.station_id, o.product_id, o.window, o.status, len(o.calls)) for o in reused.outcomes] == [
        (o.series_id, o.station_id, o.product_id, o.window, o.status, len(o.calls)) for o in baseline.outcomes
    ]
    assert reused.outcomes[0].status is OutcomeStatus.FAILED
    assert [(e.authorship, e.origin.url, e.content) for e in reused.receipts.entries] == [
        (e.authorship, e.origin.url, e.content) for e in baseline.receipts.entries
    ]
    assert len(reused.provenance.calls_made) == len(baseline.provenance.calls_made) == 2
    assert [c["url"] for c in reused.provenance.calls_made] == [c["url"] for c in baseline.provenance.calls_made]
    obs_failed_call = next(
        c for c in reused.provenance.calls_made if str(c.get("url", "")).endswith("/26605/observaciones")
    )
    assert obs_failed_call["prerequisite_acquisition_ids"]
