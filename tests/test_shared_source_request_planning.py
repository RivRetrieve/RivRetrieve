from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import polars as pl
import pytest

import rivretrieve._internal.discovery as discovery_module
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    FetchWindow,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RenderedWindow,
    RequestedWindow,
    Rows,
    RowsSchema,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptAuthorship, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_series import (
    ClippingAxis,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RestrictionKind,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)
from rivretrieve._internal.transport import HttpClient


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _date_window(start: str, stop: str) -> RequestedWindow:
    return RequestedWindow(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        WindowEndpoint.from_datetime(datetime.fromisoformat(stop)),
    )


def _sparse_config() -> ProviderConfig:
    return ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("flow"): ProductConfig(
                SourceCoordinates("flow"),
                Unit.M3_S,
                Daily(DayDefinition("00:00"), DailyLabelTime("00:00")),
            ),
            ProductId("level"): ProductConfig(
                SourceCoordinates("level"),
                Unit.M,
                Daily(DayDefinition("00:00"), DailyLabelTime("00:00")),
            ),
        },
    )


def _sparse_declarations() -> ProductWindowDeclarations:
    decl = WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)
    return ProductWindowDeclarations({ProductId("flow"): decl, ProductId("level"): decl})


def _daily_fact(product: str) -> PhysicalFacts:
    return PhysicalFacts(
        facts_id=f"{product}:facts",
        quantity=known("discharge" if product == "flow" else "stage", "test"),
        source_unit=known("m3/s" if product == "flow" else "m", "test"),
        normalized_unit="m3/s" if product == "flow" else "m",
        frequency=known("P1D", "test"),
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_time="00:00",
    )


def _series_def(station: str, product: str, provider_id: str = "test_sparse") -> SourceSeries:
    return SourceSeries(
        series_id=f"{station}:{product}",
        provider_id=provider_id,
        station_id=station,
        product_id=product,
        identity=SourceIdentity(
            namespace="test-source",
            published_id=f"{station}:{product}",
            origin="response",
            evidence=("test definition",),
        ),
        facts=(_daily_fact(product),),
    )


class _RecordingPerPairProvider:
    def __init__(self, provider_id: str = "test_sparse") -> None:
        self.config = _sparse_config()
        self.window_declarations = _sparse_declarations()
        self.provider_id = provider_id
        self.fetched_pairs: list[tuple[str, ProductId]] = []

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        fetch_window: FetchWindow,
        config: ProviderConfig,
        transport: object,
        *,
        scope: SeriesScope | None = None,
        known_series: tuple[SourceSeries, ...] = (),
    ) -> SourceAcquisition:
        del rendered_windows, config, transport, scope, known_series
        assert len(stations) == 1 and len(products) == 1
        pair = (stations[0], products[0])
        self.fetched_pairs.append(pair)
        return SourceAcquisition(
            value=(
                Payload(
                    source_coordinates=SourceCoordinates(str(pair[1])),
                    station_products=(pair,),
                    fetch_window=fetch_window,
                    content=f"{pair[0]}:{pair[1]}".encode(),
                    origin=SourceCallOrigin(
                        f"https://example.invalid/{pair[0]}/{pair[1]}",
                        MappingProxyType({"station": pair[0], "product": str(pair[1])}),
                        200,
                        _utc(2026, 1, 2, 12),
                        "text/plain",
                        UnknownOriginFact(),
                        UnknownOriginFact(),
                    ),
                    prerequisite_calls=(),
                ),
            )
        )

    def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
        del config
        station, product = payload.station_products[0]
        s_def = _series_def(station, str(product), provider_id=self.provider_id)
        fact = s_def.facts[0]
        rows: Rows = pl.DataFrame(
            {
                "station_id": [station],
                "product_id": [str(product)],
                "time": [datetime(2024, 6, 1, 0, 0)],
                "value": [10.0 if product == "flow" else 2.5],
                "time_zone": ["+00:00"],
                "series_id": [s_def.series_id],
                "facts_id": [fact.facts_id],
                "source_unit": [fact.normalized_unit],
            },
            schema=RowsSchema.polars_schema,
        )
        window = SeriesWindow(
            start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        )
        return ParsedSeries(
            rows=rows,
            series=(s_def,),
            inventories=(
                InventorySnapshot(
                    snapshot_id=f"inv:{station}:{product}",
                    scope=SeriesScope(
                        provider_ids=(self.provider_id,), station_ids=(station,), product_ids=(str(product),)
                    ),
                    members=(s_def.series_id,),
                    completeness=InventoryCompleteness.COMPLETE,
                    access="test source",
                    origin="response",
                    window=window,
                    evidence=("test response",),
                ),
            ),
            outcomes=(
                RetrievalOutcome(
                    outcome_id=f"out:{station}:{product}",
                    series_id=s_def.series_id,
                    station_id=station,
                    product_id=str(product),
                    window=window,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=(fact.facts_id,),
                ),
            ),
        )


def test_observation_request_station_products_validation_and_pairs() -> None:
    window = _date_window("2024-06-01", "2024-06-02")
    pid = ProviderId("test_sparse")
    flow = ProductId("flow")
    level = ProductId("level")

    cartesian = ObservationRequest(pid, ("s1", "s2"), (flow, level), window)
    assert cartesian.station_products is None
    assert cartesian.pairs == (("s1", flow), ("s1", level), ("s2", flow), ("s2", level))

    sparse = ObservationRequest(
        pid,
        ("s1", "s2"),
        (flow, level),
        window,
        station_products=(("s1", flow), ("s2", level)),
    )
    assert sparse.pairs == (("s1", flow), ("s2", level))

    with pytest.raises(ValueError, match="empty"):
        ObservationRequest(pid, ("s1",), (flow,), window, station_products=())

    with pytest.raises(ValueError, match="duplicate"):
        ObservationRequest(pid, ("s1",), (flow,), window, station_products=(("s1", flow), ("s1", flow)))

    with pytest.raises(ValueError, match="station"):
        ObservationRequest(pid, ("s1",), (flow,), window, station_products=(("s2", flow),))

    with pytest.raises(ValueError, match="product"):
        ObservationRequest(pid, ("s1",), (flow,), window, station_products=(("s1", level),))


def test_fetch_dispatches_single_whole_provider_call_with_sparse_pairs(monkeypatch, tmp_path: Path) -> None:
    s1_flow = _series_def("s1", "flow")
    s1_level = _series_def("s1", "level")
    s2_flow = _series_def("s2", "flow")
    s2_level = _series_def("s2", "level")
    # Provider catalog contains all 4 pairs, caller selects ONLY s1.flow and s2.level.
    del s1_level, s2_flow
    selected = (s1_flow, s2_level)

    captured_calls: list[dict[str, object]] = []
    fake_provider = _RecordingPerPairProvider()

    @dataclass(frozen=True)
    class _FakeHandle:
        provider_id: ProviderId = ProviderId("test_sparse")
        public_archive_access: object | None = None
        _reader: object | None = None

        def observations(self, **kwargs):
            captured_calls.append(dict(kwargs))
            req = ObservationRequest(
                self.provider_id,
                tuple(kwargs["stations"]),
                tuple(ProductId(p) for p in kwargs["products"]),
                _date_window("2024-06-01", "2024-06-01"),
                scope=kwargs["scope"],
                known_series=kwargs["known_series"],
                inventories=kwargs["inventories"],
                station_products=tuple((s, ProductId(p)) for s, p in kwargs["station_products"]),
            )
            assembled = driver_module.drive(
                req,
                fake_provider,
                provenance=ObservationProvenance(
                    source="test",
                    provider_id=self.provider_id,
                    requested_at=_utc(2026, 1, 2, 12),
                    request={
                        "stations": list(req.stations),
                        "products": [str(p) for p in req.products],
                        "start": req.window.start.isoformat(),
                        "end": req.window.end.isoformat(),
                    },
                ),
                receipts=kwargs["receipts"],
                cache=kwargs["cache"],
                store=kwargs["store"],
                reader=self._reader,
            )
            from rivretrieve._internal.observations import ObservationResult
            from rivretrieve._internal.source_annotations import with_annotations

            return with_annotations(
                ObservationResult(
                    data=assembled.canonical_rows,
                    source_series=assembled.source_series,
                    inventories=assembled.inventories,
                    outcomes=assembled.outcomes,
                    supporting_outcomes=assembled.supporting_outcomes,
                    scope=assembled.scope,
                    provenance=assembled.provenance,
                    issues=assembled.issues,
                    receipts=assembled.receipts,
                ),
                assembled.annotations,
            )

    monkeypatch.setattr(discovery_module, "_provider_lookup", lambda pid: _FakeHandle())
    scope = SeriesScope(provider_ids=("test_sparse",), station_ids=("s1", "s2"), product_ids=("flow", "level"))
    selection = discovery_module._Selection(
        scope=scope,
        known_series=selected,
        inventories=(),
    )
    result = discovery_module._fetch_provider_series(
        "test_sparse",
        selected,
        selection=selection,
        start=datetime(2024, 6, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 6, 1, 23, 59, 59, tzinfo=UTC),
        future_local_date=None,
        transport=HttpClient(),
        receipts=ReceiptMode.INCLUDE,
        cache="bypass",
        store=tmp_path / "cache",
        on_issue="ignore",
    )

    assert len(captured_calls) == 1
    assert captured_calls[0]["stations"] == ("s1", "s2")
    assert captured_calls[0]["products"] == ("flow", "level")
    assert captured_calls[0]["station_products"] == (("s1", "flow"), ("s2", "level"))
    assert fake_provider.fetched_pairs == [("s1", ProductId("flow")), ("s2", ProductId("level"))]
    assert sorted((r["station_id"], r["product_id"]) for r in result.data.iter_rows(named=True)) == [
        ("s1", "flow"),
        ("s2", "level"),
    ]
    assert sorted((o.station_id, o.product_id) for o in result.outcomes) == [("s1", "flow"), ("s2", "level")]
    assert len(result.receipts.entries) == 2


def test_drive_sparse_station_products_and_mixed_cache_reuse(tmp_path: Path) -> None:
    provider = _RecordingPerPairProvider()
    pid = ProviderId("test_sparse")
    flow = ProductId("flow")
    level = ProductId("level")
    window = _date_window("2024-06-01", "2024-06-01")
    scope = SeriesScope(provider_ids=("test_sparse",), station_ids=("s1", "s2"), product_ids=("flow", "level"))

    store_path = tmp_path / "store"
    # First populate store with s1.flow and s2.level ONLY
    first = driver_module.drive(
        ObservationRequest(
            pid,
            ("s1", "s2"),
            (flow, level),
            window,
            scope=scope,
            station_products=(("s1", flow), ("s2", level)),
        ),
        provider,
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        cache="reuse",
        store=store_path,
    )
    assert provider.fetched_pairs == [("s1", flow), ("s2", level)]
    assert len(first.outcomes) == 2

    # Second: ask for ALL 4 pairs with cache="reuse": only (s1, level) and (s2, flow) are fetched!
    provider.fetched_pairs.clear()
    second = driver_module.drive(
        ObservationRequest(pid, ("s1", "s2"), (flow, level), window, scope=scope),
        provider,
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 2, 13)),
        cache="reuse",
        store=store_path,
    )
    assert provider.fetched_pairs == [("s1", level), ("s2", flow)]
    assert sorted((o.station_id, o.product_id) for o in second.outcomes) == [
        ("s1", "flow"),
        ("s1", "level"),
        ("s2", "flow"),
        ("s2", "level"),
    ]

    # Third: sparse request for only (s1, level) and (s2, flow) must NOT leak cached (s1, flow) or (s2, level)
    provider.fetched_pairs.clear()
    third = driver_module.drive(
        ObservationRequest(
            pid,
            ("s1", "s2"),
            (flow, level),
            window,
            scope=scope,
            station_products=(("s1", level), ("s2", flow)),
        ),
        provider,
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 2, 14)),
        cache="reuse",
        store=store_path,
    )
    assert provider.fetched_pairs == []
    assert sorted((r["station_id"], r["product_id"]) for r in third.canonical_rows.iter_rows(named=True)) == [
        ("s1", "level"),
        ("s2", "flow"),
    ]
    assert sorted((o.station_id, o.product_id) for o in third.outcomes) == [("s1", "level"), ("s2", "flow")]


def test_drive_store_respects_sparse_station_products(tmp_path: Path) -> None:
    from rivretrieve._internal.store import certify_store
    from tests.store.certification_support import artifact_and_request, complete

    series = tuple(_series_def(st, pr, provider_id="fixture_bulk") for st in ("s1", "s2") for pr in ("flow", "level"))
    decoded = pl.DataFrame(
        [
            {
                "product": item.product_id,
                "station_id": item.station_id,
                "time": datetime(2024, 6, 1, 0, 0),
                "time_zone": "+00:00",
                "value": float(idx + 1),
                "value_state": "published_value",
                "series_id": item.series_id,
                "facts_id": item.facts[0].facts_id,
                "source_unit": item.facts[0].normalized_unit,
                "raw_value": str(idx + 1),
            }
            for idx, item in enumerate(series)
        ],
        schema={
            "product": pl.String,
            "station_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "value": pl.Float64,
            "value_state": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
            "raw_value": pl.String,
        },
    )
    artifact, compile_req = artifact_and_request(tmp_path)
    compile_req = replace(compile_req, series=series)
    certify_store(compile_req, artifact, lambda _p: complete(decoded))

    pid = ProviderId("fixture_bulk")
    flow = ProductId("flow")
    level = ProductId("level")
    scope = SeriesScope(provider_ids=("fixture_bulk",), station_ids=("s1", "s2"), product_ids=("flow", "level"))
    assembled = driver_module.drive_store(
        ObservationRequest(
            pid,
            ("s1", "s2"),
            (flow, level),
            _date_window("2024-06-01", "2024-06-01"),
            scope=scope,
            station_products=(("s1", flow), ("s2", level)),
        ),
        _sparse_config(),
        compile_req.destination,
        provenance=ObservationProvenance(source="Bulk", provider_id=pid),
        receipts=ReceiptMode.INCLUDE,
    )
    assert sorted((r["station_id"], r["product_id"]) for r in assembled.canonical_rows.iter_rows(named=True)) == [
        ("s1", "flow"),
        ("s2", "level"),
    ]
    assert sorted((o.station_id, o.product_id) for o in assembled.outcomes) == [("s1", "flow"), ("s2", "level")]


# ---------------------------------------------------------------------------
# Stage 1.2: request_planning, multi-station driver, provider_series, LiveStages
# ---------------------------------------------------------------------------


def test_request_identity_distinguishes_method_url_params_body_window_axis_and_context() -> None:
    from rivretrieve._internal.request_planning import request_identity
    from rivretrieve._internal.source_series import TimeAxis
    from rivretrieve._internal.transport import HttpMethod, TransportRequest

    fw1 = FetchWindow.__new__(FetchWindow)
    object.__setattr__(fw1, "start", WindowEndpoint.from_datetime(datetime(2024, 6, 1)))
    object.__setattr__(fw1, "end", WindowEndpoint.from_datetime(datetime(2024, 6, 2)))
    fw2 = FetchWindow.__new__(FetchWindow)
    object.__setattr__(fw2, "start", WindowEndpoint.from_datetime(datetime(2024, 6, 1)))
    object.__setattr__(fw2, "end", WindowEndpoint.from_datetime(datetime(2024, 6, 3)))

    req_a = TransportRequest(HttpMethod.GET, "https://example.invalid/obs", {"b": "2", "a": "1"})
    req_b = TransportRequest(HttpMethod.GET, "https://example.invalid/obs", {"a": "1", "b": "2"})
    assert request_identity(req_a, window=fw1) == request_identity(req_b, window=fw1)

    req_post_1 = TransportRequest(HttpMethod.POST, "https://example.invalid/obs", body=b'[{"stationId":"1"}]')
    req_post_2 = TransportRequest(HttpMethod.POST, "https://example.invalid/obs", body=b'[{"stationId":"2"}]')
    assert request_identity(req_post_1, window=fw1) != request_identity(req_post_2, window=fw1)
    assert request_identity(req_a, window=fw1) != request_identity(req_a, window=fw2)
    assert request_identity(req_a, window=fw1, axis=TimeAxis.NATIVE) != request_identity(
        req_a, window=fw1, axis=TimeAxis.UTC
    )
    assert request_identity(req_a, window=fw1, access_context="archive") != request_identity(
        req_a, window=fw1, access_context="public"
    )


