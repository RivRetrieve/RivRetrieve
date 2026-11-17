"""Source-independent tests for provider-declared client cache retention limits."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    CacheConfig,
    Daily,
    DailyLabelTime,
    DayDefinition,
    FetchWindow,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptAuthorship, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    AnnotationField,
    AnnotationSchema,
    AnnotationScope,
    ObservationAnnotationTable,
    SeriesAnnotationTable,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)
from rivretrieve._internal.store import StoreReader, StoreRoot
from rivretrieve._internal.store.integrity import audit_store
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
    _SystemClock,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_PROVIDER = ProviderId("synth_ret")
_OBS_SCHEMA = AnnotationSchema(
    schema_id="synth_ret.obs",
    provider_id="synth_ret",
    scope=AnnotationScope.OBSERVATION,
    fields=(AnnotationField(name="flag", dtype="String", description="Flag"),),
)
_SER_SCHEMA = AnnotationSchema(
    schema_id="synth_ret.meta",
    provider_id="synth_ret",
    scope=AnnotationScope.SERIES,
    fields=(AnnotationField(name="note", dtype="String", description="Series note"),),
)


def _series_def(station: str, product: str = "flow") -> SourceSeries:
    return SourceSeries(
        series_id=stable_id("synth_ret", station, product),
        provider_id="synth_ret",
        station_id=station,
        product_id=product,
        identity=SourceIdentity(
            namespace="synth_ret",
            published_id=f"{station}-{product}",
            origin="response",
            evidence=("synthetic fixture",),
        ),
        facts=(
            PhysicalFacts(
                facts_id="synth-facts-flow",
                quantity=known("discharge", "synthetic fixture"),
                source_unit=known("m3/s", "synthetic fixture"),
                normalized_unit="m3/s",
                frequency=known("daily", "synthetic fixture"),
                temporal_support=known("mean", "synthetic fixture"),
                time_zone=known("unknown", "synthetic fixture"),
            ),
        ),
    )


class _RetentionStages:
    observation_source = "live"

    def __init__(self, *, max_retention: timedelta = timedelta(days=30), coverage_kind: str = "interval") -> None:
        self.config = ProviderConfig(
            zone=ZoneValue("unknown"),
            products={
                ProductId("flow"): ProductConfig(
                    coordinates=SourceCoordinates({"parameter": "flow"}),
                    unit=Unit.M3_S,
                    semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
                )
            },
            cache=CacheConfig(max_retention=max_retention),
        )
        self.window_declarations = ProductWindowDeclarations(
            {
                ProductId("flow"): WindowDeclaration(
                    WindowGranularity("date"),
                    WindowRenderingVocabulary.DATE,
                    StopConvention.INCLUSIVE,
                )
            }
        )
        self.coverage_kind = coverage_kind

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        windows: MappingProxyType[ProductId, tuple],
        fetch_window: FetchWindow,
        config: ProviderConfig,
        transport,
        *,
        scope: SeriesScope | None = None,
        known_series: tuple[SourceSeries, ...] = (),
    ) -> WithIssues[tuple[Payload, ...]]:
        payloads = []
        for station in stations:
            for product in products:
                request = TransportRequest(
                    method=HttpMethod.GET,
                    url=f"https://example.invalid/{station}/{product}",
                    params={"start": str(fetch_window.start), "end": str(fetch_window.end)},
                )
                response = transport.send(request)
                payloads.append(
                    Payload(
                        source_coordinates=config.products[product].coordinates,
                        station_products=((station, product),),
                        fetch_window=fetch_window,
                        content=response.content,
                        origin=SourceCallOrigin(
                            url=response.url,
                            request_parameters=request.params,
                            status_code=response.status_code,
                            retrieved_at=response.retrieved_at,
                            content_type=response.content_type or UnknownOriginFact(),
                            source_path=UnknownOriginFact(),
                            query=UnknownOriginFact(),
                        ),
                        prerequisite_calls=response.prerequisite_calls,
                        scope=scope,
                        known_series=known_series,
                    )
                )
        return WithIssues(tuple(payloads))

    def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
        station, product = payload.station_products[0]
        doc = json.loads(payload.content)
        definition = _series_def(station, str(product))
        rows_data = doc["rows"]
        rows = (
            pl.DataFrame(
                [
                    {
                        "station_id": station,
                        "product_id": str(product),
                        "time": datetime.fromisoformat(row["time"]),
                        "value": row["value"],
                        "time_zone": "unknown",
                        "series_id": definition.series_id,
                        "facts_id": "synth-facts-flow",
                        "source_unit": "m3/s",
                    }
                    for row in rows_data
                ],
                schema=RowsSchema.polars_schema,
            )
            if rows_data
            else pl.DataFrame(schema=RowsSchema.polars_schema)
        )
        obs_ann = (
            ObservationAnnotationTable.from_rows(
                schema=_OBS_SCHEMA,
                rows=pl.DataFrame(
                    [
                        {
                            "series_id": definition.series_id,
                            "facts_id": "synth-facts-flow",
                            "station_id": station,
                            "product_id": str(product),
                            "time": datetime.fromisoformat(row["time"]),
                            "time_zone": "unknown",
                            "measured": True,
                            "flag": row["flag"],
                        }
                        for row in rows_data
                    ],
                    schema={
                        "series_id": pl.String(),
                        "facts_id": pl.String(),
                        "station_id": pl.String(),
                        "product_id": pl.String(),
                        "time": pl.Datetime("us"),
                        "time_zone": pl.String(),
                        "measured": pl.Boolean(),
                        **_OBS_SCHEMA.polars_schema(),
                    },
                ),
                measurement_indices=tuple(range(len(rows_data))),
            )
            if rows_data
            else None
        )
        ser_ann = SeriesAnnotationTable.from_rows(
            schema=_SER_SCHEMA,
            rows=pl.DataFrame({"series_id": [definition.series_id], "note": [doc["note"]]}),
        )
        bundle = AnnotationBundle(
            observation_tables={_OBS_SCHEMA.schema_id: obs_ann} if obs_ann is not None else {},
            series_tables={_SER_SCHEMA.schema_id: ser_ann},
        )
        start = datetime.fromisoformat(payload.fetch_window.start.isoformat())
        end = datetime.fromisoformat(payload.fetch_window.end.isoformat())
        keys = tuple(rows.select("facts_id", "time", "time_zone").iter_rows()) if not rows.is_empty() else ()
        status = OutcomeStatus.EMPTY if rows.is_empty() else OutcomeStatus.SUCCESS
        outcome = RetrievalOutcome(
            outcome_id=stable_id("out", payload.acquisition_id, station, str(product)),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=SeriesWindow(start=start, end=end),
            status=status,
            facts_ids=("synth-facts-flow",),
            retrieved_at=payload.origin.retrieved_at
            if not isinstance(payload.origin.retrieved_at, UnknownOriginFact)
            else None,
            coverage=self.coverage_kind,
            observation_keys=keys if self.coverage_kind == "observations" and status is OutcomeStatus.SUCCESS else (),
        )
        snapshot = InventorySnapshot(
            snapshot_id=stable_id("inv", payload.acquisition_id, station, str(product)),
            scope=SeriesScope(provider_ids=(str(_PROVIDER),), station_ids=(station,), product_ids=(str(product),)),
            members=(definition.series_id,),
            member_facts=((definition.series_id, ("synth-facts-flow",)),),
            completeness=InventoryCompleteness.COMPLETE,
            access="synthetic retention test",
            origin="response",
            acquired_at=outcome.retrieved_at,
            window=SeriesWindow(start=start, end=end),
            evidence=(f"retrieval-outcome:{outcome.outcome_id}",),
        )
        return ParsedSeries(
            rows=rows,
            series=(definition,),
            inventories=(snapshot,),
            outcomes=(outcome,),
            annotations=bundle,
        )


class _ScriptedTransport:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.calls.append(request)
        return self.handler(request)


def _drive(
    store: Path,
    stages: _RetentionStages,
    transport,
    *,
    now: datetime,
    station: str = "S1",
    start: datetime = datetime(1962, 11, 1),
    end: datetime = datetime(1962, 11, 2, 23, 59, 59, 999999),
    cache: str = "reuse",
):
    return drive(
        ObservationRequest(
            _PROVIDER,
            (station,),
            (ProductId("flow"),),
            RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
        ),
        stages,
        provenance=ObservationProvenance(source="live", provider_id=_PROVIDER, requested_at=now),
        transport=transport,
        cache=cache,  # ty: ignore[invalid-argument-type]
        store=StoreRoot(store),
        receipts=ReceiptMode.INCLUDE,
    )


def test_retention_reuses_within_30_days_including_historical_dates_and_evicts_past_limit(tmp_path: Path) -> None:
    store = tmp_path / "store"
    stages = _RetentionStages()
    t0 = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    current_time = t0
    version = {"n": 1}

    def handle(request: TransportRequest) -> TransportResponse:
        body = json.dumps(
            {
                "rows": [
                    {"time": "1962-11-01T00:00:00", "value": 10.0 * version["n"], "flag": "E"},
                    {"time": "1962-11-02T00:00:00", "value": None, "flag": "S"},
                ],
                "note": f"fetch-{version['n']}",
            }
        ).encode()
        return TransportResponse(body, 200, current_time, "application/json", request.url, request.params)

    transport = _ScriptedTransport(handle)
    # Historical 1962 observations fetched at t0 must be cached and reused for <= 30 days.
    first = _drive(store, stages, transport, now=t0)
    assert len(transport.calls) == 1
    assert first.canonical_rows["value"].to_list() == [10.0, None]
    assert first.annotations.schema_table("synth_ret.meta")["note"].to_list() == ["fetch-1"]

    version["n"] = 2
    exact_boundary = t0 + timedelta(days=30)
    cached = _drive(store, stages, transport, now=exact_boundary)
    assert len(transport.calls) == 1
    assert cached.canonical_rows["value"].to_list() == [10.0, None]
    assert cached.annotations.schema_table("synth_ret.obs")["flag"].to_list() == ["E", "S"]
    assert cached.annotations.schema_table("synth_ret.meta")["note"].to_list() == ["fetch-1"]
    assert cached.receipts.entries[0].authorship is ReceiptAuthorship.STORE_EXCERPT

    # Even 1 microsecond past 30 days triggers eviction and fresh source acquisition.
    expired_time = t0 + timedelta(days=30, microseconds=1)
    current_time = expired_time
    refreshed = _drive(store, stages, transport, now=expired_time)
    assert len(transport.calls) == 2
    assert refreshed.canonical_rows["value"].to_list() == [20.0, None]
    assert refreshed.annotations.schema_table("synth_ret.meta")["note"].to_list() == ["fetch-2"]
    assert audit_store(StoreRoot(store), _PROVIDER).rows_checked == 2


def test_expired_cache_does_not_conceal_failures_or_leak_held_rows(tmp_path: Path) -> None:
    store = tmp_path / "store"
    stages = _RetentionStages()
    t0 = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)

    def ok_handler(request: TransportRequest) -> TransportResponse:
        body = json.dumps(
            {
                "rows": [{"time": "2020-01-01T00:00:00", "value": 5.5, "flag": "E"}],
                "note": "cached-note",
            }
        ).encode()
        return TransportResponse(body, 200, t0, "application/json", request.url, request.params)

    first = _drive(
        store,
        stages,
        _ScriptedTransport(ok_handler),
        now=t0,
        start=datetime(2020, 1, 1),
        end=datetime(2020, 1, 1, 23, 59, 59, 999999),
    )
    assert first.canonical_rows.height == 1

    # Beyond 30 days, a transport failure must NOT fall back to expired held rows.
    def fail_handler(request: TransportRequest) -> TransportResponse:
        raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)

    expired = t0 + timedelta(days=31)
    failed = _drive(
        store,
        stages,
        _ScriptedTransport(fail_handler),
        now=expired,
        start=datetime(2020, 1, 1),
        end=datetime(2020, 1, 1, 23, 59, 59, 999999),
        cache="reuse",
    )
    assert failed.canonical_rows.is_empty()
    assert any(item.status is OutcomeStatus.FAILED for item in failed.outcomes)
    assert any(issue.code == "source.request_failed" for issue in failed.issues)

    # Expired parquet files and coverage must have been removed from the on-disk store.
    manifest = StoreReader().status(StoreRoot(store), _PROVIDER).manifest
    assert manifest is not None
    assert manifest.coverage == ()
    assert not list(store.rglob("*.parquet"))
    assert manifest.series == ()
    assert audit_store(StoreRoot(store), _PROVIDER).partitions_checked == 0


def test_selective_eviction_preserves_unexpired_stations_and_unlinked_bundles(tmp_path: Path) -> None:
    store = tmp_path / "store"
    stages = _RetentionStages()
    t0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    t_b = t0 + timedelta(days=20)
    times = {"S1": t0, "S2": t_b}

    def handle(request: TransportRequest) -> TransportResponse:
        station = "S1" if "/S1/" in request.url else "S2"
        start_param = str((request.params or {}).get("start", ""))
        year = 2020 if station == "S1" else (2019 if "month=5" in start_param else 2020)
        rows = (
            [
                {"time": "2019-06-01T00:00:00", "value": 1.0, "flag": "A"},
                {"time": "2020-01-01T00:00:00", "value": 2.0, "flag": "B"},
            ]
            if station == "S2"
            else [{"time": "2020-01-02T00:00:00", "value": 9.0, "flag": "C"}]
        )
        if station == "S2" and year == 2019:
            rows = [r for r in rows if r["time"].startswith("2019")]
        elif station == "S2":
            rows = [r for r in rows if r["time"].startswith("2020")]
        body = json.dumps({"rows": rows, "note": f"note-{station}"}).encode()
        return TransportResponse(body, 200, times[station], "application/json", request.url, request.params)

    t = _ScriptedTransport(handle)
    _drive(
        store,
        stages,
        t,
        now=t0,
        station="S1",
        start=datetime(2020, 1, 2),
        end=datetime(2020, 1, 2, 23, 59, 59, 999999),
    )
    _drive(
        store,
        stages,
        t,
        now=t_b,
        station="S2",
        start=datetime(2019, 6, 1),
        end=datetime(2019, 6, 1, 23, 59, 59, 999999),
    )
    _drive(
        store,
        stages,
        t,
        now=t_b,
        station="S2",
        start=datetime(2020, 1, 1),
        end=datetime(2020, 1, 1, 23, 59, 59, 999999),
    )
    assert len(t.calls) == 3

    # Hold a user-created bundle from S1 before cache expiry.
    s1_held = _drive(
        store,
        stages,
        t,
        now=t0 + timedelta(days=5),
        station="S1",
        start=datetime(2020, 1, 2),
        end=datetime(2020, 1, 2, 23, 59, 59, 999999),
    )
    assert len(t.calls) == 3

    # At t0 + 31 days: S1 is expired (31d), S2 is still within 30 days (11d).
    t_check = t0 + timedelta(days=31)

    def fail_s1_only(request: TransportRequest) -> TransportResponse:
        if "/S1/" in request.url:
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
        raise AssertionError("S2 must be served from cache without touching transport")

    s1_after = _drive(
        store,
        stages,
        _ScriptedTransport(fail_s1_only),
        now=t_check,
        station="S1",
        start=datetime(2020, 1, 2),
        end=datetime(2020, 1, 2, 23, 59, 59, 999999),
    )
    assert s1_after.canonical_rows.is_empty()
    assert any(item.status is OutcomeStatus.FAILED for item in s1_after.outcomes)

    # S2 in both shared partition (2020) and hardlink-candidate partition (2019) stays intact.
    s2_2019 = _drive(
        store,
        stages,
        _ScriptedTransport(fail_s1_only),
        now=t_check,
        station="S2",
        start=datetime(2019, 6, 1),
        end=datetime(2019, 6, 1, 23, 59, 59, 999999),
    )
    s2_2020 = _drive(
        store,
        stages,
        _ScriptedTransport(fail_s1_only),
        now=t_check,
        station="S2",
        start=datetime(2020, 1, 1),
        end=datetime(2020, 1, 1, 23, 59, 59, 999999),
    )
    assert s2_2019.canonical_rows["value"].to_list() == [1.0]
    assert s2_2020.canonical_rows["value"].to_list() == [2.0]
    assert s2_2020.annotations.schema_table("synth_ret.meta")["note"].to_list() == ["note-S2"]
    assert audit_store(StoreRoot(store), _PROVIDER).rows_checked == 2

    # User-held ObservationResult serialized via to_bundle/from_bundle is distinct from cache retention.
    from rivretrieve._internal.assembly import _AssemblyResult
    from rivretrieve._internal.observations import ObservationResult
    from rivretrieve._internal.source_annotations import with_annotations

    assert isinstance(s1_held, _AssemblyResult)
    obs = with_annotations(
        ObservationResult(
            data=s1_held.canonical_rows,
            source_series=s1_held.source_series,
            inventories=s1_held.inventories,
            outcomes=s1_held.outcomes,
            scope=s1_held.scope,
            provenance=s1_held.provenance,
            issues=s1_held.issues,
            receipts=s1_held.receipts,
        ),
        s1_held.annotations,
    )
    restored = rr.from_bundle(rr.to_bundle(obs))
    pl_testing.assert_frame_equal(restored.data, obs.data)


def test_observation_only_outcomes_also_respect_retention(tmp_path: Path) -> None:
    store = tmp_path / "store"
    stages = _RetentionStages(coverage_kind="observations")
    t0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)

    def ok_handler(request: TransportRequest) -> TransportResponse:
        body = json.dumps(
            {
                "rows": [{"time": "2020-05-01T00:00:00", "value": 42.0, "flag": "E"}],
                "note": "rolling-snap",
            }
        ).encode()
        return TransportResponse(body, 200, t0, "application/json", request.url, request.params)

    _drive(
        store,
        stages,
        _ScriptedTransport(ok_handler),
        now=t0,
        start=datetime(2020, 5, 1),
        end=datetime(2020, 5, 1, 23, 59, 59, 999999),
    )

    def fail_handler(request: TransportRequest) -> TransportResponse:
        raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)

    expired = _drive(
        store,
        stages,
        _ScriptedTransport(fail_handler),
        now=t0 + timedelta(days=31),
        start=datetime(2020, 5, 1),
        end=datetime(2020, 5, 1, 23, 59, 59, 999999),
    )
    assert expired.canonical_rows.is_empty()
    assert any(item.status is OutcomeStatus.FAILED for item in expired.outcomes)
    assert not list(store.rglob("*.parquet"))


def test_registry_drive_uses_system_clock_for_requested_at(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixed = datetime(2026, 11, 17, 9, 30, tzinfo=UTC)
    monkeypatch.setattr(_SystemClock, "utcnow", lambda self: fixed)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))

    from rivretrieve._internal import discovery

    seen = {}

    class _FakeTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            seen["url"] = request.url
            return TransportResponse(b"{}", 200, fixed, "application/json", request.url, request.params)

    monkeypatch.setattr(discovery, "HttpClient", lambda: _FakeTransport())
    # Verify via public registration/registry path on an existing LiveStages provider
    # by inspecting provenance.requested_at regardless of outcome.
    selection = rr.find(provider="at_ehyd", station="200014")
    result = rr.fetch(
        selection,
        start="2020-01-01",
        end="2020-01-02",
        cache="bypass",
        on_issue="ignore",
    )
    assert result.provenance.requested_at == fixed
