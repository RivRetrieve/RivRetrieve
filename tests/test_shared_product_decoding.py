"""Source-independent contracts for decoding shared-product responses once (#950)."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    InterpretedPayload,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
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
    narrow_payload_for_pair,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.observations import ReceiptAuthorship, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_annotations import (
    OBSERVATION_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    AnnotationField,
    AnnotationSchema,
    AnnotationScope,
    ObservationAnnotationTable,
    SeriesAnnotationTable,
)
from rivretrieve._internal.source_series import (
    ClippingAxis,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RestrictionKind,
    RetrievalOutcome,
    ScopeState,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)
from rivretrieve._internal.store import StoreRoot
from tests.test_internal_driver import _provenance


def _shared_config() -> tuple[tuple[ProductId, ProductId], ProviderConfig, ProductWindowDeclarations]:
    products = (ProductId("flow"), ProductId("level"))
    coords = SourceCoordinates({"route": "shared"})
    cfg = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("flow"): ProductConfig(
                coords, Unit.M3_S, Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))
            ),
            ProductId("level"): ProductConfig(
                coords, Unit.CM, Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))
            ),
        },
    )
    decl = WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)
    return products, cfg, ProductWindowDeclarations(dict.fromkeys(products, decl))


def _origin(retrieved_at: datetime | None = None) -> SourceCallOrigin:
    return SourceCallOrigin(
        "https://example.invalid/shared",
        {},
        200,
        retrieved_at or datetime(2026, 1, 1, tzinfo=UTC),
        "application/json",
        UnknownOriginFact(),
        UnknownOriginFact(),
    )


def _series_def(station: str, product: ProductId) -> SourceSeries:
    unit = "m3/s" if product == "flow" else "cm"
    norm = "m3/s" if product == "flow" else "cm"
    qty = "discharge" if product == "flow" else "stage"
    fact = PhysicalFacts(
        facts_id=f"{station}:{product}:facts",
        quantity=known(qty, "test"),
        source_unit=known(unit, "test"),
        normalized_unit=norm,
        frequency=known("daily", "test"),
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_time="00:00",
    )
    sid = f"{station}:{product}"
    return SourceSeries(
        series_id=sid,
        provider_id="throwaway",
        station_id=station,
        product_id=str(product),
        identity=SourceIdentity(namespace="test", published_id=sid, origin="response", evidence=("test",)),
        facts=(fact,),
    )


def _parsed_for_pair(
    pair_payload: Payload,
    *,
    values: list[tuple[datetime, float | None]] | None = None,
    empty: bool = False,
    failed_reason: str | None = None,
    annotations: AnnotationBundle | None = None,
    series_override: SourceSeries | None = None,
) -> ParsedSeries:
    station, product = pair_payload.station_products[0]
    definition = series_override or _series_def(station, product)
    fact = definition.facts[0]
    win = SeriesWindow(
        start=datetime.fromisoformat(pair_payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(pair_payload.fetch_window.end.isoformat()),
    )
    scope = pair_payload.scope or SeriesScope(
        provider_ids=("throwaway",), station_ids=(station,), product_ids=(str(product),)
    )
    if failed_reason is not None:
        outcome = RetrievalOutcome(
            outcome_id=stable_id(pair_payload.acquisition_id, station, str(product), "failed"),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=win,
            status=OutcomeStatus.FAILED,
            facts_ids=(fact.facts_id,),
            reason=failed_reason,
            retrieved_at=pair_payload.origin.retrieved_at
            if isinstance(pair_payload.origin.retrieved_at, datetime)
            else None,
            calls=(pair_payload.acquisition_id,),
        )
        issue = Issue(
            severity="error",
            code="source.unsupported_structure",
            message=failed_reason,
            details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
            provider_id=ProviderId("throwaway"),
        )
        inv = InventorySnapshot(
            snapshot_id=stable_id(pair_payload.acquisition_id, station, str(product), "inv-fail"),
            scope=scope,
            members=(definition.series_id,),
            completeness=InventoryCompleteness.INCOMPLETE,
            access="shared-test",
            origin="response",
            window=win,
            evidence=("test",),
            reason=failed_reason,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (definition,), (inv,), (outcome,), (issue,))

    row_items = [] if empty else (values if values is not None else [(datetime(2025, 1, 1), 15.0)])
    rows = pl.DataFrame(
        {
            "station_id": [station] * len(row_items),
            "product_id": [str(product)] * len(row_items),
            "time": [ts for ts, _ in row_items],
            "value": [val for _, val in row_items],
            "time_zone": ["+00:00"] * len(row_items),
            "series_id": [definition.series_id] * len(row_items),
            "facts_id": [fact.facts_id] * len(row_items),
            "source_unit": [fact.source_unit.value] * len(row_items),
        },
        schema=RowsSchema.polars_schema,
    )
    status = OutcomeStatus.EMPTY if rows.is_empty() else OutcomeStatus.SUCCESS
    outcome = RetrievalOutcome(
        outcome_id=stable_id(pair_payload.acquisition_id, definition.series_id, status.value),
        series_id=definition.series_id,
        station_id=station,
        product_id=str(product),
        window=win,
        status=status,
        facts_ids=(fact.facts_id,),
        retrieved_at=pair_payload.origin.retrieved_at
        if isinstance(pair_payload.origin.retrieved_at, datetime)
        else None,
        calls=(pair_payload.acquisition_id,),
    )
    inv = InventorySnapshot(
        snapshot_id=stable_id(pair_payload.acquisition_id, definition.series_id, "inv"),
        scope=scope,
        members=(definition.series_id,),
        completeness=InventoryCompleteness.COMPLETE,
        access="shared-test",
        origin="response",
        window=win,
        evidence=("test",),
    )
    return ParsedSeries(
        rows, (definition,), (inv,), (outcome,), (), annotations=annotations or AnnotationBundle.empty()
    )


def test_narrow_payload_for_pair_filters_scope_series_ids_and_known_series() -> None:
    products, cfg, _ = _shared_config()
    flow_def = _series_def("s1", products[0])
    level_def = _series_def("s1", products[1])
    other_station_def = _series_def("s2", products[0])
    from rivretrieve._internal.engine import _make_fetch_window

    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
    )
    base = Payload(
        source_coordinates=cfg.products[products[0]].coordinates,
        station_products=(("s1", products[0]), ("s1", products[1])),
        fetch_window=fw,
        content=b"{}",
        origin=_origin(),
        prerequisite_calls=(),
        known_series=(flow_def, level_def, other_station_def),
    )

    assert narrow_payload_for_pair(base, "s1", products[0]).scope is None
    assert narrow_payload_for_pair(base, "s1", products[0]).known_series == (flow_def,)

    explicit = replace(
        base,
        scope=SeriesScope(
            provider_ids=("throwaway",),
            station_ids=("s1",),
            product_ids=("flow", "level"),
            restriction=RestrictionKind.EXPLICIT,
            series_ids=(flow_def.series_id, level_def.series_id, "unknown-id"),
        ),
    )
    narrowed_flow = narrow_payload_for_pair(explicit, "s1", products[0])
    assert narrowed_flow.station_products == (("s1", products[0]),)
    assert narrowed_flow.known_series == (flow_def,)
    assert narrowed_flow.scope is not None
    assert narrowed_flow.scope.product_ids == ("flow",)
    assert narrowed_flow.scope.series_ids == (flow_def.series_id, "unknown-id")
    assert narrowed_flow.scope.state is ScopeState.ACTIVE

    only_level = replace(
        base,
        scope=SeriesScope(
            provider_ids=("throwaway",),
            station_ids=("s1",),
            product_ids=("flow", "level"),
            restriction=RestrictionKind.EXPLICIT,
            series_ids=(level_def.series_id,),
        ),
    )
    narrowed_empty = narrow_payload_for_pair(only_level, "s1", products[0])
    assert narrowed_empty.scope is not None
    assert narrowed_empty.scope.state is ScopeState.EMPTY
    assert narrowed_empty.scope.series_ids == ()


def test_shared_parse_provider_decodes_once_preserves_scope_known_series_annotations_and_releases_memory() -> None:
    products, cfg, decls = _shared_config()
    flow_known = _series_def("s1", products[0])
    level_known = _series_def("s1", products[1])
    req = ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=("s1",),
        products=products,
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
        ),
        scope=SeriesScope(
            provider_ids=("throwaway",),
            station_ids=("s1",),
            product_ids=("flow", "level"),
            restriction=RestrictionKind.EXPLICIT,
            series_ids=(flow_known.series_id, level_known.series_id),
        ),
        known_series=(flow_known, level_known),
    )

    obs_schema = AnnotationSchema(
        provider_id="throwaway",
        schema_id="obs_flag",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="flag", dtype="String", description="Source flag"),),
    )
    ser_schema = AnnotationSchema(
        provider_id="throwaway",
        schema_id="ser_note",
        scope=AnnotationScope.SERIES,
        fields=(AnnotationField(name="note", dtype="String", description="Series note"),),
    )

    parse_calls = 0
    parse_group_calls = 0
    received_contexts: list[tuple[tuple[str, ProductId], tuple[str, ...], tuple[str, ...]]] = []
    retained_refs: list[weakref.ref[object]] = []
    raw_bytes = b'{"shared":"payload-' + b"x" * 4096 + b'"}'

    class _GroupProvider:
        shared_acquisition_products = (frozenset(products),)
        config = cfg
        window_declarations = decls

        def fetch(self, stations, prod_arg, rendered_windows, window, config, transport, *, scope, known_series):
            payload = Payload(
                source_coordinates=cfg.products[products[0]].coordinates,
                station_products=tuple((stations[0], p) for p in prod_arg),
                fetch_window=window,
                content=raw_bytes,
                origin=_origin(),
                prerequisite_calls=(),
                scope=scope,
                known_series=known_series,
                acquisition_id="shared-acq-1",
            )
            return SourceAcquisition(value=(payload,))

        def parse_group(
            self,
            payload: Payload,
            pair_payloads: Mapping[tuple[str, ProductId], Payload],
            config: ProviderConfig,
        ) -> Mapping[tuple[str, ProductId], ParsedSeries]:
            nonlocal parse_group_calls
            parse_group_calls += 1
            assert payload.content == raw_bytes
            out: dict[tuple[str, ProductId], ParsedSeries] = {}
            for key, pair_payload in pair_payloads.items():
                assert pair_payload.scope is not None
                received_contexts.append(
                    (
                        key,
                        pair_payload.scope.series_ids,
                        tuple(item.series_id for item in pair_payload.known_series),
                    )
                )
                station, prod = key
                obs_ann = ObservationAnnotationTable.from_rows(
                    schema=obs_schema,
                    rows=pl.DataFrame(
                        {
                            "series_id": [f"{station}:{prod}"],
                            "facts_id": [f"{station}:{prod}:facts"],
                            "station_id": [station],
                            "product_id": [str(prod)],
                            "time": [datetime(2025, 1, 1)],
                            "time_zone": ["+00:00"],
                            "measured": [True],
                            "flag": ["A" if prod == "flow" else "B"],
                        },
                        schema={**OBSERVATION_STRUCTURAL_SCHEMA, **obs_schema.polars_schema()},
                    ),
                    measurement_indices=(0,),
                )
                ser_ann = SeriesAnnotationTable.from_rows(
                    schema=ser_schema,
                    rows=pl.DataFrame({"series_id": [f"{station}:{prod}"], "note": [f"note-{prod}"]}),
                )
                bundle = AnnotationBundle(
                    observation_tables={"obs_flag": obs_ann},
                    series_tables={"ser_note": ser_ann},
                )
                parsed = _parsed_for_pair(
                    pair_payload,
                    values=[(datetime(2025, 1, 1), 10.0 if prod == "flow" else 250.0)],
                    annotations=bundle,
                )
                retained_refs.append(weakref.ref(parsed.rows))
                retained_refs.append(weakref.ref(parsed.outcomes[0]))
                out[key] = parsed
            return out

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            nonlocal parse_calls
            parse_calls += 1
            raise AssertionError("parse() must not be called when parse_group handles >= 2 shared products")

    omit_res = driver_module.drive(req, _GroupProvider(), provenance=_provenance(req), receipts=ReceiptMode.OMIT)
    gc.collect()
    assert parse_group_calls == 1
    assert parse_calls == 0
    assert received_contexts == [
        (("s1", products[0]), (flow_known.series_id,), (flow_known.series_id,)),
        (("s1", products[1]), (level_known.series_id,), (level_known.series_id,)),
    ]
    assert omit_res.receipts.entries == ()
    assert omit_res.canonical_rows.height == 2
    assert set(omit_res.annotations.observation_tables["obs_flag"].rows["flag"].to_list()) == {"A", "B"}
    assert set(omit_res.annotations.series_tables["ser_note"].rows["note"].to_list()) == {"note-flow", "note-level"}
    assert all(ref() is None for ref in retained_refs)

    # Single-product request uses parse(), not parse_group().
    single_req = replace(req, products=(products[0],), scope=None, known_series=())
    single_parse_calls = 0
    single_group_calls = 0

    class _SingleCheckProvider(_GroupProvider):
        def parse_group(self, payload, pair_payloads, config):
            nonlocal single_group_calls
            single_group_calls += 1
            raise AssertionError("parse_group should not run for 1 product")

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            nonlocal single_parse_calls
            single_parse_calls += 1
            return _parsed_for_pair(payload, values=[(datetime(2025, 1, 1), 10.0)])

    single_res = driver_module.drive(
        single_req, _SingleCheckProvider(), provenance=_provenance(single_req), receipts=ReceiptMode.INCLUDE
    )
    assert single_group_calls == 0
    assert single_parse_calls == 1
    assert single_res.receipts.entries[0].content == raw_bytes

    # ReceiptMode.INCLUDE on shared request retains exact single publisher receipt.
    parse_group_calls = 0
    include_res = driver_module.drive(req, _GroupProvider(), provenance=_provenance(req), receipts=ReceiptMode.INCLUDE)
    assert parse_group_calls == 1
    assert len(include_res.receipts.entries) == 1
    assert include_res.receipts.entries[0].content == raw_bytes
    assert include_res.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD


def test_shared_parse_group_enforces_fatal_contracts_and_partial_handoff_interaction() -> None:
    products, cfg, decls = _shared_config()
    req = ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=("s1",),
        products=products,
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
        ),
    )

    class _Base:
        shared_acquisition_products = (frozenset(products),)
        config = cfg
        window_declarations = decls

        def fetch(self, stations, prod_arg, rendered_windows, window, config, transport, *, scope, known_series):
            payload = Payload(
                source_coordinates=cfg.products[products[0]].coordinates,
                station_products=tuple((stations[0], p) for p in prod_arg),
                fetch_window=window,
                content=b"{}",
                origin=_origin(),
                prerequisite_calls=(),
                scope=scope,
                known_series=known_series,
                acquisition_id="acq-contract",
            )
            return SourceAcquisition(value=(payload,))

        def parse(self, payload, config):
            return _parsed_for_pair(payload)

    class _NotMapping(_Base):
        def parse_group(self, payload, pair_payloads, config):
            return []  # type: ignore[return-value]

    class _MissingKey(_Base):
        def parse_group(self, payload, pair_payloads, config):
            first_key = next(iter(pair_payloads))
            return {first_key: _parsed_for_pair(pair_payloads[first_key])}

    class _BadValue(_Base):
        def parse_group(self, payload, pair_payloads, config):
            return dict.fromkeys(pair_payloads, "bad")  # type: ignore[dict-item]

    class _ZeroRowInvalidSeries(_Base):
        def parse_group(self, payload, pair_payloads, config):
            out = {}
            for key, pp in pair_payloads.items():
                parsed = _parsed_for_pair(pp, empty=True)
                if key[1] == "level":
                    bad_series = parsed.series[0].model_copy(update={"facts": ()})
                    parsed = replace(parsed, series=(bad_series,))
                out[key] = parsed
            return out

    class _FatalInside(_Base):
        def parse_group(self, payload, pair_payloads, config):
            raise FatalContractError("boom inside parse_group")

    for provider_cls, pattern in (
        (_NotMapping, "mapping"),
        (_MissingKey, "keys"),
        (_BadValue, "ParsedSeries"),
        (_ZeroRowInvalidSeries, "valid admitted physical facts"),
        (_FatalInside, "boom inside parse_group"),
    ):
        with pytest.raises(FatalContractError, match=pattern):
            driver_module.drive(req, provider_cls(), provenance=_provenance(req))

    # Partial interpretation handoff: 1st pair reuses handed-off InterpretedPayload; 2nd falls back to parse(), not parse_group().
    fallback_parse_calls = 0

    class _PartialHandoff(_Base):
        def fetch(self, stations, prod_arg, rendered_windows, window, config, transport, *, scope, known_series):
            acq = super().fetch(
                stations, prod_arg, rendered_windows, window, config, transport, scope=scope, known_series=known_series
            )
            shared = acq.value[0]
            flow_pair = narrow_payload_for_pair(shared, "s1", products[0])
            flow_parsed = _parsed_for_pair(flow_pair, values=[(datetime(2025, 1, 1), 99.0)])
            return replace(acq, interpretations=(InterpretedPayload.from_payload(flow_pair, flow_parsed),))

        def parse_group(self, payload, pair_payloads, config):
            raise AssertionError("Only 1 pair remained un-interpreted; parse() should run instead")

        def parse(self, payload, config):
            nonlocal fallback_parse_calls
            fallback_parse_calls += 1
            return _parsed_for_pair(payload, values=[(datetime(2025, 1, 1), 50.0)])

    partial_res = driver_module.drive(req, _PartialHandoff(), provenance=_provenance(req), receipts=ReceiptMode.OMIT)
    assert fallback_parse_calls == 1
    assert partial_res.canonical_rows.filter(pl.col("product_id") == "flow")["value"].to_list() == [99.0]
    assert partial_res.canonical_rows.filter(pl.col("product_id") == "level")["value"].to_list() == [pytest.approx(0.5)]


def test_shared_parse_group_refresh_preserves_held_success_on_product_and_shared_failures(tmp_path: Path) -> None:
    products, cfg, decls = _shared_config()
    store = StoreRoot(tmp_path / "shared_store")
    req = ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=("s1",),
        products=products,
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
        ),
    )
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)

    class _RefreshProvider:
        shared_acquisition_products = (frozenset(products),)
        config = cfg
        window_declarations = decls

        def __init__(self, mode: str, when: datetime) -> None:
            self.mode = mode
            self.when = when

        def fetch(self, stations, prod_arg, rendered_windows, window, config, transport, *, scope, known_series):
            payload = Payload(
                source_coordinates=cfg.products[products[0]].coordinates,
                station_products=tuple((stations[0], p) for p in prod_arg),
                fetch_window=window,
                content=b"{}",
                origin=_origin(self.when),
                prerequisite_calls=(),
                scope=scope,
                known_series=known_series,
                acquisition_id=f"acq-{self.mode}-{self.when.day}",
            )
            return SourceAcquisition(value=(payload,))

        def parse_group(self, payload, pair_payloads, config):
            out = {}
            for key, pp in pair_payloads.items():
                _, prod = key
                if self.mode == "seed":
                    out[key] = _parsed_for_pair(pp, values=[(datetime(2025, 1, 1), 10.0 if prod == "flow" else 20.0)])
                elif self.mode == "fail_level":
                    if prod == "level":
                        out[key] = _parsed_for_pair(pp, failed_reason="corrupt level column")
                    else:
                        out[key] = _parsed_for_pair(pp, values=[(datetime(2025, 1, 1), 30.0)])
                elif self.mode == "fail_all":
                    out[key] = _parsed_for_pair(pp, failed_reason="corrupt shared envelope")
            return out

        def parse(self, payload, config):
            raise AssertionError("parse_group handles all shared calls")

    seed = driver_module.drive(
        req, _RefreshProvider("seed", t1), provenance=_provenance(req), cache="reuse", store=store
    )
    assert seed.canonical_rows.height == 2

    partial_fail = driver_module.drive(
        req, _RefreshProvider("fail_level", t2), provenance=_provenance(req), cache="refresh", store=store
    )
    flow_row = partial_fail.canonical_rows.filter(pl.col("product_id") == "flow")
    level_row = partial_fail.canonical_rows.filter(pl.col("product_id") == "level")
    assert flow_row["value"].to_list() == [30.0]
    assert level_row["value"].to_list() == [pytest.approx(0.2)]
    assert [item.retrieved_at for item in partial_fail.provenance.served_intervals] == [t1]
    assert any(o.product_id == "level" and o.status is OutcomeStatus.FAILED for o in partial_fail.outcomes)

    all_fail = driver_module.drive(
        req, _RefreshProvider("fail_all", t2), provenance=_provenance(req), cache="refresh", store=store
    )
    pl_testing.assert_frame_equal(all_fail.canonical_rows.filter(pl.col("product_id") == "level"), level_row)
    assert all_fail.canonical_rows.filter(pl.col("product_id") == "flow")["value"].to_list() == [30.0]
    assert sorted(item.retrieved_at for item in all_fail.provenance.served_intervals) == [t1, t2]


def test_acquire_group_strips_bytes_under_omit_only_when_all_consumers_match_context() -> None:
    products, cfg, decls = _shared_config()
    from rivretrieve._internal.coverage import RequestedInterval
    from rivretrieve._internal.engine import _make_fetch_window
    from rivretrieve._internal.window_planning import plan_windows

    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
    )
    plans = tuple(
        driver_module._PairRetrieval(
            station="s1",
            product=prod,
            scope=SeriesScope(provider_ids=("throwaway",), station_ids=("s1",), product_ids=(str(prod),)),
            series=(),
            interval=RequestedInterval(datetime(2025, 1, 1), datetime(2025, 1, 1)),
            window=SeriesWindow(start=datetime(2025, 1, 1), end=datetime(2025, 1, 1)),
            reuse=None,
            fetch_window=fw,
            rendered=plan_windows(fw, decls.products[prod]),
        )
        for prod in products
    )
    shared = Payload(
        source_coordinates=cfg.products[products[0]].coordinates,
        station_products=tuple(("s1", prod) for prod in products),
        fetch_window=fw,
        content=b"raw-shared-bytes-" + b"z" * 1024,
        origin=_origin(),
        prerequisite_calls=(),
        scope=SeriesScope(provider_ids=("throwaway",), station_ids=("s1",), product_ids=("flow", "level")),
        known_series=(),
        acquisition_id="acq-strip-check",
    )
    interps = tuple(
        InterpretedPayload.from_payload(
            narrow_payload_for_pair(shared, "s1", prod), _parsed_for_pair(narrow_payload_for_pair(shared, "s1", prod))
        )
        for prod in products
    )
    acq_full = SourceAcquisition(value=(shared,), interpretations=interps)
    acquired_omit = driver_module._acquire_group(acq_full, plans, retain_bytes=False)
    assert acquired_omit.payload_slots[0] is not None
    assert acquired_omit.payload_slots[0].content == b""

    acquired_include = driver_module._acquire_group(acq_full, plans, retain_bytes=True)
    assert acquired_include.payload_slots[0] is not None
    assert acquired_include.payload_slots[0].content == shared.content

    acq_partial = SourceAcquisition(value=(shared,), interpretations=(interps[0],))
    acquired_partial = driver_module._acquire_group(acq_partial, plans, retain_bytes=False)
    assert acquired_partial.payload_slots[0] is not None
    assert acquired_partial.payload_slots[0].content == shared.content


def test_lt_lhmt_shared_responses_decode_once_across_all_success_and_failure_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json
    from types import SimpleNamespace

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    import rivretrieve._internal.providers.lt_lhmt.parse as lt_parse
    from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
    from rivretrieve._internal.providers.lt_lhmt.declaration import declaration
    from rivretrieve._internal.transport import TransportResponse

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "lt_cache"))
    monkeypatch.setenv("RIVRETRIEVE_REUSE_PACKAGED_CATALOGUES", "1")

    def month_doc(station: str, month: str, days: int = 3) -> dict[str, object]:
        return {
            "station": {"code": station},
            "observations": [
                {"observationDateUtc": f"{month}-{d:02d}", "waterDischarge": 10.0 + d, "waterLevel": 100 + d}
                for d in range(1, days + 1)
            ],
        }

    retrieved_1 = datetime(2026, 9, 27, tzinfo=UTC)
    retrieved_2 = datetime(2026, 9, 28, tzinfo=UTC)

    class _LtTransport:
        def __init__(self, responses: dict[str, bytes | int], when: datetime = retrieved_1) -> None:
            self.responses = responses
            self.when = when
            self.calls: list[str] = []

        def send(self, request):
            month = request.url.rsplit("/", 1)[-1]
            self.calls.append(month)
            body = self.responses.get(month, 404)
            return TransportResponse(
                content=body if isinstance(body, bytes) else b'{"error":"No data"}',
                status_code=200 if isinstance(body, bytes) else body,
                retrieved_at=self.when,
                content_type="application/json",
                url=request.url,
                request_parameters={},
            )

    decode_count = 0
    real_loads = json.loads

    def counting_loads(*args, **kwargs):
        nonlocal decode_count
        decode_count += 1
        return real_loads(*args, **kwargs)

    monkeypatch.setattr(lt_parse, "json", SimpleNamespace(loads=counting_loads, JSONDecodeError=json.JSONDecodeError))

    station = "anyksciu-vms"
    sel = rr.find(provider="lt_lhmt", station=station)
    # 1. Normal multi-month shared acquisition (null + absent row + empty month + 404).
    june = month_doc(station, "2023-06", days=4)
    assert isinstance(june["observations"], list)
    june["observations"][1]["waterLevel"] = None  # null value
    june["observations"].pop(2)  # absent row 2023-06-03
    may = {"station": {"code": station}, "observations": []}  # empty month
    t1 = _LtTransport({"2023-05": json.dumps(may).encode(), "2023-06": json.dumps(june).encode()}, retrieved_1)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t1)
    res_ok = rr.fetch(sel, start="2023-05-03", end="2023-07-28", cache="reuse", receipts=True, on_issue="ignore")
    assert t1.calls == ["2023-05", "2023-06", "2023-07"]
    assert decode_count == 2  # 1 per HTTP 200 monthly JSON response (never 2x)
    assert len(res_ok.receipts.entries) == 2
    assert res_ok.data.filter(pl.col("time") == datetime(2023, 6, 3)).is_empty()
    assert res_ok.data.filter((pl.col("time") == datetime(2023, 6, 2)) & (pl.col("quantity") == "stage"))[
        "value"
    ].to_list() == [None]

    # 2. Product-specific failure alongside healthy sibling + refresh preserves held stage & old vintage.
    decode_count = 0
    bad_stage = month_doc(station, "2023-06", days=3)
    bad_stage["observations"][0]["waterLevel"] = "bad-stage"  # type: ignore[index]
    bad_stage["observations"][1]["waterDischarge"] = 99.0  # type: ignore[index]
    t2 = _LtTransport({"2023-05": json.dumps(may).encode(), "2023-06": json.dumps(bad_stage).encode()}, retrieved_2)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t2)
    res_partial = rr.fetch(sel, start="2023-05-03", end="2023-06-03", cache="refresh", receipts=True, on_issue="ignore")
    assert decode_count == 2
    assert any(
        o.product_id == "stage_daily_mean" and o.status is OutcomeStatus.UNSUPPORTED for o in res_partial.outcomes
    )
    assert any(
        o.product_id == "discharge_daily_mean" and o.status is OutcomeStatus.SUCCESS for o in res_partial.outcomes
    )
    assert res_partial.data.filter(
        (pl.col("product_id") == "discharge_daily_mean") & (pl.col("time") == datetime(2023, 6, 2))
    )["value"].to_list() == [99.0]
    assert res_partial.data.filter(
        (pl.col("product_id") == "stage_daily_mean") & (pl.col("time") == datetime(2023, 6, 1))
    )["value"].to_list() == [pytest.approx(1.01)]
    assert any(item.retrieved_at == retrieved_1 for item in res_partial.provenance.served_intervals)

    # 3. Shared malformed JSON + double-fault precedence (bad stage on row 0, bad date on row 2).
    decode_count = 0
    t3 = _LtTransport({"2023-06": b"{corrupt"}, retrieved_2)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t3)
    res_corrupt = rr.fetch(sel, start="2023-06-03", end="2023-06-03", cache="bypass", on_issue="ignore")
    assert decode_count == 1
    assert [o.status for o in res_corrupt.outcomes] == [OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNSUPPORTED]

    double_fault = month_doc(station, "2023-06", days=3)
    double_fault["observations"][0]["waterLevel"] = "bad"  # type: ignore[index]
    double_fault["observations"][2]["observationDateUtc"] = "not-a-date"  # type: ignore[index]
    decode_count = 0
    t4 = _LtTransport({"2023-06": json.dumps(double_fault).encode()}, retrieved_2)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t4)
    res_df = rr.fetch(sel, start="2023-06-01", end="2023-06-03", cache="bypass", on_issue="ignore")
    assert decode_count == 1
    by_prod = {o.product_id: o for o in res_df.outcomes}
    assert by_prod["stage_daily_mean"].status is OutcomeStatus.UNSUPPORTED
    assert "waterLevel" in (by_prod["stage_daily_mean"].reason or "")
    assert by_prod["discharge_daily_mean"].status is OutcomeStatus.UNSUPPORTED
    assert "observationDateUtc" in (by_prod["discharge_daily_mean"].reason or "")

    # 4. Direct multi-pair parse() call also decodes once.
    stages = declaration.observations.stages
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 6, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 6, 3)),
    )
    direct_payload = Payload(
        source_coordinates=stages.config.products[ProductId("discharge_daily_mean")].coordinates,
        station_products=((station, ProductId("discharge_daily_mean")), (station, ProductId("stage_daily_mean"))),
        fetch_window=fw,
        content=json.dumps(month_doc(station, "2023-06", days=2)).encode(),
        origin=_origin(),
        prerequisite_calls=(),
    )
    decode_count = 0
    direct_parsed = stages.parse(direct_payload, stages.config)
    assert decode_count == 1
    assert direct_parsed.rows.height == 4


def test_pe_senamhi_shared_and_phisis_responses_decode_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import json
    from dataclasses import dataclass
    from types import SimpleNamespace

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    import rivretrieve._internal.providers.pe_senamhi.fetch as pe_fetch
    import rivretrieve._internal.providers.pe_senamhi.parse as pe_parse
    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.engine import (
        ObservationRequest,
        RequestedWindow,
        WindowEndpoint,
    )
    from rivretrieve._internal.providers.pe_senamhi.declaration import declaration
    from rivretrieve._internal.providers.pe_senamhi.series import MONTHLY_LEVEL_FIELDS
    from rivretrieve._internal.transport import TransportResponse
    from tests.test_internal_driver import _provenance

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "pe_cache"))
    monkeypatch.setenv("RIVRETRIEVE_REUSE_PACKAGED_CATALOGUES", "1")

    decode_count = 0
    real_loads = json.loads

    def counting_loads(*args, **kwargs):
        nonlocal decode_count
        decode_count += 1
        return real_loads(*args, **kwargs)

    proxy_json = SimpleNamespace(loads=counting_loads, JSONDecodeError=json.JSONDecodeError)
    monkeypatch.setattr(pe_parse, "json", proxy_json)
    if hasattr(pe_fetch, "json"):
        monkeypatch.setattr(pe_fetch, "json", proxy_json)

    retrieved_1 = datetime(2026, 9, 27, tzinfo=UTC)
    retrieved_2 = datetime(2026, 9, 28, tzinfo=UTC)

    class _PeTransport:
        def __init__(self, body: bytes, when: datetime = retrieved_1) -> None:
            self.body = body
            self.when = when
            self.calls = 0

        def send(self, request):
            self.calls += 1
            return TransportResponse(
                content=self.body,
                status_code=200,
                retrieved_at=self.when,
                content_type="application/json",
                url=request.url,
                request_parameters=request.params,
            )

    station = "214901"
    five_fields = [
        "NIVEL_DEL_RIO_06H",
        "NIVEL_DEL_RIO_10H",
        "NIVEL_DEL_RIO_14H",
        "NIVEL_DEL_RIO_18H",
        "NIVEL_DEL_RIO_PROMEDIO",
    ]
    monthly_doc = {
        "status": True,
        "data": {
            "columns": [{"column": field, "unit": "m"} for field in five_fields],
            "readings": [
                {
                    "date": "2024-01-10",
                    "time": "",
                    "values": [
                        {"column": "NIVEL_DEL_RIO_06H", "value": 1.2},
                        {"column": "NIVEL_DEL_RIO_10H", "value": None},
                        {"column": "NIVEL_DEL_RIO_14H", "value": 1.4},
                        {"column": "NIVEL_DEL_RIO_18H", "value": 1.8},
                        # NIVEL_DEL_RIO_PROMEDIO intentionally absent on this row
                    ],
                },
                {
                    "date": "2024-01-11",
                    "time": "",
                    "values": [{"column": field, "value": 2.0 + idx} for idx, field in enumerate(five_fields)],
                },
            ],
        },
    }

    # Spy declaration stages parse / parse_group to assert 0 fallback calls during normal fetch.
    stages = declaration.observations.stages
    fallback_calls = 0
    real_parse = stages.parse
    real_parse_group = getattr(stages, "parse_group", None)

    def tracked_parse(*args, **kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(stages, "parse", tracked_parse)
    if real_parse_group is not None:

        def tracked_parse_group(*args, **kwargs):
            nonlocal fallback_calls
            fallback_calls += 1
            return real_parse_group(*args, **kwargs)

        monkeypatch.setattr(stages, "parse_group", tracked_parse_group)

    # 1. 5-product shared monthly_archive via rr.find and rr.pick(..., series_id=...).
    sel = rr.find(provider="pe_senamhi", station=station)
    t_ok = _PeTransport(json.dumps(monthly_doc).encode(), retrieved_1)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_ok)
    decode_count = 0
    fallback_calls = 0
    res_find = rr.fetch(sel, start="2024-01-10", end="2024-01-11", cache="bypass", receipts=True, on_issue="ignore")
    assert t_ok.calls == 1
    assert decode_count == 1
    assert fallback_calls == 0
    assert len(res_find.receipts.entries) == 1
    assert {o.status for o in res_find.outcomes} == {OutcomeStatus.SUCCESS}
    assert res_find.data.filter(pl.col("product_id") == "monthly_archive_nivel_del_rio_10h")["value"].to_list() == [
        None,
        3.0,
    ]
    assert res_find.data.filter(pl.col("product_id") == "monthly_archive_nivel_del_rio_promedio")["time"].to_list() == [
        datetime(2024, 1, 11)
    ]

    sel_table = rr.as_frame(sel)
    picked_ids = sel_table.filter(
        pl.col("product_id").is_in(["monthly_archive_nivel_del_rio_06h", "monthly_archive_nivel_del_rio_14h"])
    )["series_id"].to_list()
    sel_pick = rr.pick(sel, series_id=picked_ids)
    t_pick = _PeTransport(json.dumps(monthly_doc).encode(), retrieved_1)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_pick)
    decode_count = 0
    fallback_calls = 0
    res_pick = rr.fetch(sel_pick, start="2024-01-10", end="2024-01-11", cache="reuse", receipts=True, on_issue="ignore")
    assert t_pick.calls == 1
    assert decode_count == 1
    assert fallback_calls == 0
    assert sorted(res_pick.data["product_id"].unique().to_list()) == [
        "monthly_archive_nivel_del_rio_06h",
        "monthly_archive_nivel_del_rio_14h",
    ]

    # Store full 5 products in cache for subsequent cache="refresh" checks.
    t_seed = _PeTransport(json.dumps(monthly_doc).encode(), retrieved_1)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_seed)
    rr.fetch(sel, start="2024-01-10", end="2024-01-11", cache="reuse", on_issue="ignore")

    # 2. Synthetic 9-product shared monthly_archive via drive().
    nine_fields = sorted(MONTHLY_LEVEL_FIELDS)
    nine_doc = {
        "status": True,
        "data": {
            "columns": [{"column": f, "unit": "m"} for f in nine_fields],
            "readings": [
                {
                    "date": "2024-01-10",
                    "time": "",
                    "values": [{"column": f, "value": 1.0 + i} for i, f in enumerate(nine_fields)],
                }
            ],
        },
    }
    t_nine = _PeTransport(json.dumps(nine_doc).encode(), retrieved_1)
    decode_count = 0
    fallback_calls = 0
    req_nine = ObservationRequest(
        provider_id=ProviderId("pe_senamhi"),
        stations=("214901",),
        products=tuple(ProductId(f"monthly_archive_{f.lower()}") for f in nine_fields),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 10)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 10, 23, 59, 59)),
        ),
    )
    res_nine = drive(
        req_nine,
        stages,
        provenance=_provenance(req_nine),
        receipts=ReceiptMode.OMIT,
        transport=t_nine,
    )
    assert t_nine.calls == 1
    assert decode_count == 1
    assert fallback_calls == 0
    assert res_nine.canonical_rows.height == 9

    # 3. Envelope failure & malformed JSON under cache="refresh" -> 1 decode total, HELD preserved.
    for bad_body in (json.dumps({"status": False, "message": "source refusal"}).encode(), b"{corrupt"):
        t_fail = _PeTransport(bad_body, retrieved_2)
        monkeypatch.setattr(discovery, "HttpClient", lambda t_fail=t_fail: t_fail)
        decode_count = 0
        res_fail = rr.fetch(sel, start="2024-01-10", end="2024-01-11", cache="refresh", on_issue="ignore")
        assert decode_count == 1
        assert {o.product_id for o in res_fail.outcomes if o.status is OutcomeStatus.FAILED} == {
            f"monthly_archive_{f.lower()}" for f in five_fields
        }
        assert any(i.code == "source.response_failed" for i in res_fail.issues)
        assert not any(i.code == "unsupported_source_structure" for i in res_fail.issues)
        assert not res_fail.data.is_empty()
        assert any(item.retrieved_at == retrieved_1 for item in res_fail.provenance.served_intervals)

    # 4. Product-specific structural failure alongside 4 healthy siblings + double-fault precedence.
    partial_doc = {
        "status": True,
        "data": {
            "columns": [
                {"column": "NIVEL_DEL_RIO_06H", "unit": "cm"},  # unsupported unit for 06h only
                *({"column": f, "unit": "m"} for f in five_fields[1:]),
            ],
            "readings": [
                {
                    "date": "2024-01-10",
                    "time": "",
                    "values": [{"column": f, "value": 9.0} for f in five_fields],
                }
            ],
        },
    }
    t_partial = _PeTransport(json.dumps(partial_doc).encode(), retrieved_2)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_partial)
    decode_count = 0
    res_partial = rr.fetch(sel, start="2024-01-10", end="2024-01-11", cache="refresh", on_issue="ignore")
    assert decode_count == 1
    statuses_by_prod: dict[str, set[OutcomeStatus]] = {}
    for o in res_partial.outcomes:
        statuses_by_prod.setdefault(o.product_id, set()).add(o.status)
    assert OutcomeStatus.UNSUPPORTED in statuses_by_prod["monthly_archive_nivel_del_rio_06h"]
    for healthy in five_fields[1:]:
        assert statuses_by_prod[f"monthly_archive_{healthy.lower()}"] == {OutcomeStatus.SUCCESS}
    assert res_partial.data.filter(
        (pl.col("product_id") == "monthly_archive_nivel_del_rio_06h") & (pl.col("time") == datetime(2024, 1, 10))
    )["value"].to_list() == [1.2]
    assert res_partial.data.filter(
        (pl.col("product_id") == "monthly_archive_nivel_del_rio_10h") & (pl.col("time") == datetime(2024, 1, 10))
    )["value"].to_list() == [9.0]

    double_fault_doc = {
        "status": True,
        "data": {
            "columns": [{"column": f, "unit": "m"} for f in five_fields],
            "readings": [
                {"date": "2024-01-10", "time": "", "values": [{"column": "NIVEL_DEL_RIO_06H", "value": "bad-num"}]},
                {"date": "not-a-date", "time": "", "values": [{"column": "NIVEL_DEL_RIO_10H", "value": 1.0}]},
            ],
        },
    }
    t_df = _PeTransport(json.dumps(double_fault_doc).encode(), retrieved_2)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_df)
    decode_count = 0
    res_df = rr.fetch(sel, start="2024-01-10", end="2024-01-11", cache="bypass", on_issue="ignore")
    assert decode_count == 1
    df_by_prod = {o.product_id: o for o in res_df.outcomes}
    assert "numeric" in (df_by_prod["monthly_archive_nivel_del_rio_06h"].reason or "")
    assert "timestamp" in (df_by_prod["monthly_archive_nivel_del_rio_10h"].reason or "").lower()

    # 5. Single-product phisis_daily_flow (3 fields: current/minimum/maximum) -> 1 decode total + per-field isolation.
    phisis_sel = rr.find(provider="pe_senamhi", station="47251282")
    phisis_ids = rr.as_frame(phisis_sel).filter(pl.col("product_id") == "phisis_daily_flow")["series_id"].to_list()
    phisis_pick = rr.pick(phisis_sel, series_id=phisis_ids)
    phisis_doc = {
        "status": True,
        "data": {
            "station": {"code": "47251282"},
            "type": "DAILY",
            "variable": "FLOW",
            "unit": "m3/s",
            "daily": [{"date": "2024-01-02", "current": -9, "minimum": "bad-min", "maximum": 7}],
        },
    }
    t_ph = _PeTransport(json.dumps(phisis_doc).encode(), retrieved_1)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_ph)
    decode_count = 0
    res_ph = rr.fetch(phisis_pick, start="2024-01-02", end="2024-01-02T23:59:59", cache="bypass", on_issue="ignore")
    assert t_ph.calls == 1
    assert decode_count == 1
    assert {o.status for o in res_ph.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.UNSUPPORTED}
    assert res_ph.data.height == 2

    # 6. Context-change fallback (strip interpretations=()) -> fallback parse_group decodes once (total = 2).
    @dataclass(frozen=True)
    class _StrippedStages:
        config: ProviderConfig = stages.config
        window_declarations: ProductWindowDeclarations = stages.window_declarations
        shared_acquisition_products = stages.shared_acquisition_products
        parse = staticmethod(real_parse)
        parse_group = staticmethod(real_parse_group) if real_parse_group is not None else None

        @staticmethod
        def fetch(*args, **kwargs):
            from dataclasses import replace

            return replace(stages.fetch(*args, **kwargs), interpretations=())

    t_fb = _PeTransport(json.dumps(monthly_doc).encode(), retrieved_1)
    decode_count = 0
    req_fb = ObservationRequest(
        provider_id=ProviderId("pe_senamhi"),
        stations=("214901",),
        products=tuple(ProductId(f"monthly_archive_{f.lower()}") for f in five_fields),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 10)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 11, 23, 59, 59)),
        ),
    )
    res_fb = drive(
        req_fb,
        _StrippedStages(),  # type: ignore[arg-type]
        provenance=_provenance(req_fb),
        receipts=ReceiptMode.OMIT,
        transport=t_fb,
    )
    assert decode_count == 2  # 1 in fetch + 1 in fallback parse_group (never 1 + 5)
    assert res_fb.canonical_rows.height == 9


def test_at_ehyd_shared_responses_decode_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import json
    from dataclasses import dataclass, replace
    from types import SimpleNamespace

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    import rivretrieve._internal.providers.at_ehyd.fetch as at_fetch
    import rivretrieve._internal.providers.at_ehyd.parse as at_parse
    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.engine import (
        ObservationRequest,
        RequestedWindow,
        SourceCoordinates,
        WindowEndpoint,
        _make_fetch_window,
    )
    from rivretrieve._internal.providers.at_ehyd.config import (
        AtEhydInfoCoordinates,
        AtEhydPegelEndpointCoordinates,
    )
    from rivretrieve._internal.providers.at_ehyd.declaration import declaration
    from rivretrieve._internal.providers.at_ehyd.series import IN_SCOPE_OWF_FTYPES, OWF_INTERVAL_RULE_TEXT
    from rivretrieve._internal.transport import TransportResponse
    from tests.test_internal_driver import _provenance

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "at_cache"))
    monkeypatch.setenv("RIVRETRIEVE_REUSE_PACKAGED_CATALOGUES", "1")

    decode_count = 0
    real_loads = json.loads

    def counting_loads(*args, **kwargs):
        nonlocal decode_count
        decode_count += 1
        return real_loads(*args, **kwargs)

    proxy_json = SimpleNamespace(loads=counting_loads, JSONDecodeError=json.JSONDecodeError)
    monkeypatch.setattr(at_parse, "json", proxy_json)
    if hasattr(at_fetch, "json"):
        monkeypatch.setattr(at_fetch, "json", proxy_json)

    retrieved_1 = datetime(2026, 9, 27, tzinfo=UTC)
    retrieved_2 = datetime(2026, 9, 28, tzinfo=UTC)

    def info_bytes(station: str, files: list[tuple[int, str]]) -> bytes:
        return json.dumps(
            [
                {
                    "caption": "Messstelle",
                    "data": [
                        {
                            "info": {
                                "data": [
                                    {"caption": "HZBNR", "text": int(station)},
                                    {
                                        "tag": "dl_mstfiles",
                                        "data": {
                                            "fileData": [
                                                {
                                                    "fileNr": nr,
                                                    "fileName": f"{prefix}-{station}.csv",
                                                    "hzbnr": int(station),
                                                    "msttyp": "owf",
                                                }
                                                for nr, prefix in files
                                            ]
                                        },
                                    },
                                ]
                            }
                        }
                    ],
                }
            ]
        ).encode("utf-8")

    def owf_csv(station: str, descriptor: str, unit: str, value_str: str) -> bytes:
        return "\r\n".join(
            [
                "Stammdaten:",
                "Messstelle:                ;Testpegel",
                f"HZB-Nummer:                ;{station}",
                f"Einheit:                   ;{unit}",
                f"Exportzeitreihe:           ;{descriptor}",
                f"Zeitreihenart:             ;{OWF_INTERVAL_RULE_TEXT}",
                "Exportzeitraum:            ;[01.01.2020 00:00,03.01.2020 00:00]",
                "Werte:",
                f"01.01.2020 00:00:00; {value_str}",
                "02.01.2020 00:00:00; Lücke",
                "03.01.2020 00:00:00; Lücke",
                "",
            ]
        ).encode("cp1252")

    class _AtTransport:
        def __init__(self, handler) -> None:
            self.handler = handler
            self.requests: list[tuple[str, dict[str, str]]] = []

        def send(self, request):
            params = dict(request.params or {})
            self.requests.append((request.url, params))
            body, ctype, when = self.handler(request.url, params)
            return TransportResponse(
                content=body,
                status_code=200,
                retrieved_at=when,
                content_type=ctype,
                url=request.url,
                request_parameters=params,
            )

    stages = declaration.observations.stages
    fallback_info_calls = 0
    real_parse = stages.parse
    real_parse_group = getattr(stages, "parse_group", None)

    def tracked_parse(payload, config):
        nonlocal fallback_info_calls
        if isinstance(payload.source_coordinates.value, AtEhydInfoCoordinates):
            fallback_info_calls += 1
        return real_parse(payload, config)

    monkeypatch.setattr(stages, "parse", tracked_parse)
    if real_parse_group is not None:

        def tracked_parse_group(payload, pair_payloads, config):
            nonlocal fallback_info_calls
            if isinstance(payload.source_coordinates.value, AtEhydInfoCoordinates):
                fallback_info_calls += 1
            return real_parse_group(payload, pair_payloads, config)

        monkeypatch.setattr(stages, "parse_group", tracked_parse_group)

    # 1. Multi-product owf on real catalogue station 207704 (6 owf products).
    owf_station = "207704"
    valid_info = info_bytes(owf_station, [(2, "W-Tagesmittel"), (4, "Q-Tagesmittel")])
    q_csv = owf_csv(owf_station, "Abfluss,I,mit,T,1", "[m³/s]", "15,5")
    w_csv = owf_csv(owf_station, "Wasserstand,I,mit,T,1", "[cm]", "250")

    def ok_handler(url: str, params: dict[str, str]):
        if url.endswith("/Messstellen/info"):
            return valid_info, "application/json", retrieved_1
        if url.endswith("/MessstellenExtraData/owf") and params.get("file") == "4":
            return q_csv, "text/csv", retrieved_1
        if url.endswith("/MessstellenExtraData/owf") and params.get("file") == "2":
            return w_csv, "text/csv", retrieved_1
        return (
            json.dumps(
                {
                    "hzbnr": int(owf_station),
                    "parameter": "Abfluss",
                    "einheit": "m³/s",
                    "valCount": 0,
                    "categories": [],
                    "data": [],
                }
            ).encode(),
            "application/json",
            retrieved_1,
        )

    sel_owf_all = rr.find(provider="at_ehyd", station=owf_station)
    owf_table = rr.as_frame(sel_owf_all).filter(pl.col("product_id").is_in(list(IN_SCOPE_OWF_FTYPES)))
    assert owf_table["product_id"].n_unique() >= 4
    sel_owf = rr.pick(sel_owf_all, series_id=owf_table["series_id"].to_list())
    t_owf = _AtTransport(ok_handler)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_owf)
    decode_count = 0
    fallback_info_calls = 0
    res_owf = rr.fetch(
        sel_owf, start="2020-01-01", end="2020-01-02T23:59:59", cache="reuse", receipts=True, on_issue="ignore"
    )
    assert decode_count == 1  # Messstellen/info decoded ONCE across fetch+parse
    assert fallback_info_calls == 0
    assert len(res_owf.receipts.entries) == 3  # 1 Messstellen/info + 2 CSVs
    assert any(o.product_id == "owf_abfl_monatsmaxima" and o.status is OutcomeStatus.NO_MATCH for o in res_owf.outcomes)
    assert any(i.code == "source.no_match" for i in res_owf.issues)
    assert "Geprüfte Daten" in rr.series(res_owf, annotations=True)["data_quality"].to_list()
    assert res_owf.data.filter(pl.col("product_id") == "owf_wasserst_tagesmittel")["value"].to_list() == [
        pytest.approx(2.5),
    ]
    assert any(i.code == "source.gap_marker" for i in res_owf.issues)

    # Pick subset including 1 present CSV + 2 missing owf products -> still 1 decode.
    subset_ids = owf_table.filter(
        pl.col("product_id").is_in(["owf_abfl_tagesmittel", "owf_abfl_monatsmaxima", "owf_abfl_monatsminima"])
    )["series_id"].to_list()
    t_owf_sub = _AtTransport(ok_handler)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_owf_sub)
    decode_count = 0
    fallback_info_calls = 0
    res_owf_sub = rr.fetch(
        rr.pick(sel_owf_all, series_id=subset_ids),
        start="2020-01-01",
        end="2020-01-02T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert decode_count == 1
    assert fallback_info_calls == 0
    assert res_owf_sub.data["value"].to_list() == [15.5]

    # Corrupt Messstellen/info under cache="refresh" -> 1 decode, FAILED + source.unsupported_structure, HELD preserved.
    def bad_info_handler(url: str, params: dict[str, str]):
        if url.endswith("/Messstellen/info"):
            return b"{corrupt", "application/json", retrieved_2
        raise AssertionError(f"Unexpected child request: {url}")

    t_bad_info = _AtTransport(bad_info_handler)
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_bad_info)
    decode_count = 0
    res_bad_info = rr.fetch(sel_owf, start="2020-01-01", end="2020-01-02T23:59:59", cache="refresh", on_issue="ignore")
    assert decode_count == 1
    assert any(o.status is OutcomeStatus.FAILED for o in res_bad_info.outcomes)
    assert any(i.code == "source.unsupported_structure" for i in res_bad_info.issues)
    assert not res_bad_info.data.is_empty()
    assert any(item.retrieved_at == retrieved_1 for item in res_bad_info.provenance.served_intervals)

    # 2. Shared pegel_bgis (2 products -> 1 decode), including empty 200 (0 decodes) & corrupt (1 decode).
    bgis_station = "201913"
    bgis_doc = json.dumps(
        {
            "hzbnr": int(bgis_station),
            "parameter": "Abfluss",
            "einheit": "m³/s",
            "valCount": 1,
            "categories": ["2026-10-31 10:00:00"],
            "data": [22.5],
        }
    ).encode()
    req_bgis = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(bgis_station,),
        products=(ProductId("pegel_bgis_abfluss"), ProductId("pegel_bgis_wasserstand")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 31)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 31, 23, 59, 59)),
        ),
    )
    t_bgis = _AtTransport(lambda url, params: (bgis_doc, "application/json", retrieved_1))
    decode_count = 0
    res_bgis = drive(req_bgis, stages, provenance=_provenance(req_bgis), transport=t_bgis)
    assert len(t_bgis.requests) == 1
    assert decode_count == 1
    assert OutcomeStatus.SUCCESS in {o.status for o in res_bgis.outcomes if o.product_id == "pegel_bgis_abfluss"}
    assert {o.status for o in res_bgis.outcomes if o.product_id == "pegel_bgis_wasserstand"} == {OutcomeStatus.NO_MATCH}
    assert res_bgis.annotations.series_tables["at_ehyd.series"].rows["data_quality"].to_list() == [
        "ungeprüfte Rohdaten!"
    ]

    for body, expected_decodes, expected_status in (
        (b"", 0, OutcomeStatus.UNRESOLVED),
        (b"{corrupt", 1, OutcomeStatus.FAILED),
    ):
        t_edge = _AtTransport(lambda url, params, b=body: (b, "application/json", retrieved_1))
        decode_count = 0
        res_edge = drive(req_bgis, stages, provenance=_provenance(req_bgis), transport=t_edge)
        assert decode_count == expected_decodes
        assert {o.status for o in res_edge.outcomes} == {expected_status}
        assert len({o.product_id for o in res_edge.outcomes}) == 2

    # 3. Shared pegel_longterm (2 products -> 1 decode), including empty skeleton (1 decode).
    lt_doc = {
        "parameter": "Abfluss",
        "einheit": "m³/s",
        "points_in_time": ["2026-10-29", "2026-10-30"],
        "current_value": [10.5, 11.5],
    }
    lt_skeleton = {
        k: []
        for k in (
            "points_in_time",
            "current_value",
            "min_data",
            "min_year",
            "max_data",
            "max_year",
            "mit_data",
            "p5_data",
            "p95_data",
            "last_year_value",
        )
    }
    for body, expected_statuses in (
        (json.dumps(lt_doc).encode(), {OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED, OutcomeStatus.NO_MATCH}),
        (json.dumps(lt_skeleton).encode(), {OutcomeStatus.UNRESOLVED}),
    ):
        req_lt = ObservationRequest(
            provider_id=ProviderId("at_ehyd"),
            stations=("209486",),
            products=(ProductId("pegel_longterm_abfluss"), ProductId("pegel_longterm_wasserstand")),
            window=RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 10, 29)),
                WindowEndpoint.from_datetime(datetime(2026, 10, 31)),
            ),
        )
        t_lt = _AtTransport(lambda url, params, b=body: (b, "application/json", retrieved_1))
        decode_count = 0
        res_lt = drive(req_lt, stages, provenance=_provenance(req_lt), transport=t_lt)
        assert len(t_lt.requests) == 1
        assert decode_count == 1
        assert {o.status for o in res_lt.outcomes} == expected_statuses

    # 4. Context-change fallback on Messstellen/info (strip interpretations=()) -> 1 fallback parse_group decode.
    @dataclass(frozen=True)
    class _StrippedAtStages:
        config: ProviderConfig = stages.config
        window_declarations: ProductWindowDeclarations = stages.window_declarations
        shared_acquisition_products = stages.shared_acquisition_products
        parse = staticmethod(real_parse)
        parse_group = staticmethod(real_parse_group) if real_parse_group is not None else None

        @staticmethod
        def fetch(*args, **kwargs):
            return replace(stages.fetch(*args, **kwargs), interpretations=())

    req_fb = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(owf_station,),
        products=(
            ProductId("owf_abfl_tagesmittel"),
            ProductId("owf_abfl_monatsmaxima"),
            ProductId("owf_abfl_monatsminima"),
        ),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2020, 1, 2, 23, 59, 59)),
        ),
    )
    t_fb = _AtTransport(ok_handler)
    decode_count = 0
    res_fb = drive(req_fb, _StrippedAtStages(), provenance=_provenance(req_fb), transport=t_fb)  # type: ignore[arg-type]
    assert decode_count == 2  # 1 in fetch + 1 in fallback parse_group (never 1 + 3)
    assert res_fb.canonical_rows["value"].to_list() == [15.5]

    # 5. Direct multi-pair parse() on AtEhydInfoCoordinates & AtEhydPegelEndpointCoordinates decodes once.
    fw_info = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2020, 1, 2)),
    )
    direct_info_payload = Payload(
        source_coordinates=SourceCoordinates(AtEhydInfoCoordinates()),
        station_products=(
            (owf_station, ProductId("owf_abfl_monatsmaxima")),
            (owf_station, ProductId("owf_abfl_monatsminima")),
        ),
        fetch_window=fw_info,
        content=valid_info,
        origin=_origin(),
        prerequisite_calls=(),
    )
    decode_count = 0
    direct_info_res = real_parse(direct_info_payload, stages.config)
    assert decode_count == 1
    assert {o.status for o in direct_info_res.outcomes} == {OutcomeStatus.NO_MATCH}

    direct_bgis_payload = Payload(
        source_coordinates=SourceCoordinates(AtEhydPegelEndpointCoordinates("pegel_bgis")),
        station_products=(
            (bgis_station, ProductId("pegel_bgis_abfluss")),
            (bgis_station, ProductId("pegel_bgis_wasserstand")),
        ),
        fetch_window=_make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2026, 10, 31)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 31, 23, 59, 59)),
        ),
        content=bgis_doc,
        origin=_origin(),
        prerequisite_calls=(),
    )
    decode_count = 0
    direct_bgis_res = real_parse(direct_bgis_payload, stages.config)
    assert decode_count == 1
    assert not direct_bgis_res.annotations.is_empty
    assert direct_bgis_res.annotations.series_tables["at_ehyd.series"].rows["data_quality"].to_list() == [
        "ungeprüfte Rohdaten!"
    ]


def test_review_regressions_unhashable_pe_column_and_explicit_mixed_series_ids_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from types import SimpleNamespace

    import rivretrieve._internal.providers.pe_senamhi.parse as pe_parse
    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.engine import (
        ObservationRequest,
        RequestedWindow,
        WindowEndpoint,
    )
    from rivretrieve._internal.providers.pe_senamhi.declaration import declaration
    from rivretrieve._internal.providers.pe_senamhi.series import series_mappings
    from rivretrieve._internal.transport import TransportResponse
    from tests.test_internal_driver import _provenance

    stages = declaration.observations.stages
    decode_count = 0
    fallback_calls = 0
    real_loads = json.loads

    def counting_loads(*args, **kwargs):
        nonlocal decode_count
        decode_count += 1
        return real_loads(*args, **kwargs)

    monkeypatch.setattr(pe_parse, "json", SimpleNamespace(loads=counting_loads, JSONDecodeError=json.JSONDecodeError))
    real_parse = stages.parse
    real_parse_group = stages.parse_group

    def tracked_parse(*args, **kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return real_parse(*args, **kwargs)

    def tracked_parse_group(*args, **kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return real_parse_group(*args, **kwargs)

    monkeypatch.setattr(stages, "parse", tracked_parse)
    monkeypatch.setattr(stages, "parse_group", tracked_parse_group)

    station = "214901"
    p1 = ProductId("monthly_archive_nivel_del_rio_06h")
    p2 = ProductId("monthly_archive_nivel_del_rio_10h")
    s1 = series_mappings("monthly_archive", None, "NIVEL_DEL_RIO_06H", "m")["NIVEL_DEL_RIO_06H"].source_series(
        "pe_senamhi", station, str(p1)
    )
    s2 = series_mappings("monthly_archive", None, "NIVEL_DEL_RIO_10H", "m")["NIVEL_DEL_RIO_10H"].source_series(
        "pe_senamhi", station, str(p2)
    )

    body = json.dumps(
        {
            "status": True,
            "data": {
                "columns": [
                    {"column": "NIVEL_DEL_RIO_06H", "unit": "m"},
                    {"column": "NIVEL_DEL_RIO_10H", "unit": "m"},
                ],
                "readings": [
                    {
                        "date": "2024-01-10",
                        "time": "",
                        "values": [
                            {"column": ["unhashable"], "value": 999.0},
                            {"column": "NIVEL_DEL_RIO_06H", "value": 1.25},
                            {"column": "NIVEL_DEL_RIO_10H", "value": 2.5},
                        ],
                    }
                ],
            },
        }
    ).encode()

    class _Trans:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request):
            self.calls += 1
            return TransportResponse(
                content=body,
                status_code=200,
                retrieved_at=datetime(2026, 9, 27, tzinfo=UTC),
                content_type="application/json",
                url=request.url,
                request_parameters=request.params,
            )

    transport = _Trans()
    req = ObservationRequest(
        provider_id=ProviderId("pe_senamhi"),
        stations=(station,),
        products=(p1, p2),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 10)),
            WindowEndpoint.from_datetime(datetime(2024, 2, 10, 23, 59, 59)),
        ),
        known_series=(s1, s2),
        scope=SeriesScope(
            provider_ids=("pe_senamhi",),
            station_ids=(station,),
            product_ids=(str(p1), str(p2)),
            restriction=RestrictionKind.EXPLICIT,
            series_ids=(s1.series_id, s2.series_id, "unknown-series-id"),
        ),
    )
    res = drive(req, stages, provenance=_provenance(req), receipts=ReceiptMode.OMIT, transport=transport)
    assert transport.calls >= 2
    assert decode_count == transport.calls  # 1 decode per response (never 2x on mixed EXPLICIT series_ids)
    assert fallback_calls == 0
    assert sorted(res.canonical_rows["value"].to_list()) == [1.25, 2.5]