def test_batch_selector_packs_by_max_items_and_url_length() -> None:
    from rivretrieve._internal.request_planning import BatchSelector

    selector = BatchSelector(max_items=3, max_url_length=65)
    batches = selector.pack_batches(
        ("ST001", "ST002", "ST003", "ST004", "ST005", "ST006"),
        estimate_url_length=lambda items: len("https://example.invalid/api?codes=" + ",".join(items)),
    )
    # base len = 34; 3 items = 34 + 17 = 51 <= 65; try max_url_length=50 next
    assert batches == (("ST001", "ST002", "ST003"), ("ST004", "ST005", "ST006"))

    tight = BatchSelector(max_items=5, max_url_length=48)
    # 34 + len("ST001,ST002") = 45 <= 48; adding ST003 -> 51 > 48
    assert tight.pack_batches(
        ("ST001", "ST002", "ST003", "ST004"),
        estimate_url_length=lambda items: len("https://example.invalid/api?codes=" + ",".join(items)),
    ) == (("ST001", "ST002"), ("ST003", "ST004"))


def test_planned_lookup_deduplication_and_failure_isolation() -> None:
    import json

    from rivretrieve._internal.request_planning import (
        ConsumerNeed,
        LookupFailureResult,
        ObservationPlan,
        PlannedLookup,
        PlannedObservationRequest,
        ResolvedLookup,
    )
    from rivretrieve._internal.source_acquisition import (
        FailedSourceRequest,
        SourceRequestTarget,
        SourceResponseMeaning,
    )
    from rivretrieve._internal.transport import (
        HttpMethod,
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
        TransportResponse,
    )

    sent_urls: list[str] = []

    class _MockTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            sent_urls.append(request.url)
            if request.url.endswith("/lookup/s2"):
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=500,
                )
            if "/lookup/s1" in request.url:
                return TransportResponse(
                    url=request.url,
                    request_parameters=request.params or {},
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=json.dumps({"station_token": "tok-s1"}).encode(),
                )
            return TransportResponse(
                url=request.url,
                request_parameters=request.params or {},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12, 1),
                content_type="application/json",
                content=json.dumps({"station": "s1", "token": "tok-s1"}).encode(),
            )

    class _Planner:
        def plan_lookups(self, needs: tuple[ConsumerNeed, ...], config: ProviderConfig) -> tuple[PlannedLookup, ...]:
            del config
            # Even though s1 appears twice (flow + level), both emit identical lookup identity.
            return tuple(
                PlannedLookup(
                    key=f"meta:{need.station}",
                    consumers=(need,),
                    request=TransportRequest(HttpMethod.GET, f"https://example.invalid/lookup/{need.station}"),
                    source_coordinates=SourceCoordinates("lookup"),
                    fetch_window=need.fetch_window,
                    emit_payload=False,
                    on_response=lambda resp, consumers, acq_id, cfg: ResolvedLookup(
                        value=json.loads(resp.content)["station_token"],
                    ),
                    on_failure=lambda failure, req, consumers, call_id, acq_id: (
                        FailedSourceRequest(
                            event_id=f"fail:{c.station}:{c.product}",
                            series=SourceRequestTarget(c.station, str(c.product)),
                            window=c.window,
                            request=req,
                            failure=failure,
                            meaning=SourceResponseMeaning.UNSPECIFIED,
                            call_id=call_id,
                        )
                        for c in consumers
                    ),
                )
                for need in needs
            )

        def plan_observations(
            self,
            needs: tuple[ConsumerNeed, ...],
            lookups: Mapping[object, object],
            config: ProviderConfig,
        ) -> ObservationPlan:
            del config
            reqs = []
            for need in needs:
                res = lookups.get((f"meta:{need.station}", need.station, need.product))
                if isinstance(res, LookupFailureResult) or not isinstance(res, ResolvedLookup):
                    continue
                reqs.append(
                    PlannedObservationRequest(
                        consumers=(need,),
                        request=TransportRequest(
                            HttpMethod.GET,
                            f"https://example.invalid/obs/{need.station}/{res.value}",
                        ),
                        source_coordinates=SourceCoordinates(str(need.product)),
                        fetch_window=need.fetch_window,
                        prerequisite_acquisition_ids=(res.acquisition_id,),
                    )
                )
            return ObservationPlan(requests=tuple(reqs))

    class _LookupProvider:
        config = _sparse_config()
        window_declarations = _sparse_declarations()
        request_planner = _Planner()

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            del config
            st, pr = payload.station_products[0]
            s_def = _series_def(st, str(pr), provider_id="test_lookup")
            fact = s_def.facts[0]
            window = SeriesWindow(
                start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
                end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
            )
            rows = pl.DataFrame(
                {
                    "station_id": [st],
                    "product_id": [str(pr)],
                    "time": [datetime(2024, 6, 1, 0, 0)],
                    "value": [4.0 if pr == "flow" else 1.5],
                    "time_zone": ["+00:00"],
                    "series_id": [s_def.series_id],
                    "facts_id": [fact.facts_id],
                    "source_unit": [fact.normalized_unit],
                },
                schema=RowsSchema.polars_schema,
            )
            return ParsedSeries(
                rows=rows,
                series=(s_def,),
                inventories=(
                    InventorySnapshot(
                        snapshot_id=f"inv:{st}:{pr}",
                        scope=payload.scope
                        or SeriesScope(provider_ids=("test_lookup",), station_ids=(st,), product_ids=(str(pr),)),
                        members=(s_def.series_id,),
                        completeness=InventoryCompleteness.COMPLETE,
                        access="test",
                        origin="response",
                        window=window,
                        evidence=("test",),
                    ),
                ),
                outcomes=(
                    RetrievalOutcome(
                        outcome_id=f"out:{st}:{pr}",
                        series_id=s_def.series_id,
                        station_id=st,
                        product_id=str(pr),
                        window=window,
                        status=OutcomeStatus.SUCCESS,
                        facts_ids=(fact.facts_id,),
                    ),
                ),
            )

    pid = ProviderId("test_lookup")
    assembled = driver_module.drive(
        ObservationRequest(
            pid, ("s1", "s2"), (ProductId("flow"), ProductId("level")), _date_window("2024-06-01", "2024-06-01")
        ),
        _LookupProvider(),
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=_MockTransport(),
        receipts=ReceiptMode.INCLUDE,
    )
    # 1 lookup for s1 (deduped across flow & level), 1 failed lookup for s2, 1 shared obs GET for s1 (deduped across flow & level)
    assert sent_urls == [
        "https://example.invalid/lookup/s1",
        "https://example.invalid/lookup/s2",
        "https://example.invalid/obs/s1/tok-s1",
    ]
    # s1 succeeded for both products; s2 failed cleanly for both products with 1 shared failed_call entry
    assert sorted((r["station_id"], r["product_id"]) for r in assembled.canonical_rows.iter_rows(named=True)) == [
        ("s1", "flow"),
        ("s1", "level"),
    ]
    assert {o.station_id: o.status for o in assembled.outcomes if o.station_id == "s1"} == {"s1": OutcomeStatus.SUCCESS}
    assert all(o.status is OutcomeStatus.FAILED for o in assembled.outcomes if o.station_id == "s2")
    s2_failed_calls = [c for c in assembled.provenance.calls_made if "lookup/s2" in str(c.get("url"))]
    assert len(s2_failed_calls) == 1
    assert set(s2_failed_calls[0]["station_products"]) == {("s2", "flow"), ("s2", "level")}
    s1_lookup_calls = [c for c in assembled.provenance.calls_made if "lookup/s1" in str(c.get("url"))]
    assert len(s1_lookup_calls) == 1
    assert set(s1_lookup_calls[0]["station_products"]) == {("s1", "flow"), ("s1", "level")}


def test_shared_snapshot_multi_station_parse_mapped_group_and_missing_station_isolation() -> None:
    import json

    from rivretrieve._internal.provider_series import NATIVE_SCHEMA, SeriesMapping, parse_mapped_group
    from rivretrieve._internal.request_planning import (
        ConsumerNeed,
        ObservationPlan,
        PlannedLookup,
        PlannedObservationRequest,
    )
    from rivretrieve._internal.transport import HttpMethod, TransportRequest, TransportResponse

    mappings = {
        ProductId("flow"): SeriesMapping(
            namespace="test.flow",
            quantity="discharge",
            source_unit="m3/s",
            normalized_unit="m3/s",
            frequency="P1D",
            label_time="00:00",
            clipping_axis=ClippingAxis.CALENDAR_DATE,
            evidence=("test mapping",),
        ),
        ProductId("level"): SeriesMapping(
            namespace="test.level",
            quantity="stage",
            source_unit="m",
            normalized_unit="m",
            frequency="P1D",
            label_time="00:00",
            clipping_axis=ClippingAxis.CALENDAR_DATE,
            evidence=("test mapping",),
        ),
    }

    http_calls: list[str] = []
    decode_calls: list[int] = []

    class _SharedFileTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            http_calls.append(request.url)
            return TransportResponse(
                url=request.url,
                request_parameters={},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps(
                    {
                        "s1": {"flow": 12.5, "level": 1.2},
                        "s2": {"flow": 22.5, "level": 2.2},
                    }
                ).encode(),
            )

    class _Planner:
        def plan_lookups(self, needs: tuple[ConsumerNeed, ...], config: ProviderConfig) -> tuple[PlannedLookup, ...]:
            del needs, config
            return ()

        def plan_observations(
            self,
            needs: tuple[ConsumerNeed, ...],
            lookups: Mapping[object, object],
            config: ProviderConfig,
        ) -> ObservationPlan:
            del lookups, config
            # Deliberately emit per-need requests with identical URL to exercise engine deduplication
            # Note: drop s3 in one test to test missing station in group!
            return ObservationPlan(
                requests=tuple(
                    PlannedObservationRequest(
                        consumers=(need,),
                        request=TransportRequest(HttpMethod.GET, "https://example.invalid/snapshot-daily.json"),
                        source_coordinates=SourceCoordinates("shared_snapshot"),
                        fetch_window=need.fetch_window,
                    )
                    for need in needs
                    if need.station != "s3"
                )
            )

    class _SharedFileProvider:
        config = _sparse_config()
        window_declarations = _sparse_declarations()
        request_planner = _Planner()

        def _native_parse_group(
            self,
            payload: Payload,
            pair_payloads: Mapping[tuple[str, ProductId], Payload],
            config: ProviderConfig,
        ) -> dict[tuple[str, ProductId], object]:
            from rivretrieve._internal.engine import WithIssues

            del config
            decode_calls.append(1)
            doc = json.loads(payload.content)
            out = {}
            for key in pair_payloads:
                st, pr = key
                df = pl.DataFrame(
                    {
                        "station_id": [st],
                        "product_id": [str(pr)],
                        "time": [datetime(2024, 6, 1, 0, 0)],
                        "value": [float(doc[st][str(pr)])],
                        "time_zone": ["+00:00"],
                    },
                    schema=NATIVE_SCHEMA,
                )
                out[key] = WithIssues(value=df, issues=())
            return out

        def parse_group(
            self,
            payload: Payload,
            pair_payloads: Mapping[tuple[str, ProductId], Payload],
            config: ProviderConfig,
        ) -> dict[tuple[str, ProductId], ParsedSeries]:
            return parse_mapped_group(
                payload,
                pair_payloads,
                config,
                provider="test_shared",
                mappings=mappings,
                native_parse_group=self._native_parse_group,
            )

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            return next(iter(self.parse_group(payload, {payload.station_products[0]: payload}, config).values()))

    pid = ProviderId("test_shared")
    assembled = driver_module.drive(
        ObservationRequest(
            pid,
            ("s1", "s2", "s3"),
            (ProductId("flow"), ProductId("level")),
            _date_window("2024-06-01", "2024-06-01"),
        ),
        _SharedFileProvider(),
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=_SharedFileTransport(),
        receipts=ReceiptMode.INCLUDE,
    )
    assert http_calls == ["https://example.invalid/snapshot-daily.json"]
    assert len(decode_calls) == 1
    assert len(assembled.receipts.entries) == 1
    assert len(assembled.provenance.calls_made) == 1
    assert assembled.canonical_rows.height == 4
    # s3 received no payload and no explicit failure in the group -> must get UNRESOLVED (not silently dropped!)
    s3_outcomes = [o for o in assembled.outcomes if o.station_id == "s3"]
    assert len(s3_outcomes) == 2
    assert all(o.status is OutcomeStatus.UNRESOLVED for o in s3_outcomes)


def test_batch_pagination_out_of_order_complete_empty_and_late_page_failure() -> None:
    import json

    from rivretrieve._internal.request_planning import (
        BatchPageStep,
        BatchPaginationSpec,
        ConsumerNeed,
        ObservationPlan,
        PlannedLookup,
        PlannedObservationRequest,
    )
    from rivretrieve._internal.transport import (
        HttpMethod,
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
        TransportResponse,
    )

    class _PagedTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url == "https://example.invalid/batchA?page=1":
                body = {"rows": [{"st": "s2", "val": 2.0}], "next": "https://example.invalid/batchA?page=2"}
            elif request.url == "https://example.invalid/batchA?page=2":
                body = {"rows": [], "next": "https://example.invalid/batchA?page=3"}
            elif request.url == "https://example.invalid/batchA?page=3":
                # Out of order: s1 arrives on last page, s3 has no rows anywhere
                body = {"rows": [{"st": "s1", "val": 1.0}], "next": None}
            elif request.url == "https://example.invalid/batchB?page=1":
                body = {"rows": [{"st": "s4", "val": 4.0}], "next": "https://example.invalid/batchB?page=2"}
            elif request.url == "https://example.invalid/batchB?page=2":
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=503,
                )
            else:
                raise AssertionError(request.url)
            return TransportResponse(
                url=request.url,
                request_parameters={},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps(body).encode(),
            )

    def _step_page(
        payload: Payload,
        consumers: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> BatchPageStep:
        del config
        doc = json.loads(payload.content)
        rows_list = doc["rows"]
        # Build per-present-station ParsedSeries; absent stations stay unsettled until final page!
        interpretations: dict[tuple[str, ProductId], ParsedSeries] = {}
        present_by_station = {r["st"]: r["val"] for r in rows_list}
        for need in consumers:
            s_def = _series_def(need.station, str(need.product), provider_id="test_paged")
            fact = s_def.facts[0]
            if need.station in present_by_station:
                df = pl.DataFrame(
                    {
                        "station_id": [need.station],
                        "product_id": [str(need.product)],
                        "time": [datetime(2024, 6, 1, 0, 0)],
                        "value": [float(present_by_station[need.station])],
                        "time_zone": ["+00:00"],
                        "series_id": [s_def.series_id],
                        "facts_id": [fact.facts_id],
                        "source_unit": [fact.normalized_unit],
                    },
                    schema=RowsSchema.polars_schema,
                )
                out = RetrievalOutcome(
                    outcome_id=f"{payload.acquisition_id}:{need.station}",
                    series_id=s_def.series_id,
                    station_id=need.station,
                    product_id=str(need.product),
                    window=need.window,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=(fact.facts_id,),
                )
                inv = InventorySnapshot(
                    snapshot_id=f"inv:{payload.acquisition_id}:{need.station}",
                    scope=need.scope,
                    members=(s_def.series_id,),
                    completeness=InventoryCompleteness.COMPLETE,
                    access="test",
                    origin="response",
                    window=need.window,
                    evidence=("test",),
                )
                interpretations[(need.station, need.product)] = ParsedSeries(df, (s_def,), (inv,), (out,))
            else:
                interpretations[(need.station, need.product)] = ParsedSeries(
                    pl.DataFrame(schema=RowsSchema.polars_schema),
                    (s_def,),
                    (),
                    (),
                )
        next_url = doc["next"]
        return BatchPageStep(
            interpretations=interpretations,
            next_request=TransportRequest(HttpMethod.GET, next_url) if next_url is not None else None,
            cursor_key=next_url,
        )

    def _empty_for_unseen(
        need: ConsumerNeed,
        payloads: tuple[Payload, ...],
        config: ProviderConfig,
    ) -> RetrievalOutcome:
        del config
        s_def = _series_def(need.station, str(need.product), provider_id="test_paged")
        return RetrievalOutcome(
            outcome_id=stable_id("empty", need.station, *(p.acquisition_id for p in payloads)),
            series_id=s_def.series_id,
            station_id=need.station,
            product_id=str(need.product),
            window=need.window,
            status=OutcomeStatus.EMPTY,
            facts_ids=(s_def.facts[0].facts_id,),
            calls=tuple(p.acquisition_id for p in payloads),
        )

    class _PagedPlanner:
        def plan_lookups(self, needs: tuple[ConsumerNeed, ...], config: ProviderConfig) -> tuple[PlannedLookup, ...]:
            del needs, config
            return ()

        def plan_observations(
            self,
            needs: tuple[ConsumerNeed, ...],
            lookups: Mapping[object, object],
            config: ProviderConfig,
        ) -> ObservationPlan:
            del lookups, config
            batch_a = tuple(n for n in needs if n.station in ("s1", "s2", "s3"))
            batch_b = tuple(n for n in needs if n.station in ("s4", "s5"))
            spec = BatchPaginationSpec(step_page=_step_page, finalize_unseen_consumer=_empty_for_unseen)
            return ObservationPlan(
                requests=(
                    PlannedObservationRequest(
                        consumers=batch_a,
                        request=TransportRequest(HttpMethod.GET, "https://example.invalid/batchA?page=1"),
                        source_coordinates=SourceCoordinates("paged"),
                        fetch_window=batch_a[0].fetch_window,
                        pagination=spec,
                    ),
                    PlannedObservationRequest(
                        consumers=batch_b,
                        request=TransportRequest(HttpMethod.GET, "https://example.invalid/batchB?page=1"),
                        source_coordinates=SourceCoordinates("paged"),
                        fetch_window=batch_b[0].fetch_window,
                        pagination=spec,
                    ),
                )
            )

    class _PagedProvider:
        config = _sparse_config()
        window_declarations = _sparse_declarations()
        request_planner = _PagedPlanner()

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            raise AssertionError("Should use pre-interpreted BatchPageStep interpretations")

    pid = ProviderId("test_paged")
    assembled = driver_module.drive(
        ObservationRequest(
            pid, ("s1", "s2", "s3", "s4", "s5"), (ProductId("flow"),), _date_window("2024-06-01", "2024-06-01")
        ),
        _PagedProvider(),
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=_PagedTransport(),
    )
    by_station_statuses: dict[str, list[OutcomeStatus]] = {}
    for o in assembled.outcomes:
        by_station_statuses.setdefault(o.station_id, []).append(o.status)
    assert by_station_statuses["s1"] == [OutcomeStatus.SUCCESS]
    assert by_station_statuses["s2"] == [OutcomeStatus.SUCCESS]
    assert by_station_statuses["s3"] == [OutcomeStatus.EMPTY]
    s3_outcome = next(o for o in assembled.outcomes if o.station_id == "s3")
    assert len(s3_outcome.calls) == 3
    # Batch B failed on page 2 -> NO page-1 rows or SUCCESS for s4 leaked, NO fabricated EMPTY for s5, both UNRESOLVED!
    assert OutcomeStatus.UNRESOLVED in by_station_statuses["s4"]
    assert OutcomeStatus.SUCCESS not in by_station_statuses["s4"]
    assert OutcomeStatus.EMPTY not in by_station_statuses["s4"]
    assert OutcomeStatus.UNRESOLVED in by_station_statuses["s5"]
    assert OutcomeStatus.EMPTY not in by_station_statuses["s5"]
    assert sorted(assembled.canonical_rows["station_id"].to_list()) == ["s1", "s2"]


def test_live_stages_allows_request_planner_without_fetch(tmp_path: Path) -> None:
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration, load_manifest
    from rivretrieve._internal.request_planning import ConsumerNeed, ObservationPlan, PlannedLookup

    class _Planner:
        def plan_lookups(self, needs: tuple[ConsumerNeed, ...], config: ProviderConfig) -> tuple[PlannedLookup, ...]:
            del needs, config
            return ()

        def plan_observations(
            self, needs: tuple[ConsumerNeed, ...], lookups: Mapping[object, object], config: ProviderConfig
        ) -> ObservationPlan:
            del needs, lookups, config
            return ObservationPlan()

    class _PlannerOnlyStages:
        observation_source = "live"
        config = _sparse_config()
        window_declarations = _sparse_declarations()
        request_planner = _Planner()

        @staticmethod
        def parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
            raise NotImplementedError

    loaded = load_manifest(
        ("xx_planner",),
        declaration_loader=lambda _pid: ProviderDeclaration(
            tmp_path / "catalogue", LiveStages(stages=_PlannerOnlyStages)
        ),
    )
    assert loaded[0].provider_id == "xx_planner"

    class _InvalidPlannerStages:
        observation_source = "live"
        config = _sparse_config()
        window_declarations = _sparse_declarations()
        request_planner = object()

        @staticmethod
        def parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
            raise NotImplementedError

    with pytest.raises(FatalContractError, match="Provider xx_bad.*malformed LiveStages"):
        load_manifest(
            ("xx_bad",),
            declaration_loader=lambda _pid: ProviderDeclaration(
                tmp_path / "catalogue",
                LiveStages(stages=_InvalidPlannerStages),  # ty: ignore[invalid-argument-type]
            ),
        )


def test_cross_station_failure_isolation_and_failed_call_dedup(tmp_path: Path) -> None:
    from rivretrieve._internal.request_planning import (
        ConsumerNeed,
        ObservationPlan,
        PlannedLookup,
        PlannedObservationRequest,
    )
    from rivretrieve._internal.transport import (
        HttpMethod,
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
        TransportResponse,
    )

    fail_s1 = {"flag": False}

    class _IsoTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url.endswith("/shared-fail"):
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=502,
                )
            if fail_s1["flag"] and "/s1/" in request.url:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=500,
                )
            station = "s1" if "/s1/" in request.url else "s2"
            product = "flow" if request.url.endswith("/flow") else "level"
            return TransportResponse(
                url=request.url,
                request_parameters={},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="text/plain",
                content=f"{station}:{product}".encode(),
            )

    class _IsoPlanner:
        def plan_lookups(self, needs: tuple[ConsumerNeed, ...], config: ProviderConfig) -> tuple[PlannedLookup, ...]:
            del needs, config
            return ()

        def plan_observations(
            self,
            needs: tuple[ConsumerNeed, ...],
            lookups: Mapping[object, object],
            config: ProviderConfig,
        ) -> ObservationPlan:
            del lookups, config
            return ObservationPlan(
                requests=tuple(
                    PlannedObservationRequest(
                        consumers=(need,),
                        request=TransportRequest(
                            HttpMethod.GET,
                            "https://example.invalid/shared-fail"
                            if need.station == "s3"
                            else f"https://example.invalid/{need.station}/{need.product}",
                        ),
                        source_coordinates=SourceCoordinates(str(need.product)),
                        fetch_window=need.fetch_window,
                    )
                    for need in needs
                )
            )

    class _IsoProvider:
        config = _sparse_config()
        window_declarations = _sparse_declarations()
        request_planner = _IsoPlanner()

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            del config
            st, pr = payload.station_products[0]
            s_def = _series_def(st, str(pr), provider_id="test_iso")
            fact = s_def.facts[0]
            val = 99.0 if fail_s1["flag"] else 10.0
            df = pl.DataFrame(
                {
                    "station_id": [st],
                    "product_id": [str(pr)],
                    "time": [datetime(2024, 6, 1, 0, 0)],
                    "value": [val],
                    "time_zone": ["+00:00"],
                    "series_id": [s_def.series_id],
                    "facts_id": [fact.facts_id],
                    "source_unit": [fact.normalized_unit],
                },
                schema=RowsSchema.polars_schema,
            )
            return ParsedSeries(
                rows=df,
                series=(s_def,),
                inventories=(
                    InventorySnapshot(
                        snapshot_id=f"inv:{st}:{pr}",
                        scope=payload.scope
                        or SeriesScope(provider_ids=("test_iso",), station_ids=(st,), product_ids=(str(pr),)),
                        members=(s_def.series_id,),
                        completeness=InventoryCompleteness.COMPLETE,
                        access="test",
                        origin="response",
                        window=SeriesWindow(
                            start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
                            end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
                        ),
                        evidence=("test",),
                    ),
                ),
                outcomes=(
                    RetrievalOutcome(
                        outcome_id=f"out:{st}:{pr}:{val}",
                        series_id=s_def.series_id,
                        station_id=st,
                        product_id=str(pr),
                        window=SeriesWindow(
                            start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
                            end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
                        ),
                        status=OutcomeStatus.SUCCESS,
                        facts_ids=(fact.facts_id,),
                    ),
                ),
            )

    pid = ProviderId("test_iso")
    store_dir = tmp_path / "iso_store"
    # Seed store for s1 and s2
    driver_module.drive(
        ObservationRequest(
            pid, ("s1", "s2"), (ProductId("flow"), ProductId("level")), _date_window("2024-06-01", "2024-06-01")
        ),
        _IsoProvider(),
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=_IsoTransport(),
        cache="refresh",
        store=store_dir,
    )
    # Refresh with s1 failing, s2 succeeding, and uncached s3 failing across both products via one shared call!
    fail_s1["flag"] = True
    refreshed = driver_module.drive(
        ObservationRequest(
            pid, ("s1", "s2", "s3"), (ProductId("flow"), ProductId("level")), _date_window("2024-06-01", "2024-06-01")
        ),
        _IsoProvider(),
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 2, 13)),
        transport=_IsoTransport(),
        cache="refresh",
        store=store_dir,
    )
    by_st = refreshed.canonical_rows.group_by("station_id").agg(pl.col("value").mean())
    vals = {row["station_id"]: row["value"] for row in by_st.iter_rows(named=True)}
    # s1 preserves held cached value (10.0) while s2 gets fresh refreshed value (99.0)
    assert vals == {"s1": 10.0, "s2": 99.0}
    # s3 shared failure recorded ONCE in calls_made with both (s3, flow) and (s3, level)
    shared_failed = [
        c for c in refreshed.provenance.calls_made if c.get("url") == "https://example.invalid/shared-fail"
    ]
    assert len(shared_failed) == 1
    assert set(shared_failed[0]["station_products"]) == {("s3", "flow"), ("s3", "level")}


def _ba_workbook_bytes(
    station: str, source_parameter: str, source_unit: str, rows: list[tuple[datetime, float | None]]
) -> bytes:
    from io import BytesIO

    import openpyxl

    doc = openpyxl.Workbook()
    sheet = doc.active
    assert sheet is not None
    for row in [
        ("#Station Name", f"Station {station}"),
        ("#Station Number", station),
        ("#Station Parameter Name", source_parameter),
        ("#Timeseries Name", "81 Web Kontinuirani"),
        ("#Unit Symbol", source_unit),
        ("#Rows", len(rows)),
        ("#", None),
        ("#Timestamp", "Value"),
        *rows,
    ]:
        sheet.append(row)
    stream = BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


def test_ba_fhmzbih_deduplicates_metadata_index_across_stations_and_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from rivretrieve._internal.providers.ba_fhmzbih import parse as ba_parse_mod
    from rivretrieve._internal.providers.ba_fhmzbih.declaration import declaration as ba_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import HttpMethod, TransportRequest, TransportResponse

    assert isinstance(ba_declaration.observations, LiveStages)
    stations = ("4024", "4110")
    products = (
        ProductId("discharge_reported"),
        ProductId("stage_reported"),
        ProductId("water_temperature_reported"),
    )
    meta_bytes = json.dumps(
        [
            {"metadata_station_no": "4024", "metadata_site_no": "site-4024"},
            {"metadata_station_no": "4110", "metadata_site_no": "site-4110"},
        ]
    ).encode()
    workbook_map = {
        ("4024", "Q"): _ba_workbook_bytes("4024", "Proticaj", "m³/s", [(datetime(2025, 9, 4, 0), 12.5)]),
        ("4024", "H"): _ba_workbook_bytes("4024", "Vodostaj", "cm", [(datetime(2025, 9, 4, 0), 110.0)]),
        ("4024", "WT"): _ba_workbook_bytes("4024", "Temperatura vode", "°C", [(datetime(2025, 9, 4, 0), 14.0)]),
        ("4110", "Q"): _ba_workbook_bytes("4110", "Proticaj", "m³/s", [(datetime(2025, 9, 4, 0), 22.5)]),
        ("4110", "H"): _ba_workbook_bytes("4110", "Vodostaj", "cm", [(datetime(2025, 9, 4, 0), 210.0)]),
        ("4110", "WT"): _ba_workbook_bytes("4110", "Temperatura vode", "°C", [(datetime(2025, 9, 4, 0), 15.0)]),
    }

    class _BaTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url.endswith("/index.json"):
                return TransportResponse(
                    url=request.url,
                    request_parameters=request.params or {},
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=meta_bytes,
                )
            for st in stations:
                for code, fname in (("Q", "Q_1Y.xlsx"), ("H", "H_1Y.xlsx"), ("WT", "Tvode_1Y.xlsx")):
                    if f"/{st}/{code}/{fname}" in request.url:
                        return TransportResponse(
                            url=request.url,
                            request_parameters=request.params or {},
                            status_code=200,
                            retrieved_at=_utc(2026, 1, 2, 12, 1),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            content=workbook_map[(st, code)],
                        )
            raise AssertionError(f"Unexpected URL: {request.url}")

    json_loads_calls = 0
    real_loads = ba_parse_mod.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal json_loads_calls
        json_loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ba_parse_mod.json, "loads", _counted_loads)
    transport = _BaTransport()
    pid = ProviderId("ba_fhmzbih")
    assembled = driver_module.drive(
        ObservationRequest(pid, stations, products, _date_window("2025-09-04", "2025-09-04")),
        ba_declaration.observations.stages,
        provenance=ObservationProvenance(source="ba", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 5)),
        transport=transport,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(transport.requests) == 7
    assert sum(1 for r in transport.requests if r.method is HttpMethod.GET and r.url.endswith("/index.json")) == 1
    assert json_loads_calls == 1
    assert len(assembled.provenance.calls_made) == 7
    assert len(assembled.receipts.entries) == 7
    assert all(e.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD for e in assembled.receipts.entries)
    assert assembled.issues == ()
    assert assembled.canonical_rows.height == 6
    assert {o.status for o in assembled.outcomes} == {OutcomeStatus.SUCCESS}
    assert len(assembled.inventories) == 6
    meta_calls = [c for c in assembled.provenance.calls_made if str(c["url"]).endswith("/index.json")]
    assert len(meta_calls) == 1
    assert len(meta_calls[0]["station_products"]) == 6
    workbook_calls = [c for c in assembled.provenance.calls_made if not str(c["url"]).endswith("/index.json")]
    assert len(workbook_calls) == 6
    meta_call_id = meta_calls[0]["call_id"]
    assert all(c["prerequisite_acquisition_ids"] == (meta_call_id,) for c in workbook_calls)


def test_ba_fhmzbih_isolates_missing_station_in_metadata_index_from_present_station() -> None:
    import json

    from rivretrieve._internal.providers.ba_fhmzbih.declaration import declaration as ba_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import TransportRequest, TransportResponse

    assert isinstance(ba_declaration.observations, LiveStages)
    stations = ("4024", "4110")
    products = (
        ProductId("discharge_reported"),
        ProductId("stage_reported"),
        ProductId("water_temperature_reported"),
    )
    # 4024 absent, 4110 present
    meta_bytes = json.dumps([{"metadata_station_no": "4110", "metadata_site_no": "site-4110"}]).encode()
    workbook_map = {
        ("4110", "Q"): _ba_workbook_bytes("4110", "Proticaj", "m³/s", [(datetime(2025, 9, 4, 0), 22.5)]),
        ("4110", "H"): _ba_workbook_bytes("4110", "Vodostaj", "cm", [(datetime(2025, 9, 4, 0), 210.0)]),
        ("4110", "WT"): _ba_workbook_bytes("4110", "Temperatura vode", "°C", [(datetime(2025, 9, 4, 0), 15.0)]),
    }

    class _BaTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url.endswith("/index.json"):
                return TransportResponse(
                    url=request.url,
                    request_parameters={},
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=meta_bytes,
                )
            for code, fname in (("Q", "Q_1Y.xlsx"), ("H", "H_1Y.xlsx"), ("WT", "Tvode_1Y.xlsx")):
                if f"/4110/{code}/{fname}" in request.url:
                    return TransportResponse(
                        url=request.url,
                        request_parameters={},
                        status_code=200,
                        retrieved_at=_utc(2026, 1, 2, 12, 1),
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        content=workbook_map[("4110", code)],
                    )
            raise AssertionError(f"Unexpected URL: {request.url}")

    transport = _BaTransport()
    pid = ProviderId("ba_fhmzbih")
    assembled = driver_module.drive(
        ObservationRequest(pid, stations, products, _date_window("2025-09-04", "2025-09-04")),
        ba_declaration.observations.stages,
        provenance=ObservationProvenance(source="ba", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 5)),
        transport=transport,
    )
    assert len(transport.requests) == 4
    by_pair = {(o.station_id, o.product_id): o.status for o in assembled.outcomes}
    for pr in products:
        assert by_pair[("4024", str(pr))] is OutcomeStatus.UNSUPPORTED
        assert by_pair[("4110", str(pr))] is OutcomeStatus.SUCCESS
    assert sorted(assembled.canonical_rows["station_id"].unique().to_list()) == ["4110"]
    assert assembled.canonical_rows.height == 3
    assert len(assembled.inventories) == 3
    assert sum(1 for i in assembled.issues if i.code == "unsupported_source_structure") == 3


def test_ba_fhmzbih_isolates_workbook_failure_and_corrupt_or_failed_metadata_index() -> None:
    import json

    from rivretrieve._internal.providers.ba_fhmzbih.declaration import declaration as ba_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import (
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
        TransportResponse,
    )

    assert isinstance(ba_declaration.observations, LiveStages)
    stations = ("4024", "4110")
    products = (
        ProductId("discharge_reported"),
        ProductId("stage_reported"),
        ProductId("water_temperature_reported"),
    )
    meta_bytes = json.dumps(
        [
            {"metadata_station_no": "4024", "metadata_site_no": "site-4024"},
            {"metadata_station_no": "4110", "metadata_site_no": "site-4110"},
        ]
    ).encode()
    workbook_map = {
        ("4024", "H"): _ba_workbook_bytes("4024", "Vodostaj", "cm", [(datetime(2025, 9, 4, 0), 110.0)]),
        ("4024", "WT"): _ba_workbook_bytes("4024", "Temperatura vode", "°C", [(datetime(2025, 9, 4, 0), 14.0)]),
        ("4110", "Q"): _ba_workbook_bytes("4110", "Proticaj", "m³/s", [(datetime(2025, 9, 4, 0), 22.5)]),
        ("4110", "H"): _ba_workbook_bytes("4110", "Vodostaj", "cm", [(datetime(2025, 9, 4, 0), 210.0)]),
        ("4110", "WT"): _ba_workbook_bytes("4110", "Temperatura vode", "°C", [(datetime(2025, 9, 4, 0), 15.0)]),
    }

    class _PartialWorkbookFailTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url.endswith("/index.json"):
                return TransportResponse(
                    url=request.url,
                    request_parameters={},
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=meta_bytes,
                )
            if "/4024/Q/" in request.url:
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            for st in stations:
                for code, fname in (("Q", "Q_1Y.xlsx"), ("H", "H_1Y.xlsx"), ("WT", "Tvode_1Y.xlsx")):
                    if f"/{st}/{code}/{fname}" in request.url:
                        return TransportResponse(
                            url=request.url,
                            request_parameters={},
                            status_code=200,
                            retrieved_at=_utc(2026, 1, 2, 12, 1),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            content=workbook_map[(st, code)],
                        )
            raise AssertionError(request.url)

    pid = ProviderId("ba_fhmzbih")
    t1 = _PartialWorkbookFailTransport()
    partial = driver_module.drive(
        ObservationRequest(pid, stations, products, _date_window("2025-09-04", "2025-09-04")),
        ba_declaration.observations.stages,
        provenance=ObservationProvenance(source="ba", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 5)),
        transport=t1,
    )
    assert len(t1.requests) == 7
    assert len(partial.provenance.calls_made) == 7
    by_pair = {(o.station_id, o.product_id): o.status for o in partial.outcomes}
    assert by_pair[("4024", "discharge_reported")] is OutcomeStatus.FAILED
    for pair in (
        ("4024", "stage_reported"),
        ("4024", "water_temperature_reported"),
        ("4110", "discharge_reported"),
        ("4110", "stage_reported"),
        ("4110", "water_temperature_reported"),
    ):
        assert by_pair[pair] is OutcomeStatus.SUCCESS
    assert partial.canonical_rows.height == 5

    # Case B: Corrupt index.json
    class _CorruptMetaTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            assert request.url.endswith("/index.json")
            return TransportResponse(
                url=request.url,
                request_parameters={},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=b"{not-json",
            )

    t2 = _CorruptMetaTransport()
    corrupt = driver_module.drive(
        ObservationRequest(pid, stations, products, _date_window("2025-09-04", "2025-09-04")),
        ba_declaration.observations.stages,
        provenance=ObservationProvenance(source="ba", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 5)),
        transport=t2,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(t2.requests) == 1
    assert len(corrupt.receipts.entries) == 1
    assert corrupt.receipts.entries[0].content == b"{not-json"
    assert len(corrupt.outcomes) == 6
    assert {o.status for o in corrupt.outcomes} == {OutcomeStatus.UNSUPPORTED}

    # Case C: Failed index.json (HTTP 503)
    class _FailedMetaTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)

    t3 = _FailedMetaTransport()
    failed = driver_module.drive(
        ObservationRequest(pid, stations, products, _date_window("2025-09-04", "2025-09-04")),
        ba_declaration.observations.stages,
        provenance=ObservationProvenance(source="ba", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 5)),
        transport=t3,
    )
    assert len(t3.requests) == 1
    assert len(failed.provenance.calls_made) == 1
    assert len(failed.outcomes) == 6
    assert {o.status for o in failed.outcomes} == {OutcomeStatus.FAILED}


def test_fr_hubeau_single_station_wire_parity_and_multi_station_batch_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from rivretrieve._internal.providers.fr_hubeau import parse as fr_parse_mod
    from rivretrieve._internal.providers.fr_hubeau.declaration import declaration as fr_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import TransportRequest, TransportResponse

    assert isinstance(fr_declaration.observations, LiveStages)
    stages = fr_declaration.observations.stages
    pid = ProviderId("fr_hubeau")

    class _RecorderTransport:
        def __init__(self, row_builder: object | None = None) -> None:
            self.requests: list[TransportRequest] = []
            self.row_builder = row_builder

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            rows = self.row_builder(request) if callable(self.row_builder) else []
            return TransportResponse(
                url=request.url,
                request_parameters=request.params or {},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"count": len(rows), "next": None, "data": rows}).encode(),
            )

    # 1. Single-station exact wire parity (daily & temperature)
    t_daily_1 = _RecorderTransport()
    driver_module.drive(
        ObservationRequest(
            pid, ("1011000101",), (ProductId("discharge_daily_mean"),), _date_window("2025-01-03", "2025-01-03")
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=t_daily_1,
    )
    assert len(t_daily_1.requests) == 1
    assert t_daily_1.requests[0].url == "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
    assert dict(t_daily_1.requests[0].params or {}) == {
        "code_entite": "1011000101",
        "date_debut_obs_elab": "2025-01-01",
        "date_fin_obs_elab": "2025-01-05",
        "grandeur_hydro_elab": "QmnJ",
        "size": 2500,
    }

    t_temp_1 = _RecorderTransport()
    driver_module.drive(
        ObservationRequest(
            pid, ("01001336",), (ProductId("water_temperature_reported"),), _date_window("2025-07-03", "2025-07-03")
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=t_temp_1,
    )
    assert len(t_temp_1.requests) == 1
    assert t_temp_1.requests[0].url == "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"
    assert dict(t_temp_1.requests[0].params or {}) == {
        "code_station": "01001336",
        "date_debut_mesure": "2025-07-01",
        "date_fin_mesure": "2025-07-05",
        "size": 2500,
    }

    # 2. Multi-station obs_elab batching: 3 stations -> 1 GET + 1 JSON decode; 55 stations -> 2 GETs (50 + 5)
    json_calls = 0
    real_loads = fr_parse_mod.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal json_calls
        json_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(fr_parse_mod.json, "loads", _counted_loads)
    t_daily_3 = _RecorderTransport(
        row_builder=lambda req: [
            {
                "code_station": st,
                "grandeur_hydro_elab": "QmnJ",
                "date_obs_elab": "2025-01-03",
                "resultat_obs_elab": 100.0 + i,
            }
            for i, st in enumerate(str((req.params or {})["code_entite"]).split(","))
        ]
    )
    res_3 = driver_module.drive(
        ObservationRequest(
            pid, ("S1", "S2", "S3"), (ProductId("discharge_daily_mean"),), _date_window("2025-01-03", "2025-01-03")
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=t_daily_3,
    )
    assert len(t_daily_3.requests) == 1
    assert (t_daily_3.requests[0].params or {})["code_entite"] == "S1,S2,S3"
    assert json_calls == 1
    assert res_3.canonical_rows.height == 3

    stations_55 = tuple(f"ST{i:03d}" for i in range(55))
    t_daily_55 = _RecorderTransport()
    driver_module.drive(
        ObservationRequest(
            pid, stations_55, (ProductId("discharge_daily_mean"),), _date_window("2025-01-03", "2025-01-03")
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=t_daily_55,
    )
    assert [len(str((r.params or {})["code_entite"]).split(",")) for r in t_daily_55.requests] == [50, 5]

    # 3. Workload-aware temperature batching: cap = max(1, min(50, 10_000 // (48 * days)))
    # 5 rendered days (padding +-2 around 2025-07-03..2025-07-03) -> cap 41 -> 10 stations in 1 GET
    t_temp_short = _RecorderTransport()
    driver_module.drive(
        ObservationRequest(
            pid,
            tuple(f"T{i:02d}" for i in range(10)),
            (ProductId("water_temperature_reported"),),
            _date_window("2025-07-03", "2025-07-03"),
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=t_temp_short,
    )
    assert [len(str((r.params or {})["code_station"]).split(",")) for r in t_temp_short.requests] == [10]

    # 30 rendered days (2025-07-03..2025-07-28 + +-2d padding = 2025-07-01..2025-07-30) -> cap 6 -> 15st in 3 GETs (6, 6, 3)
    t_temp_med = _RecorderTransport()
    driver_module.drive(
        ObservationRequest(
            pid,
            tuple(f"T{i:02d}" for i in range(15)),
            (ProductId("water_temperature_reported"),),
            _date_window("2025-07-03", "2025-07-28"),
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=t_temp_med,
    )
    assert [len(str((r.params or {})["code_station"]).split(",")) for r in t_temp_med.requests] == [6, 6, 3]

    # 215 rendered days -> cap 1 -> 3 stations in 3 individual GETs
    t_temp_long = _RecorderTransport()
    driver_module.drive(
        ObservationRequest(
            pid,
            ("T00", "T01", "T02"),
            (ProductId("water_temperature_reported"),),
            _date_window("2025-01-03", "2025-08-01"),
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=t_temp_long,
    )
    assert [len(str((r.params or {})["code_station"]).split(",")) for r in t_temp_long.requests] == [1, 1, 1]


def test_fr_hubeau_batched_out_of_order_annotations_complete_empty_and_reuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import json
    import sys

    from rivretrieve._internal.providers.fr_hubeau import parse as fr_parse_mod
    from rivretrieve._internal.providers.fr_hubeau.declaration import declaration as fr_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import TransportRequest, TransportResponse

    assert isinstance(fr_declaration.observations, LiveStages)
    stages = fr_declaration.observations.stages
    pid = ProviderId("fr_hubeau")
    next_url = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?cursor=p2&size=2500"

    class _PagedTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url == "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab":
                body = {
                    "count": 1,
                    "next": next_url,
                    "data": [
                        {
                            "code_station": "S1",
                            "grandeur_hydro_elab": "QmnJ",
                            "date_obs_elab": "2025-01-03",
                            "resultat_obs_elab": 100.0,
                            "code_statut": 4,
                            "libelle_statut": "Brute",
                            "code_qualification": 12,
                            "libelle_qualification": "Douteuse",
                            "code_methode": 0,
                            "libelle_methode": "Mesurée",
                        }
                    ],
                }
            elif request.url == next_url:
                body = {
                    "count": 2,
                    "next": None,
                    "data": [
                        {
                            "code_station": "S2",
                            "grandeur_hydro_elab": "QmnJ",
                            "date_obs_elab": "2025-01-03",
                            "resultat_obs_elab": 200.0,
                            "code_statut": 16,
                            "libelle_statut": "Validée",
                            "code_qualification": 20,
                            "libelle_qualification": "Bonne",
                            "code_methode": 8,
                            "libelle_methode": "Calculée",
                        },
                        {
                            "code_station": "S1",
                            "grandeur_hydro_elab": "QmnJ",
                            "date_obs_elab": "2025-01-04",
                            "resultat_obs_elab": 150.0,
                            "code_statut": 16,
                            "libelle_statut": "Validée",
                            "code_qualification": 20,
                            "libelle_qualification": "Bonne",
                            "code_methode": 0,
                            "libelle_methode": "Mesurée",
                        },
                    ],
                }
            else:
                raise AssertionError(request.url)
            return TransportResponse(
                url=request.url,
                request_parameters=request.params or {},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps(body).encode(),
            )

    json_calls = 0
    real_loads = fr_parse_mod.json.loads
    driver_parse_calls = 0
    real_parse = stages.parse

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal json_calls
        if sys._getframe(1).f_code.co_filename == fr_parse_mod.__file__:
            json_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(fr_parse_mod.json, "loads", _counted_loads)

    class _SpiedStages:
        config = stages.config
        window_declarations = stages.window_declarations
        request_planner = stages.request_planner

        @staticmethod
        def parse(payload: Payload, cfg: ProviderConfig) -> ParsedSeries:
            nonlocal driver_parse_calls
            driver_parse_calls += 1
            return real_parse(payload, cfg)

    transport = _PagedTransport()
    store_dir = tmp_path / "fr_store"
    req = ObservationRequest(
        pid,
        ("S1", "S2", "S3"),
        (ProductId("discharge_daily_mean"),),
        _date_window("2025-01-03", "2025-01-04"),
    )
    first = driver_module.drive(
        req,
        _SpiedStages(),
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 5)),
        transport=transport,
        cache="reuse",
        store=store_dir,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(transport.requests) == 2
    assert json_calls == 2
    assert driver_parse_calls == 0
    assert len(first.receipts.entries) == 2
    assert first.issues == ()
    assert sorted(first.canonical_rows["station_id"].to_list()) == ["S1", "S1", "S2"]
    ann = first.annotations.schema_table("fr_hubeau.obs_elab").sort("station_id", "time")
    assert ann["station_id"].to_list() == ["S1", "S1", "S2"]
    assert ann["code_statut"].to_list() == [4, 16, 16]
    by_st: dict[str, list[OutcomeStatus]] = {}
    for o in first.outcomes:
        by_st.setdefault(o.station_id, []).append(o.status)
    assert set(by_st["S1"]) == {OutcomeStatus.SUCCESS}
    assert set(by_st["S2"]) == {OutcomeStatus.SUCCESS}
    assert by_st["S3"] == [OutcomeStatus.EMPTY]
    s3_empty = next(o for o in first.outcomes if o.station_id == "S3" and o.status is OutcomeStatus.EMPTY)
    assert s3_empty.window == SeriesWindow(start=datetime(2025, 1, 3), end=datetime(2025, 1, 4, 23, 59, 59, 999999))
    assert len(s3_empty.calls) == 2
    # Closing scope with explicit series_ids lets reuse hit store cache across S1, S2, and empty S3 with 0 GETs!
    closed_req = replace(
        req,
        scope=SeriesScope(
            provider_ids=("fr_hubeau",),
            restriction=RestrictionKind.EXPLICIT,
            series_ids=tuple(s.series_id for s in first.source_series),
        ),
        known_series=first.source_series,
    )
    reused = driver_module.drive(
        closed_req,
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 10)),
        transport=transport,
        cache="reuse",
        store=store_dir,
    )
    assert len(transport.requests) == 2
    assert reused.canonical_rows.sort("station_id", "time").equals(first.canonical_rows.sort("station_id", "time"))


@pytest.mark.parametrize("failure_mode", ["http_503", "cursor_cycle", "foreign_station"])
def test_fr_hubeau_batch_failure_isolation_and_no_partial_or_foreign_leakage(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    import json

    from rivretrieve._internal.providers.fr_hubeau.declaration import declaration as fr_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import (
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
        TransportResponse,
    )

    assert isinstance(fr_declaration.observations, LiveStages)
    stages = fr_declaration.observations.stages
    pid = ProviderId("fr_hubeau")
    stations = tuple(f"ST{i:02d}" for i in range(52))  # Batch 1: ST00..ST49, Batch 2: ST50..ST51

    class _SeedTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            codes = str((request.params or {})["code_entite"]).split(",")
            data = [
                {
                    "code_station": st,
                    "grandeur_hydro_elab": "QmnJ",
                    "date_obs_elab": "2025-01-03",
                    "resultat_obs_elab": 10.0,
                }
                for st in codes
            ]
            return TransportResponse(
                url=request.url,
                request_parameters=request.params,
                status_code=200,
                retrieved_at=_utc(2026, 1, 1, 12),
                content_type="application/json",
                content=json.dumps({"count": len(data), "next": None, "data": data}).encode(),
            )

    store_dir = tmp_path / f"store_{failure_mode}"
    req = ObservationRequest(
        pid, stations, (ProductId("discharge_daily_mean"),), _date_window("2025-01-03", "2025-01-03")
    )
    seed = driver_module.drive(
        req,
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
        transport=_SeedTransport(),
        cache="refresh",
        store=store_dir,
    )
    assert seed.canonical_rows.height == 52

    next_b1 = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?cursor=b1p2"

    class _RefreshTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url == next_b1:
                if failure_mode == "http_503":
                    raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
                if failure_mode == "cursor_cycle":
                    return TransportResponse(
                        url=request.url,
                        request_parameters=request.params or {},
                        status_code=200,
                        retrieved_at=_utc(2026, 1, 2, 12),
                        content_type="application/json",
                        content=json.dumps({"data": [], "next": next_b1}).encode(),
                    )
                return TransportResponse(
                    url=request.url,
                    request_parameters=request.params or {},
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=json.dumps(
                        {
                            "data": [
                                {
                                    "code_station": "UNREQUESTED_FOREIGN",
                                    "grandeur_hydro_elab": "QmnJ",
                                    "date_obs_elab": "2025-01-03",
                                    "resultat_obs_elab": 999.0,
                                }
                            ],
                            "next": None,
                        }
                    ).encode(),
                )
            codes = str((request.params or {})["code_entite"]).split(",")
            is_batch1 = len(codes) == 50
            data = [
                {
                    "code_station": st,
                    "grandeur_hydro_elab": "QmnJ",
                    "date_obs_elab": "2025-01-03",
                    "resultat_obs_elab": 99.0,
                }
                for st in codes[: (2 if is_batch1 else 2)]
            ]
            return TransportResponse(
                url=request.url,
                request_parameters=request.params,
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"data": data, "next": next_b1 if is_batch1 else None}).encode(),
            )

    refreshed = driver_module.drive(
        req,
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 5)),
        transport=_RefreshTransport(),
        cache="refresh",
        store=store_dir,
        receipts=ReceiptMode.INCLUDE,
    )
    vals = dict(refreshed.canonical_rows.select("station_id", "value").iter_rows())
    # Batch 1 preserves held values (10.0 l/s -> 0.01 m3/s) without leaking fresh page-1 values (0.099 m3/s);
    # Batch 2 gets fresh values (99.0 l/s -> 0.099 m3/s).
    assert all(vals[f"ST{i:02d}"] == pytest.approx(0.01) for i in range(50))
    assert vals["ST50"] == pytest.approx(0.099)
    assert vals["ST51"] == pytest.approx(0.099)
    assert "UNREQUESTED_FOREIGN" not in vals
    by_st: dict[str, list[OutcomeStatus]] = {}
    for o in refreshed.outcomes:
        by_st.setdefault(o.station_id, []).append(o.status)
    for i in range(50):
        st = f"ST{i:02d}"
        assert OutcomeStatus.UNRESOLVED in by_st[st]
        assert all(
            o.retrieved_at == _utc(2026, 1, 1, 12)
            for o in refreshed.outcomes
            if o.station_id == st and o.status is OutcomeStatus.SUCCESS
        )
        assert OutcomeStatus.EMPTY not in by_st[st]
        unresolved = next(o for o in refreshed.outcomes if o.station_id == st and o.status is OutcomeStatus.UNRESOLVED)
        assert len(unresolved.calls) == 2
    assert set(by_st["ST50"]) == {OutcomeStatus.SUCCESS}
    assert set(by_st["ST51"]) == {OutcomeStatus.SUCCESS}
    assert len(refreshed.receipts.entries) >= 3


def _make_bg_syn_harness(tmp_path: Path):
    from datetime import date, time, timedelta

    from rivretrieve._internal.engine import WithIssues, _make_fetch_window
    from rivretrieve._internal.provider_series import (
        NATIVE_SCHEMA,
        SeriesMapping,
        UnsupportedSourceStructureError,
        parse_mapped_group,
    )
    from rivretrieve._internal.request_planning import (
        ConsumerNeed,
        ObservationPlan,
        PlannedLookup,
        PlannedObservationRequest,
    )
    from rivretrieve._internal.transport import (
        HttpMethod,
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
        TransportResponse,
    )

    stations = tuple(f"S{i:02d}" for i in range(68))
    products = (ProductId("flow"), ProductId("level"))
    mappings = {
        "flow": SeriesMapping(
            "bg_syn.flow",
            "discharge",
            "m3/s",
            "m3/s",
            "P1D",
            "mean",
            evidence=("test:bg_syn_flow",),
        ),
        "level": SeriesMapping(
            "bg_syn.level",
            "stage",
            "m",
            "m",
            "P1D",
            "instantaneous",
            evidence=("test:bg_syn_level",),
        ),
    }
    daily = Daily(DayDefinition("00:00"), DailyLabelTime("00:00"))
    cfg = ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId("flow"): ProductConfig(SourceCoordinates("bulletin_csv"), Unit.M3_S, daily),
            ProductId("level"): ProductConfig(SourceCoordinates("bulletin_csv"), Unit.M, daily),
        },
    )
    decl = WindowDeclaration(
        WindowGranularity("date"),
        WindowRenderingVocabulary.DATE,
        StopConvention.INCLUSIVE,
        fetch_padding=timedelta(0),
    )
    w_decls = ProductWindowDeclarations(dict.fromkeys(products, decl))
    decode_counter = {"count": 0}

    def _interpret_bulletin_group(
        payload: Payload,
        pair_payloads: Mapping[tuple[str, ProductId], Payload],
        provider_config: ProviderConfig,
    ) -> dict[tuple[str, ProductId], ParsedSeries]:
        decode_counter["count"] += 1
        text = payload.content.decode("utf-8")
        lines = [line for line in text.splitlines() if line]
        if not lines or lines[0] != "date,station,flow,level":
            raise UnsupportedSourceStructureError("Malformed CSV header")
        bulletin_day_str = payload.fetch_window.start.date
        day_dt = datetime.fromisoformat(bulletin_day_str)
        rows_by_station: dict[str, tuple[str, str]] = {}
        for line in lines[1:]:
            d_str, st, raw_flow, raw_level = line.split(",")
            if d_str != bulletin_day_str:
                raise UnsupportedSourceStructureError("Mismatched bulletin date")
            rows_by_station[st] = (raw_flow, raw_level)

        def _native_group(
            _p: Payload,
            matched: Mapping[tuple[str, ProductId], Payload],
            _cfg: ProviderConfig,
        ) -> Mapping[tuple[str, ProductId], WithIssues[Rows] | UnsupportedSourceStructureError]:
            out: dict[tuple[str, ProductId], WithIssues[Rows] | UnsupportedSourceStructureError] = {}
            for st, pr in matched:
                if st not in rows_by_station:
                    out[(st, pr)] = WithIssues(pl.DataFrame(schema=NATIVE_SCHEMA))
                    continue
                raw_flow, raw_level = rows_by_station[st]
                raw_cell = raw_flow if pr == ProductId("flow") else raw_level
                if raw_cell == "":
                    parsed_val: float | None = None
                else:
                    try:
                        parsed_val = float(raw_cell)
                    except ValueError:
                        out[(st, pr)] = UnsupportedSourceStructureError(
                            f"Malformed float cell {raw_cell!r} for {st}/{pr}"
                        )
                        continue
                df = pl.DataFrame(
                    [
                        {
                            "station_id": st,
                            "product_id": str(pr),
                            "time": day_dt,
                            "value": parsed_val,
                            "time_zone": "unknown",
                        }
                    ],
                    schema=NATIVE_SCHEMA,
                )
                out[(st, pr)] = WithIssues(df)
            return out

        return parse_mapped_group(
            payload,
            pair_payloads,
            provider_config,
            provider="bg_syn",
            mappings=mappings,
            native_parse_group=_native_group,
        )

    class _BgSynPlanner:
        def plan_lookups(self, needs: tuple[ConsumerNeed, ...], config: ProviderConfig) -> tuple[PlannedLookup, ...]:
            del needs, config
            return ()

        def plan_observations(
            self,
            needs: tuple[ConsumerNeed, ...],
            lookups: Mapping[object, object],
            config: ProviderConfig,
        ) -> ObservationPlan:
            del lookups, config
            reqs: list[PlannedObservationRequest] = []
            for need in needs:
                d_start = date.fromisoformat(need.fetch_window.start.date)
                d_end = date.fromisoformat(need.fetch_window.end.date)
                cur = d_start
                while cur <= d_end:
                    day_fw = _make_fetch_window(
                        WindowEndpoint.from_datetime(datetime.combine(cur, time.min)),
                        WindowEndpoint.from_datetime(datetime.combine(cur, time.max)),
                    )
                    reqs.append(
                        PlannedObservationRequest(
                            consumers=(need,),
                            request=TransportRequest(
                                HttpMethod.GET, f"https://example.invalid/bulletins/{cur.isoformat()}.csv"
                            ),
                            source_coordinates=SourceCoordinates("bulletin_csv"),
                            fetch_window=day_fw,
                            interpret_group=_interpret_bulletin_group,
                        )
                    )
                    cur += timedelta(days=1)
            return ObservationPlan(requests=tuple(reqs))

    class _BgSynProvider:
        config = cfg
        window_declarations = w_decls
        request_planner = _BgSynPlanner()

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            raise AssertionError("Driver should adopt pre-interpreted group results instead of calling parse()")

    class _BulletinTransport:
        def __init__(
            self,
            *,
            flow_offset: float = 0.0,
            level_offset: float = 0.0,
            retrieved_at: datetime | None = None,
            fail_dates: set[str] | None = None,
            cell_overrides: dict[tuple[str, str, str], str] | None = None,
        ) -> None:
            self.flow_offset = flow_offset
            self.level_offset = level_offset
            self.retrieved_at = retrieved_at or _utc(2026, 1, 1, 12)
            self.fail_dates = fail_dates or set()
            self.cell_overrides = cell_overrides or {}
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            day_str = request.url.rsplit("/", 1)[-1].removesuffix(".csv")
            if day_str in self.fail_dates:
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=404)
            day_num = int(day_str.rsplit("-", 1)[-1])
            lines = ["date,station,flow,level"]
            for idx, st in enumerate(stations):
                f_val = self.cell_overrides.get((day_str, st, "flow"), f"{idx + day_num + self.flow_offset:.1f}")
                l_val = self.cell_overrides.get(
                    (day_str, st, "level"), f"{100 + idx + day_num + self.level_offset:.1f}"
                )
                lines.append(f"{day_str},{st},{f_val},{l_val}")
            return TransportResponse(
                url=request.url,
                request_parameters={},
                status_code=200,
                retrieved_at=self.retrieved_at,
                content_type="text/csv",
                content="\n".join(lines).encode("utf-8"),
            )

    def explicit_scope_and_series(
        pair_subset: tuple[tuple[str, ProductId], ...] | None = None,
    ) -> tuple[SeriesScope, tuple[SourceSeries, ...]]:
        pairs = pair_subset or tuple((st, pr) for st in stations for pr in products)
        defs = tuple(mappings[str(pr)].source_series("bg_syn", st, str(pr)) for st, pr in pairs)
        scope = SeriesScope(
            provider_ids=("bg_syn",),
            restriction=RestrictionKind.EXPLICIT,
            series_ids=tuple(d.series_id for d in defs),
        )
        return scope, defs

    return (
        ProviderId("bg_syn"),
        stations,
        products,
        _BgSynProvider(),
        _BulletinTransport,
        decode_counter,
        explicit_scope_and_series,
        tmp_path,
    )


def test_bg_nimh_shaped_68_stations_cold_reuse_bypass_refresh_and_sparse(tmp_path: Path) -> None:
    pid, stations, products, provider, make_transport, decodes, explicit_scope_and_series, root = _make_bg_syn_harness(
        tmp_path
    )
    scope_all, defs_all = explicit_scope_and_series()
    req_all = ObservationRequest(
        pid,
        stations,
        products,
        _date_window("2024-06-01", "2024-06-30"),
        scope=scope_all,
        known_series=defs_all,
    )
    store_dir = root / "store_full"

    # 1. Cold cache: 68st x 2prod x 30d = 30 GETs, 30 decodes, 30 calls_made, 30 receipts, 4080 rows
    t1 = make_transport(retrieved_at=_utc(2026, 1, 1, 12))
    decodes["count"] = 0
    cold = driver_module.drive(
        req_all,
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 12, 5)),
        transport=t1,
        cache="reuse",
        store=store_dir,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(t1.requests) == 30
    assert decodes["count"] == 30
    assert len(cold.provenance.calls_made) == 30
    assert len(cold.receipts.entries) == 30
    assert all(e.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD for e in cold.receipts.entries)
    assert cold.canonical_rows.height == 68 * 2 * 30
    assert cold.issues == ()
    assert {o.series_id for o in cold.outcomes} == {d.series_id for d in defs_all}
    assert {o.status for o in cold.outcomes} == {OutcomeStatus.SUCCESS}

    # 2. Full cache reuse: 0 GETs, 0 decodes, STORE_EXCERPT receipt, identical rows
    t2 = make_transport()
    decodes["count"] = 0
    reused = driver_module.drive(
        req_all,
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 13)),
        transport=t2,
        cache="reuse",
        store=store_dir,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(t2.requests) == 0
    assert decodes["count"] == 0
    assert {c["call_id"] for c in reused.provenance.calls_made} == {c["call_id"] for c in cold.provenance.calls_made}
    assert reused.receipts.entries
    assert all(e.authorship is ReceiptAuthorship.STORE_EXCERPT for e in reused.receipts.entries)
    assert reused.canonical_rows.sort("series_id", "time").equals(cold.canonical_rows.sort("series_id", "time"))

    # 3a. Mixed cache reuse (Vision line 9): seed A.flow + B.level at t1; request (A,B)x(flow,level) at t2
    mixed_store = root / "store_mixed"
    cached_pairs = (("S00", ProductId("flow")), ("S01", ProductId("level")))
    cached_scope, cached_defs = explicit_scope_and_series(cached_pairs)
    driver_module.drive(
        ObservationRequest(
            pid,
            ("S00", "S01"),
            products,
            _date_window("2024-06-01", "2024-06-30"),
            scope=cached_scope,
            known_series=cached_defs,
            station_products=cached_pairs,
        ),
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
        transport=make_transport(flow_offset=0.0, level_offset=0.0, retrieved_at=_utc(2026, 1, 1, 12)),
        cache="reuse",
        store=mixed_store,
    )
    four_scope, four_defs = explicit_scope_and_series(
        (
            ("S00", ProductId("flow")),
            ("S00", ProductId("level")),
            ("S01", ProductId("flow")),
            ("S01", ProductId("level")),
        )
    )
    t_mixed = make_transport(flow_offset=500.0, level_offset=500.0, retrieved_at=_utc(2026, 1, 2, 12))
    decodes["count"] = 0
    mixed_res = driver_module.drive(
        ObservationRequest(
            pid,
            ("S00", "S01"),
            products,
            _date_window("2024-06-01", "2024-06-30"),
            scope=four_scope,
            known_series=four_defs,
        ),
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 2, 12, 5)),
        transport=t_mixed,
        cache="reuse",
        store=mixed_store,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(t_mixed.requests) == 30
    assert decodes["count"] == 30
    # Cached S00.flow and S01.level keep original t1 values (offset 0) & original retrieval instant
    s00_flow_vals = (
        mixed_res.canonical_rows.filter((pl.col("station_id") == "S00") & (pl.col("product_id") == "flow"))
        .sort("time")["value"]
        .to_list()
    )
    s01_level_vals = (
        mixed_res.canonical_rows.filter((pl.col("station_id") == "S01") & (pl.col("product_id") == "level"))
        .sort("time")["value"]
        .to_list()
    )
    # Uncached S00.level and S01.flow get fresh t2 values (offset +500)
    s00_level_vals = (
        mixed_res.canonical_rows.filter((pl.col("station_id") == "S00") & (pl.col("product_id") == "level"))
        .sort("time")["value"]
        .to_list()
    )
    s01_flow_vals = (
        mixed_res.canonical_rows.filter((pl.col("station_id") == "S01") & (pl.col("product_id") == "flow"))
        .sort("time")["value"]
        .to_list()
    )
    assert s00_flow_vals[0] == 1.0
    assert s01_level_vals[0] == 102.0
    assert s00_level_vals[0] == 601.0
    assert s01_flow_vals[0] == 502.0
    served_by_series = {item.series_id: item.retrieved_at for item in mixed_res.provenance.served_intervals}
    assert served_by_series[cached_defs[0].series_id] == _utc(2026, 1, 1, 12)
    assert served_by_series[cached_defs[1].series_id] == _utc(2026, 1, 1, 12)
    assert any(e.authorship is ReceiptAuthorship.STORE_EXCERPT for e in mixed_res.receipts.entries)
    assert sum(1 for e in mixed_res.receipts.entries if e.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD) == 30

    # 3b. Date range mixed follow-up: seed 68x2 for days 1-15 -> reread days 1-15 (0 GETs), read days 16-30 (15 GETs)
    split_store = root / "store_split"
    driver_module.drive(
        ObservationRequest(
            pid, stations, products, _date_window("2024-06-01", "2024-06-15"), scope=scope_all, known_series=defs_all
        ),
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
        transport=make_transport(),
        cache="reuse",
        store=split_store,
    )
    t_hit = make_transport()
    driver_module.drive(
        ObservationRequest(
            pid, stations, products, _date_window("2024-06-01", "2024-06-15"), scope=scope_all, known_series=defs_all
        ),
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 13)),
        transport=t_hit,
        cache="reuse",
        store=split_store,
    )
    assert len(t_hit.requests) == 0
    t_tail = make_transport()
    decodes["count"] = 0
    tail = driver_module.drive(
        ObservationRequest(
            pid, stations, products, _date_window("2024-06-16", "2024-06-30"), scope=scope_all, known_series=defs_all
        ),
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 14)),
        transport=t_tail,
        cache="reuse",
        store=split_store,
    )
    assert len(t_tail.requests) == 15
    assert decodes["count"] == 15
    assert tail.canonical_rows.height == 68 * 2 * 15

    # 4. cache="bypass" leaves empty store untouched; cache="refresh" overwrites held store values cleanly
    bypass_store = root / "store_bypass"
    t_bypass = make_transport()
    driver_module.drive(
        req_all,
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
        transport=t_bypass,
        cache="bypass",
        store=bypass_store,
    )
    assert len(t_bypass.requests) == 30
    assert not bypass_store.exists() or not list(bypass_store.rglob("*.parquet"))

    t_refresh = make_transport(flow_offset=1000.0, level_offset=1000.0, retrieved_at=_utc(2026, 1, 3, 12))
    refreshed = driver_module.drive(
        req_all,
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 3, 12, 5)),
        transport=t_refresh,
        cache="refresh",
        store=store_dir,
    )
    assert len(t_refresh.requests) == 30
    assert (
        refreshed.canonical_rows.filter((pl.col("station_id") == "S00") & (pl.col("product_id") == "flow")).sort(
            "time"
        )["value"][0]
        == 1001.0
    )

    # 5. Sparse station_products & explicit series_ids still make 30 GETs (not 60) and leak 0 extra pairs
    t_sparse = make_transport()
    decodes["count"] = 0
    sparse = driver_module.drive(
        ObservationRequest(
            pid,
            stations,
            products,
            _date_window("2024-06-01", "2024-06-30"),
            scope=cached_scope,
            known_series=cached_defs,
            station_products=cached_pairs,
        ),
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
        transport=t_sparse,
    )
    assert len(t_sparse.requests) == 30
    assert decodes["count"] == 30
    assert sparse.canonical_rows.height == 60
    assert set(sparse.canonical_rows.select("station_id", "product_id").iter_rows()) == {
        ("S00", "flow"),
        ("S01", "level"),
    }
    assert {s.series_id for s in sparse.source_series} == {d.series_id for d in cached_defs}
    assert {o.series_id for o in sparse.outcomes} == {d.series_id for d in cached_defs}


def test_bg_nimh_shaped_missing_bulletin_date_and_null_vs_malformed_cell_isolation(tmp_path: Path) -> None:
    pid, stations, products, provider, make_transport, decodes, explicit_scope_and_series, root = _make_bg_syn_harness(
        tmp_path
    )
    scope_all, defs_all = explicit_scope_and_series()

    # 6. Missing bulletin date isolation: day 15 returns HTTP 404; other 29 days succeed (3944 rows)
    t_missing = make_transport(fail_dates={"2024-06-15"})
    decodes["count"] = 0
    missing = driver_module.drive(
        ObservationRequest(
            pid, stations, products, _date_window("2024-06-01", "2024-06-30"), scope=scope_all, known_series=defs_all
        ),
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
        transport=t_missing,
        cache="reuse",
        store=root / "store_missing",
    )
    assert len(t_missing.requests) == 30
    assert decodes["count"] == 29
    assert missing.canonical_rows.height == 68 * 2 * 29
    failed_calls = [c for c in missing.provenance.calls_made if c.get("status_code") == 404]
    assert len(failed_calls) == 1
    assert len(failed_calls[0]["station_products"]) == 136
    assert sum(1 for o in missing.outcomes if o.status is OutcomeStatus.FAILED) == 136
    assert sum(1 for o in missing.outcomes if o.status is OutcomeStatus.SUCCESS) == 136 * 29

    # 7. Unmeasured null cell vs malformed cell isolation on 2024-06-10
    overrides = {
        ("2024-06-10", "S00", "flow"): "",  # blank unmeasured null cell -> admitted as None + SUCCESS
        ("2024-06-10", "S01", "level"): "NOT_A_FLOAT",  # malformed -> isolates ONLY (S01, level) on day 10
    }
    t_cells = make_transport(cell_overrides=overrides)
    cells_res = driver_module.drive(
        ObservationRequest(
            pid, stations, products, _date_window("2024-06-01", "2024-06-30"), scope=scope_all, known_series=defs_all
        ),
        provider,
        provenance=ObservationProvenance(source="bg", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
        transport=t_cells,
    )
    assert len(t_cells.requests) == 30
    # Total rows: 68*2*30 - 1 (S01, level on 2024-06-10 excluded; S00, flow on 2024-06-10 admitted with null value)
    assert cells_res.canonical_rows.height == 68 * 2 * 30 - 1
    s00_day10 = cells_res.canonical_rows.filter(
        (pl.col("station_id") == "S00") & (pl.col("product_id") == "flow") & (pl.col("time") == datetime(2024, 6, 10))
    )
    assert s00_day10.height == 1
    assert s00_day10["value"].to_list() == [None]
    s01_level_rows = cells_res.canonical_rows.filter(
        (pl.col("station_id") == "S01") & (pl.col("product_id") == "level")
    )
    assert s01_level_rows.height == 29
    bad_outcomes = [o for o in cells_res.outcomes if o.status is OutcomeStatus.UNSUPPORTED]
    assert len(bad_outcomes) == 1
    assert (bad_outcomes[0].station_id, bad_outcomes[0].product_id) == ("S01", "level")
    assert len(cells_res.issues) == 1
    assert cells_res.issues[0].code == "unsupported_source_structure"


def test_driver_clips_acquired_empty_outcomes_without_duplicate_or_padding_leakage() -> None:
    from datetime import timedelta

    from rivretrieve._internal.request_planning import (
        BatchPageStep,
        BatchPaginationSpec,
        ConsumerNeed,
        ObservationPlan,
        PlannedLookup,
        PlannedObservationRequest,
        UnseenConsumerEvidence,
    )
    from rivretrieve._internal.transport import HttpMethod, TransportRequest, TransportResponse

    pid = ProviderId("test_padding_empty")
    cfg = _sparse_config()
    padded_decl = WindowDeclaration(
        WindowGranularity("date"),
        WindowRenderingVocabulary.DATE,
        StopConvention.INCLUSIVE,
        fetch_padding=timedelta(days=2),
    )
    decls = ProductWindowDeclarations({ProductId("flow"): padded_decl, ProductId("level"): padded_decl})
    s_flow = _series_def("S1", "flow", provider_id="test_padding_empty")
    s_pad = _series_def("S2", "flow", provider_id="test_padding_empty")

    class _PaddingTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            del request
            return TransportResponse(
                url="https://example.invalid/empty",
                request_parameters={},
                status_code=200,
                retrieved_at=_utc(2026, 1, 1, 12),
                content_type="application/json",
                content=b"{}",
            )

    class _PaddingPlanner:
        def plan_lookups(self, needs: tuple[ConsumerNeed, ...], config: ProviderConfig) -> tuple[PlannedLookup, ...]:
            del needs, config
            return ()

        def plan_observations(
            self, needs: tuple[ConsumerNeed, ...], lookups: Mapping[object, object], config: ProviderConfig
        ) -> ObservationPlan:
            del lookups, config

            def _step(payload: Payload, consumers: tuple[ConsumerNeed, ...], cfg: ProviderConfig) -> BatchPageStep:
                del payload, cfg
                return BatchPageStep(
                    interpretations={
                        (n.station, n.product): ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())
                        for n in consumers
                    }
                )

            def _finalize(
                need: ConsumerNeed, payloads: tuple[Payload, ...], cfg: ProviderConfig
            ) -> UnseenConsumerEvidence:
                del cfg
                s_def = s_flow if need.station == "S1" else s_pad
                # S2's EMPTY window lies completely inside the -2d..-1d padding before requested 2025-01-03..2025-01-03.
                empty_win = (
                    SeriesWindow(start=datetime(2025, 1, 1), end=datetime(2025, 1, 5))
                    if need.station == "S1"
                    else SeriesWindow(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2))
                )
                return UnseenConsumerEvidence(
                    series=(s_def,),
                    outcomes=(
                        RetrievalOutcome(
                            outcome_id=stable_id("raw-empty", need.station, payloads[0].acquisition_id),
                            series_id=s_def.series_id,
                            station_id=need.station,
                            product_id=str(need.product),
                            window=empty_win,
                            status=OutcomeStatus.EMPTY,
                            facts_ids=(s_def.facts[0].facts_id,),
                            calls=(payloads[0].acquisition_id,),
                        ),
                    ),
                )

            return ObservationPlan(
                requests=(
                    PlannedObservationRequest(
                        consumers=needs,
                        request=TransportRequest(HttpMethod.GET, "https://example.invalid/empty"),
                        source_coordinates=SourceCoordinates("flow"),
                        fetch_window=needs[0].fetch_window,
                        pagination=BatchPaginationSpec(step_page=_step, finalize_unseen_consumer=_finalize),
                    ),
                )
            )

    class _Provider:
        config = cfg
        window_declarations = decls
        request_planner = _PaddingPlanner()

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            raise AssertionError("fallback parse must not run")

    res = driver_module.drive(
        ObservationRequest(pid, ("S1", "S2"), (ProductId("flow"),), _date_window("2025-01-03", "2025-01-03")),
        _Provider(),
        provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
        transport=_PaddingTransport(),
        cache="bypass",
    )
    s1_empties = [o for o in res.outcomes if o.station_id == "S1" and o.status is OutcomeStatus.EMPTY]
    assert len(s1_empties) == 1
    assert s1_empties[0].window == SeriesWindow(
        start=datetime(2025, 1, 3), end=datetime(2025, 1, 3, 23, 59, 59, 999999)
    )
    assert [o for o in res.outcomes if o.station_id == "S2" and o.status is OutcomeStatus.EMPTY] == []
    # S2's padding-only EMPTY outcome must NOT leak into result.outcomes!
    s2_empties = [o for o in res.outcomes if o.station_id == "S2" and o.status is OutcomeStatus.EMPTY]
    assert s2_empties == []


def test_fr_hubeau_unmatched_explicit_scope_and_malformed_empty_page_handling() -> None:
    import json

    from rivretrieve._internal.providers.fr_hubeau.declaration import declaration as fr_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import TransportRequest, TransportResponse

    assert isinstance(fr_declaration.observations, LiveStages)
    stages = fr_declaration.observations.stages
    pid = ProviderId("fr_hubeau")

    # 1. Mixed batch: S2 has explicit variant="NO_SUCH" -> 200 empty response must NOT fabricate S2 EMPTY or claim S2 member.
    class _EmptyTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                url=request.url,
                request_parameters=request.params or {},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"count": 0, "next": None, "data": []}).encode(),
            )

    res_mixed = driver_module.drive(
        ObservationRequest(
            pid,
            ("S1", "S2"),
            (ProductId("discharge_daily_mean"),),
            _date_window("2025-01-03", "2025-01-03"),
            scope=SeriesScope(
                provider_ids=("fr_hubeau",),
                restriction=RestrictionKind.EXPLICIT,
                variants=("NO_SUCH",),
            ),
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=_EmptyTransport(),
    )
    assert [o for o in res_mixed.outcomes if o.status is OutcomeStatus.EMPTY] == []
    assert all(not inv.members for inv in res_mixed.inventories)

    # 2. Malformed b"{}" page when all batch consumers have unmatched explicit variant -> must NOT swallow page_error!
    class _MalformedTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                url=request.url,
                request_parameters=request.params or {},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=b"{}",
            )

    res_malformed = driver_module.drive(
        ObservationRequest(
            pid,
            ("S1", "S2"),
            (ProductId("discharge_daily_mean"),),
            _date_window("2025-01-03", "2025-01-03"),
            scope=SeriesScope(
                provider_ids=("fr_hubeau",),
                restriction=RestrictionKind.EXPLICIT,
                variants=("NO_SUCH",),
            ),
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=_MalformedTransport(),
    )
    assert any(o.status is OutcomeStatus.UNRESOLVED for o in res_malformed.outcomes)
    assert all(
        "NO_SUCH" in (o.reason or "") or "incomplete" in (o.reason or "") or "data" in (o.reason or "")
        for o in res_malformed.outcomes
    )
    assert any("data" in (o.reason or "").lower() for o in res_malformed.outcomes)


def test_fr_hubeau_temperature_batched_annotations_and_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import sys

    from rivretrieve._internal.providers.fr_hubeau import parse as fr_parse_mod
    from rivretrieve._internal.providers.fr_hubeau.declaration import declaration as fr_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import TransportRequest, TransportResponse

    assert isinstance(fr_declaration.observations, LiveStages)
    stages = fr_declaration.observations.stages
    pid = ProviderId("fr_hubeau")
    next_url = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique?page=2&size=2500"

    class _TempTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url == next_url:
                body = {
                    "count": 2,
                    "next": None,
                    "data": [
                        {
                            "code_station": "T2",
                            "code_parametre": "1301",
                            "symbole_unite": "°C",
                            "code_unite": "27",
                            "date_mesure_temp": "2025-07-03",
                            "heure_mesure_temp": "12:00:00",
                            "resultat": 18.5,
                            "code_qualification": "1",
                            "libelle_qualification": "Correcte",
                        },
                        {
                            "code_station": "T1",
                            "code_parametre": "1301",
                            "symbole_unite": "°C",
                            "code_unite": "27",
                            "date_mesure_temp": "2025-07-03",
                            "heure_mesure_temp": "14:00:00",
                            "resultat": 19.25,
                            "code_qualification": "2",
                            "libelle_qualification": "Incertaine",
                        },
                    ],
                }
            else:
                body = {
                    "count": 1,
                    "next": next_url,
                    "data": [
                        {
                            "code_station": "T1",
                            "code_parametre": "1301",
                            "symbole_unite": "°C",
                            "code_unite": "27",
                            "date_mesure_temp": "2025-07-03",
                            "heure_mesure_temp": "10:00:00",
                            "resultat": 17.0,
                            "code_qualification": "1",
                            "libelle_qualification": "Correcte",
                        }
                    ],
                }
            return TransportResponse(
                url=request.url,
                request_parameters=request.params or {},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps(body).encode(),
            )

    json_calls = 0
    real_loads = fr_parse_mod.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal json_calls
        if sys._getframe(1).f_code.co_filename == fr_parse_mod.__file__:
            json_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(fr_parse_mod.json, "loads", _counted_loads)
    t = _TempTransport()
    res = driver_module.drive(
        ObservationRequest(
            pid,
            ("T1", "T2", "T3"),
            (ProductId("water_temperature_reported"),),
            _date_window("2025-07-03", "2025-07-03T23:59:59"),
        ),
        stages,
        provenance=ObservationProvenance(source="fr", provider_id=pid, requested_at=_utc(2026, 1, 2, 12)),
        transport=t,
    )
    assert len(t.requests) == 2
    assert json_calls == 2
    assert res.canonical_rows.sort("station_id", "time")["value"].to_list() == [17.0, 19.25, 18.5]
    ann = res.annotations.schema_table("fr_hubeau.temperature_chronique").sort("station_id", "time")
    assert ann["code_qualification"].to_list() == ["1", "2", "1"]
    t3_outcomes = [o for o in res.outcomes if o.station_id == "T3"]
    assert len(t3_outcomes) == 1
    assert t3_outcomes[0].status is OutcomeStatus.EMPTY


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_rr_fetch_bosnia_and_france_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import json

    import rivretrieve as rr
    from rivretrieve._internal.transport import TransportRequest, TransportResponse

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    # 1. Bosnia Vision §2 public test: 2 stations x 3 products, cache="bypass", receipts=True -> 7 GETs & 7 receipts
    ba_index = json.dumps(
        [
            {"metadata_station_no": "1010", "metadata_site_no": "site-a"},
            {"metadata_station_no": "1020", "metadata_site_no": "site-b"},
        ]
    ).encode()
    ba_wb_params = {
        "H_1Y.xlsx": ("Vodostaj", "cm"),
        "Q_1Y.xlsx": ("Proticaj", "m³/s"),
        "Tvode_1Y.xlsx": ("Temperatura vode", "°C"),
    }

    class _BosniaTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url.endswith("index.json"):
                body = ba_index
                ctype = "application/json"
            else:
                parts = request.url.split("/")
                station = parts[-3]
                fname = parts[-1]
                param_name, unit_sym = ba_wb_params[fname]
                val = {"1010": 100.0, "1020": 200.0}[station]
                body = _ba_workbook_bytes(station, param_name, unit_sym, [(datetime(2024, 6, 11, 12, 0), val)])
                ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            return TransportResponse(
                url=request.url,
                request_parameters=request.params or {},
                status_code=200,
                retrieved_at=_utc(2026, 1, 1, 12),
                content_type=ctype,
                content=body,
            )

    t_ba = _BosniaTransport()
    monkeypatch.setattr(discovery_module, "HttpClient", lambda: t_ba)
    ba_sel = rr.find(provider="ba_fhmzbih", station=("1010", "1020"))
    ba_res = rr.fetch(ba_sel, start="2024-06-11", end="2024-06-12", cache="bypass", receipts=True, on_issue="raise")
    assert len(t_ba.requests) == 7
    assert len(ba_res.receipts.entries) == 7
    assert ba_res.data.height == 6

    # 2. France public rr.fetch: cold, mixed cache reuse, refresh, sparse
    class _FrTransport:
        def __init__(self, *, offset: float = 0.0, retrieved_at: datetime | None = None) -> None:
            self.requests: list[TransportRequest] = []
            self.offset = offset
            self.retrieved_at = retrieved_at or _utc(2026, 1, 1, 12)

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = request.params or {}
            codes = str(params["code_entite"]).split(",")
            field = str(params["grandeur_hydro_elab"])
            start_d = str(params.get("date_debut_obs_elab") or "2024-06-11")
            end_d = str(params.get("date_fin_obs_elab") or start_d)
            days = [d for d in ("2024-06-11", "2024-06-12") if start_d <= d <= end_d]
            data = [
                {
                    "code_station": st,
                    "grandeur_hydro_elab": field,
                    "date_obs_elab": day,
                    "resultat_obs_elab": (1000.0 if field == "QmnJ" else 2000.0) + self.offset + idx,
                }
                for idx, st in enumerate(codes)
                for day in days
            ]
            return TransportResponse(
                url=request.url,
                request_parameters=dict(params),
                status_code=200,
                retrieved_at=self.retrieved_at,
                content_type="application/json",
                content=json.dumps({"count": len(data), "next": None, "data": data}).encode(),
            )

    # 2. France public rr.fetch: cold, mixed cache reuse, full reuse, refresh
    fr_sel_one = rr.find(
        provider="fr_hubeau", station="1011000101", quantity="discharge", frequency="P1D", statistic="mean"
    )
    fr_sel_two = rr.find(
        provider="fr_hubeau", station="J261401001", quantity="discharge", frequency="P1D", statistic="mean"
    )
    t_fr_seed = _FrTransport(offset=0.0, retrieved_at=_utc(2026, 1, 1, 12))
    monkeypatch.setattr(discovery_module, "HttpClient", lambda: t_fr_seed)
    fr_seed_1 = rr.fetch(
        fr_sel_one, start="2024-06-11", end="2024-06-12", cache="reuse", receipts=True, on_issue="raise"
    )
    fr_seed_2 = rr.fetch(
        fr_sel_two, start="2024-06-11", end="2024-06-11", cache="reuse", receipts=True, on_issue="raise"
    )
    assert len(t_fr_seed.requests) == 2
    assert fr_seed_1.data.height == 2
    assert fr_seed_2.data.height == 1

    # Mixed cache hit (1011000101 complete for 06-11..12 at t1; J261401001 misses 06-12 -> only J261401001 GET at t2)
    fr_sel_both = rr.find(
        provider="fr_hubeau",
        station=("1011000101", "J261401001"),
        quantity="discharge",
        frequency="P1D",
        statistic="mean",
    )
    fr_closed_both = rr.pick(
        fr_sel_both,
        series_id=(rr.series(fr_seed_1)["series_id"][0], rr.series(fr_seed_2)["series_id"][0]),
    )
    t_fr_mixed = _FrTransport(offset=500.0, retrieved_at=_utc(2026, 1, 2, 12))
    monkeypatch.setattr(discovery_module, "HttpClient", lambda: t_fr_mixed)
    fr_mixed = rr.fetch(
        fr_closed_both, start="2024-06-11", end="2024-06-12", cache="reuse", receipts=True, on_issue="raise"
    )
    assert len(t_fr_mixed.requests) == 1
    assert (t_fr_mixed.requests[0].params or {})["code_entite"] == "J261401001"
    vals_by_pair_day = {
        (r["station_id"], r["time"].date().isoformat()): r["value"]
        for r in fr_mixed.data.select("station_id", "time", "value").to_dicts()
    }
    assert vals_by_pair_day[("1011000101", "2024-06-11")] == pytest.approx(1.0)
    assert vals_by_pair_day[("1011000101", "2024-06-12")] == pytest.approx(1.0)
    assert vals_by_pair_day[("J261401001", "2024-06-11")] == pytest.approx(1.5)
    assert vals_by_pair_day[("J261401001", "2024-06-12")] == pytest.approx(1.5)

    # Full reuse -> 0 GETs; refresh -> 1 batched GET for both stations
    t_fr_hit = _FrTransport()
    monkeypatch.setattr(discovery_module, "HttpClient", lambda: t_fr_hit)
    fr_hit = rr.fetch(
        fr_closed_both, start="2024-06-11", end="2024-06-12", cache="reuse", receipts=True, on_issue="raise"
    )
    assert len(t_fr_hit.requests) == 0
    assert fr_hit.data.height == 4

    t_fr_refresh = _FrTransport(offset=1000.0, retrieved_at=_utc(2026, 1, 3, 12))
    monkeypatch.setattr(discovery_module, "HttpClient", lambda: t_fr_refresh)
    fr_refresh = rr.fetch(
        fr_closed_both, start="2024-06-11", end="2024-06-12", cache="refresh", receipts=True, on_issue="raise"
    )
    assert len(t_fr_refresh.requests) == 1
    assert set(str((t_fr_refresh.requests[0].params or {})["code_entite"]).split(",")) == {"1011000101", "J261401001"}
    assert fr_refresh.data.filter(pl.col("time").dt.date().cast(pl.String) == "2024-06-11").sort("station_id")[
        "value"
    ].to_list() == [pytest.approx(2.0), pytest.approx(2.001)]


def test_request_planning_contract_hardening_and_memory_release() -> None:
    import gc
    import tracemalloc

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.request_planning import (
        BatchPageStep,
        BatchPaginationSpec,
        ConsumerNeed,
        ObservationPlan,
        PlannedLookup,
        PlannedObservationRequest,
        ResolvedLookup,
        execute_planned_acquisition,
        request_identity,
    )
    from rivretrieve._internal.source_acquisition import SourceResponseMeaning
    from rivretrieve._internal.transport import HttpMethod, TransportRequest, TransportResponse

    payload_size = 2 * 1024 * 1024

    # 1. request_identity distinguishes None vs "" params
    assert request_identity(TransportRequest(HttpMethod.GET, "https://example.invalid", params={"a": None})) != (
        request_identity(TransportRequest(HttpMethod.GET, "https://example.invalid", params={"a": ""}))
    )

    need_a = ConsumerNeed(
        station="S1",
        product=ProductId("flow"),
        scope=SeriesScope(provider_ids=("test",), station_ids=("S1",), product_ids=("flow",)),
        known_series=(),
        interval=driver_module.RequestedInterval(datetime(2024, 6, 1), datetime(2024, 6, 1)),
        window=SeriesWindow(start=datetime(2024, 6, 1), end=datetime(2024, 6, 1)),
        fetch_window=driver_module._make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 6, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 6, 1)),
        ),
        rendered=(),
    )
    need_b = replace(
        need_a,
        station="S2",
        scope=SeriesScope(provider_ids=("test",), station_ids=("S2",), product_ids=("flow",)),
    )

    class _DummyTransport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            raw = b'{"pad":"' + (b"x" * payload_size) + b'"}'
            return TransportResponse(
                url=request.url,
                request_parameters=request.params or {},
                status_code=200,
                retrieved_at=_utc(2026, 1, 1, 12),
                content_type="application/json",
                content=raw,
            )

    # 2. Invalid interpret_group / resolve_payload returns raise FatalContractError
    class _BadInterpretPlanner:
        def plan_lookups(self, needs, cfg):
            del needs, cfg
            return ()

        def plan_observations(self, needs, lookups, cfg):
            del lookups, cfg
            return ObservationPlan(
                requests=(
                    PlannedObservationRequest(
                        consumers=needs,
                        request=TransportRequest(HttpMethod.GET, "https://example.invalid/obs"),
                        source_coordinates=SourceCoordinates("flow"),
                        fetch_window=needs[0].fetch_window,
                        interpret_group=lambda p, pp, c: {},  # missing pair key!
                    ),
                )
            )

    with pytest.raises(FatalContractError):
        execute_planned_acquisition(_BadInterpretPlanner(), (need_a,), _sparse_config(), _DummyTransport())

    class _BadLookupPlanner:
        def plan_lookups(self, needs, cfg):
            del cfg
            return (
                PlannedLookup(
                    key="k",
                    consumers=needs,
                    request=TransportRequest(HttpMethod.GET, "https://example.invalid/lookup"),
                    source_coordinates=SourceCoordinates("flow"),
                    fetch_window=needs[0].fetch_window,
                    emit_payload=True,
                    resolve_payload=lambda p, pp, c: ("ok", "not-a-mapping"),  # type: ignore[return-value]
                ),
            )

        def plan_observations(self, needs, lookups, cfg):
            del needs, lookups, cfg
            return ObservationPlan()

    with pytest.raises(FatalContractError):
        execute_planned_acquisition(_BadLookupPlanner(), (need_a,), _sparse_config(), _DummyTransport())

    # 3. Conflicting merged lookup/obs specs raise FatalContractError
    class _ConflictLookupPlanner:
        def plan_lookups(self, needs, cfg):
            del cfg
            req = TransportRequest(HttpMethod.GET, "https://example.invalid/lookup")
            return (
                PlannedLookup(
                    key="k",
                    consumers=(needs[0],),
                    request=req,
                    source_coordinates=SourceCoordinates("flow"),
                    fetch_window=needs[0].fetch_window,
                    emit_payload=True,
                ),
                PlannedLookup(
                    key="k",
                    consumers=(needs[1],),
                    request=req,
                    source_coordinates=SourceCoordinates("flow"),
                    fetch_window=needs[1].fetch_window,
                    emit_payload=False,
                ),
            )

        def plan_observations(self, needs, lookups, cfg):
            del needs, lookups, cfg
            return ObservationPlan()

    with pytest.raises(FatalContractError):
        execute_planned_acquisition(_ConflictLookupPlanner(), (need_a, need_b), _sparse_config(), _DummyTransport())

    class _ConflictObsPlanner:
        def plan_lookups(self, needs, cfg):
            del needs, cfg
            return ()

        def plan_observations(self, needs, lookups, cfg):
            del lookups, cfg
            req = TransportRequest(HttpMethod.GET, "https://example.invalid/obs")
            return ObservationPlan(
                requests=(
                    PlannedObservationRequest(
                        consumers=(needs[0],),
                        request=req,
                        source_coordinates=SourceCoordinates("flow"),
                        fetch_window=needs[0].fetch_window,
                        response_meanings={404: SourceResponseMeaning.NO_OBSERVATIONS},
                    ),
                    PlannedObservationRequest(
                        consumers=(needs[1],),
                        request=req,
                        source_coordinates=SourceCoordinates("flow"),
                        fetch_window=needs[1].fetch_window,
                        response_meanings=None,
                    ),
                )
            )

    with pytest.raises(FatalContractError):
        execute_planned_acquisition(_ConflictObsPlanner(), (need_a, need_b), _sparse_config(), _DummyTransport())

    # 4. Partial BatchPageStep.interpretations + weakref release for PlannedLookup(emit_payload=True) and obs under OMIT
    def _empty_parsed() -> ParsedSeries:
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())

    class _PartialStepAndMemoryPlanner:
        def plan_lookups(self, needs, cfg):
            del cfg
            return (
                PlannedLookup(
                    key="meta",
                    consumers=needs,
                    request=TransportRequest(HttpMethod.GET, "https://example.invalid/meta"),
                    source_coordinates=SourceCoordinates("flow"),
                    fetch_window=needs[0].fetch_window,
                    emit_payload=True,
                    resolve_payload=lambda p, pp, c: (
                        "meta",
                        {k: _empty_parsed() for k in pp},
                    ),
                ),
            )

        def plan_observations(self, needs, lookups, cfg):
            del cfg
            assert isinstance(lookups[("meta", "S1", ProductId("flow"))], ResolvedLookup)

            def _partial_step(
                payload: Payload, consumers: tuple[ConsumerNeed, ...], cfg: ProviderConfig
            ) -> BatchPageStep:
                del payload, cfg
                # Intentionally omit ("S2", ProductId("flow")) from interpretations!
                return BatchPageStep(interpretations={(consumers[0].station, consumers[0].product): _empty_parsed()})

            return ObservationPlan(
                requests=(
                    PlannedObservationRequest(
                        consumers=needs,
                        request=TransportRequest(HttpMethod.GET, "https://example.invalid/obs"),
                        source_coordinates=SourceCoordinates("flow"),
                        fetch_window=needs[0].fetch_window,
                        pagination=BatchPaginationSpec(step_page=_partial_step),
                    ),
                )
            )

    class _Provider:
        config = _sparse_config()
        window_declarations = _sparse_declarations()
        request_planner = _PartialStepAndMemoryPlanner()

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            raise AssertionError("Partial BatchPageStep must not fall back to provider.parse()")

    mem_transport = _DummyTransport()
    pid = ProviderId("test_mem")
    tracemalloc.start()
    try:
        res = driver_module.drive(
            ObservationRequest(pid, ("S1", "S2"), (ProductId("flow"),), _date_window("2024-06-01", "2024-06-01")),
            _Provider(),
            provenance=ObservationProvenance(source="test", provider_id=pid, requested_at=_utc(2026, 1, 1, 12)),
            transport=mem_transport,
            receipts=ReceiptMode.OMIT,
        )
        gc.collect()
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert mem_transport.calls == 2
    assert res.canonical_rows.is_empty()
    assert peak_bytes >= payload_size
    assert current_bytes < 1_500_000


def test_vision_section_2_baseline_audit_probes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reproduce all five Vision section 2 audit probes for 2024-06-11..2024-06-12."""
    import json

    import rivretrieve as rr
    from rivretrieve._internal.providers.br_ana import parse as br_parse
    from rivretrieve._internal.providers.br_ana.declaration import declaration as br_declaration
    from rivretrieve._internal.providers.cz_chmi import parse as cz_parse
    from rivretrieve._internal.providers.cz_chmi.declaration import declaration as cz_declaration
    from rivretrieve._internal.providers.no_nve.declaration import declaration as no_declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.providers.th_thaiwater import parse as th_parse
    from rivretrieve._internal.providers.th_thaiwater.declaration import declaration as th_declaration
    from rivretrieve._internal.transport import TransportRequest, TransportResponse

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "vision_cache"))
    monkeypatch.setenv("RIVRETRIEVE_REUSE_PACKAGED_CATALOGUES", "1")
    probe_win = _date_window("2024-06-11", "2024-06-12")
    requested_at = _utc(2026, 6, 15, 12)

    # 1. ba_fhmzbih via public rr.fetch: 1010 & 1020, all 3 products -> 7 GETs (down from 12) & 7 receipts.
    ba_calls: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
    ba_stations = ("1010", "1020")
    ba_index = json.dumps(
        [{"metadata_station_no": st, "metadata_site_no": f"site-{st}"} for st in ba_stations]
    ).encode()
    ba_books = {
        ("1010", "Q"): _ba_workbook_bytes("1010", "Proticaj", "m³/s", [(datetime(2024, 6, 11, 12), 11.5)]),
        ("1010", "H"): _ba_workbook_bytes("1010", "Vodostaj", "cm", [(datetime(2024, 6, 11, 12), 105.0)]),
        ("1010", "WT"): _ba_workbook_bytes("1010", "Temperatura vode", "°C", [(datetime(2024, 6, 11, 12), 14.5)]),
        ("1020", "Q"): _ba_workbook_bytes("1020", "Proticaj", "m³/s", [(datetime(2024, 6, 11, 12), 21.5)]),
        ("1020", "H"): _ba_workbook_bytes("1020", "Vodostaj", "cm", [(datetime(2024, 6, 11, 12), 205.0)]),
        ("1020", "WT"): _ba_workbook_bytes("1020", "Temperatura vode", "°C", [(datetime(2024, 6, 11, 12), 15.5)]),
    }

    class _BaAuditTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            ba_calls.append((request.method.value, request.url, tuple(sorted((k, str(v)) for k, v in params.items()))))
            if request.url.endswith("/index.json"):
                return TransportResponse(
                    content=ba_index,
                    status_code=200,
                    retrieved_at=requested_at,
                    content_type="application/json",
                    url=request.url,
                    request_parameters=params,
                )
            for st in ba_stations:
                for code, fname in (("Q", "Q_1Y.xlsx"), ("H", "H_1Y.xlsx"), ("WT", "Tvode_1Y.xlsx")):
                    if f"/{st}/{code}/{fname}" in request.url:
                        return TransportResponse(
                            content=ba_books[(st, code)],
                            status_code=200,
                            retrieved_at=requested_at,
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            url=request.url,
                            request_parameters=params,
                        )
            raise AssertionError(f"Unexpected ba_fhmzbih URL: {request.url}")

    monkeypatch.setattr(discovery_module, "HttpClient", _BaAuditTransport)
    ba_sel = rr.find(provider="ba_fhmzbih", station=ba_stations)
    ba_res = rr.fetch(ba_sel, start="2024-06-11", end="2024-06-12", cache="bypass", receipts=True)
    assert len(ba_calls) == 7
    assert sum(1 for _, url, _ in ba_calls if url.endswith("/index.json")) == 1
    assert len(ba_res.receipts.entries) == 7
    assert ba_res.data.height == 6

    # 2. no_nve via drive: 2.279.0, unrestricted stage at 3 resolutions with empty /Series -> 1 /Series call (down from 3).
    assert isinstance(no_declaration.observations, LiveStages)
    no_calls: list[TransportRequest] = []

    class _NoAuditTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            no_calls.append(request)
            assert request.url.endswith("/Series")
            return TransportResponse(
                content=json.dumps({"itemCount": 0, "data": []}).encode(),
                status_code=200,
                retrieved_at=requested_at,
                content_type="application/json",
                url=request.url,
                request_parameters=dict(request.params or {}),
            )

    no_res = driver_module.drive(
        ObservationRequest(
            ProviderId("no_nve"),
            ("2.279.0",),
            (ProductId("stage_daily_mean"), ProductId("stage_hourly_mean"), ProductId("stage_instantaneous")),
            probe_win,
        ),
        no_declaration.observations.stages,
        provenance=ObservationProvenance(source="nve", provider_id=ProviderId("no_nve"), requested_at=requested_at),
        transport=_NoAuditTransport(),
        cache="bypass",
    )
    assert len(no_calls) == 1
    assert {o.status for o in no_res.outcomes} == {OutcomeStatus.NO_MATCH}
    lookup_invs = [
        inv for inv in no_res.inventories if not any(e.startswith("retrieval-outcome:") for e in inv.evidence)
    ]
    assert len(lookup_invs) == 3

    # 3. cz_chmi via drive: 0-203-1-000400, all 5 products -> 2 GETs & 2 decodes (down from 5).
    assert isinstance(cz_declaration.observations, LiveStages)
    cz_station = "0-203-1-000400"
    cz_dq = {
        "objID": cz_station,
        "tsList": [
            {
                "tsConID": tid,
                "unit": unit_str,
                "tsData": {
                    "type": "DataCollection",
                    "data": {
                        "header": "DT,VAL",
                        "values": [["2024-06-11T00:00:00Z", v1], ["2024-06-12T00:00:00Z", v2]],
                    },
                },
            }
            for tid, unit_str, v1, v2 in (("HD", "CM", 10.0, 11.0), ("QD", "M3_S", 1.5, 1.7), ("TD", "0C", 15.0, 15.5))
        ],
    }
    cz_hq = {
        "objID": cz_station,
        "tsList": [
            {
                "tsConID": tid,
                "unit": unit_str,
                "tsData": {
                    "type": "DataCollection",
                    "data": {
                        "header": "DT,VAL",
                        "values": [["2024-06-11T00:00:00Z", v1], ["2024-06-12T00:00:00Z", v2]],
                    },
                },
            }
            for tid, unit_str, v1, v2 in (("HH", "CM", 12.0, 13.0), ("QH", "M3_S", 2.1, 2.3))
        ],
    }
    cz_calls: list[TransportRequest] = []
    cz_decodes = 0
    real_cz_loads = cz_parse.json.loads

    def _counting_cz_loads(*args: object, **kwargs: object) -> object:
        nonlocal cz_decodes
        cz_decodes += 1
        return real_cz_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cz_parse.json, "loads", _counting_cz_loads)

    class _CzAuditTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            cz_calls.append(request)
            body = cz_hq if "_HQ_" in request.url else cz_dq
            return TransportResponse(
                content=json.dumps(body).encode(),
                status_code=200,
                retrieved_at=requested_at,
                content_type="application/json",
                url=request.url,
                request_parameters=dict(request.params or {}),
            )

    cz_res = driver_module.drive(
        ObservationRequest(
            ProviderId("cz_chmi"),
            (cz_station,),
            (
                ProductId("stage_daily_mean"),
                ProductId("discharge_daily_mean"),
                ProductId("water_temperature_daily_mean"),
                ProductId("stage_hourly_mean"),
                ProductId("discharge_hourly_mean"),
            ),
            probe_win,
        ),
        cz_declaration.observations.stages,
        provenance=ObservationProvenance(source="chmi", provider_id=ProviderId("cz_chmi"), requested_at=requested_at),
        transport=_CzAuditTransport(),
        cache="bypass",
    )
    assert len(cz_calls) == 2
    assert cz_decodes == 2
    assert cz_res.canonical_rows.height == 10

    # 4. th_thaiwater via drive: 1373273, stage + discharge -> 1 GET & 1 decode (down from 2).
    assert isinstance(th_declaration.observations, LiveStages)
    th_calls: list[TransportRequest] = []
    th_decodes = 0
    real_th_loads = th_parse.json.loads

    def _counting_th_loads(*args: object, **kwargs: object) -> object:
        nonlocal th_decodes
        th_decodes += 1
        return real_th_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(th_parse.json, "loads", _counting_th_loads)

    class _ThAuditTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            th_calls.append(request)
            doc = {
                "result": "OK",
                "data": {
                    "graph_data": [
                        {"datetime": "2024-06-11 00:00", "discharge": 12.5, "value": 3.4},
                        {"datetime": "2024-06-12 00:00", "discharge": 13.0, "value": 3.5},
                    ]
                },
            }
            return TransportResponse(
                content=json.dumps(doc).encode(),
                status_code=200,
                retrieved_at=requested_at,
                content_type="application/json",
                url=request.url,
                request_parameters=dict(request.params or {}),
            )

    th_res = driver_module.drive(
        ObservationRequest(
            ProviderId("th_thaiwater"),
            ("1373273",),
            (ProductId("discharge_reported"), ProductId("stage_reported")),
            probe_win,
        ),
        th_declaration.observations.stages,
        provenance=ObservationProvenance(
            source="thaiwater", provider_id=ProviderId("th_thaiwater"), requested_at=requested_at
        ),
        transport=_ThAuditTransport(),
        cache="bypass",
    )
    assert len(th_calls) == 1
    assert th_decodes == 1
    assert th_res.canonical_rows.height == 4

    # 5. br_ana via drive: 15400000, all 6 products -> 3 GETs & 3 decodes (down from 6).
    assert isinstance(br_declaration.observations, LiveStages)
    br_station = "15400000"

    def _ana_daily_row(prefix: str, consistency: str, v11: str, v12: str) -> dict[str, object]:
        cons_key = "nivelconsistencia" if prefix == "Cota" else "Nivel_Consistencia"
        meth_key = "Tipo_Medicao_Cotas" if prefix == "Cota" else "Metodo_Obtencao_Vazoes"
        row: dict[str, object] = {
            "codigoestacao": br_station,
            "Mediadiaria": "1",
            cons_key: consistency,
            "Data_Hora_Dado": "2024-06-01 00:00:00.0",
            meth_key: "2",
        }
        for day in range(1, 32):
            if day == 11:
                row[f"{prefix}_11"] = v11
                row[f"{prefix}_11_Status"] = "1"
            elif day == 12:
                row[f"{prefix}_12"] = v12
                row[f"{prefix}_12_Status"] = "2"
            else:
                row[f"{prefix}_{day:02d}"] = None
                row[f"{prefix}_{day:02d}_Status"] = "0" if day > 30 else None
        return row

    br_bodies = {
        "telemetry": json.dumps(
            {
                "status": "OK",
                "code": 200,
                "items": [
                    {
                        "codigoestacao": br_station,
                        "Data_Hora_Medicao": "2024-06-11 12:00:00.0",
                        "Cota_Adotada": "150.0",
                        "Cota_Adotada_Status": "0",
                        "Vazao_Adotada": "42.5",
                        "Vazao_Adotada_Status": "1",
                    }
                ],
            }
        ).encode(),
        "cotas": json.dumps(
            {
                "status": "OK",
                "code": 200,
                "items": [
                    _ana_daily_row("Cota", "1", "100.0", "102.0"),
                    _ana_daily_row("Cota", "2", "105.0", "106.0"),
                ],
            }
        ).encode(),
        "vazoes": json.dumps(
            {
                "status": "OK",
                "code": 200,
                "items": [
                    _ana_daily_row("Vazao", "1", "21.0", "22.0"),
                    _ana_daily_row("Vazao", "2", "23.0", "24.0"),
                ],
            }
        ).encode(),
    }
    br_calls: list[TransportRequest] = []
    br_decodes = 0
    real_br_loads = br_parse.json.loads

    def _counting_br_loads(*args: object, **kwargs: object) -> object:
        nonlocal br_decodes
        br_decodes += 1
        return real_br_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(br_parse.json, "loads", _counting_br_loads)

    class _BrAuditTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            br_calls.append(request)
            key = (
                "telemetry"
                if "HidroinfoanaSerieTelemetricaAdotada" in request.url
                else ("vazoes" if "HidroSerieVazao" in request.url else "cotas")
            )
            return TransportResponse(
                content=br_bodies[key],
                status_code=200,
                retrieved_at=requested_at,
                content_type="application/json",
                url=request.url,
                request_parameters=dict(request.params or {}),
            )

    br_res = driver_module.drive(
        ObservationRequest(
            ProviderId("br_ana"),
            (br_station,),
            (
                ProductId("discharge_instantaneous"),
                ProductId("stage_instantaneous"),
                ProductId("discharge_daily_mean_bruto"),
                ProductId("discharge_daily_mean_consistido"),
                ProductId("stage_daily_mean_bruto"),
                ProductId("stage_daily_mean_consistido"),
            ),
            probe_win,
        ),
        br_declaration.observations.stages,
        provenance=ObservationProvenance(source="ana", provider_id=ProviderId("br_ana"), requested_at=requested_at),
        transport=_BrAuditTransport(),
        cache="bypass",
    )
    assert len(br_calls) == 3
    assert br_decodes == 3
    assert len(br_res.outcomes) == 6
    assert {o.status for o in br_res.outcomes} == {OutcomeStatus.SUCCESS}
