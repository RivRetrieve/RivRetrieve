"""Source-independent contract tests for context-bound interpretation handoff."""

from __future__ import annotations

import gc
import weakref
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import (
    InterpretationContext,
    InterpretedPayload,
    ObservationRequest,
    Payload,
    ProviderConfig,
    RenderedWindow,
    RowsSchema,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ReceiptAuthorship, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.request_planning import ObservationPlan, PlannedObservationRequest
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
)
from rivretrieve._internal.time_axis import TimeAxis
from rivretrieve._internal.transport import HttpMethod, TransportAttempt, TransportRequest, TransportResponse
from rivretrieve._internal.window_acquisition import WindowAcquisition, WindowResponseMeaning, acquire_window
from tests.test_internal_driver import (
    _LEVEL_WINDOW_DECLARATIONS,
    _config,
    _parsed,
    _payload,
    _provenance,
    _request,
    _rows,
    _windows,
)


def _provider_config() -> ProviderConfig:
    return _config(SourceCoordinates({"route": "level"}))


def test_source_call_origin_from_response_handles_present_and_empty_content_type() -> None:
    resp = TransportResponse(
        content=b"{}",
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_type="application/json",
        url="https://example.invalid/data",
        request_parameters={"station": "s1"},
        attempts=2,
    )
    origin = SourceCallOrigin.from_response(resp)
    assert origin.url == "https://example.invalid/data"
    assert dict(origin.request_parameters) == {"station": "s1"}
    assert origin.status_code == 200
    assert origin.retrieved_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert origin.content_type == "application/json"
    assert origin.attempts == 2

    empty_ct = TransportResponse(
        content=b"{}",
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_type="",
        url="https://example.invalid/data",
        request_parameters={},
    )
    assert isinstance(SourceCallOrigin.from_response(empty_ct).content_type, UnknownOriginFact)


def test_matching_context_reuses_interpretation_without_calling_parse_and_preserves_receipts() -> None:
    requested, fetched = _windows()
    request = _request(requested, ("station-1",))
    cfg = _provider_config()
    coordinates = cfg.products[ProductId("level")].coordinates
    rows = _rows("station-1", 12, 10.0)
    attempts = (
        TransportAttempt(
            "attempt-1",
            "https://example.invalid/obs",
            {"station": "station-1"},
            datetime(2026, 1, 1, 12, tzinfo=UTC),
            status_code=200,
            content_type="application/json",
        ),
    )

    class _Provider:
        config = cfg
        window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def __init__(self, reuse: bool) -> None:
            self.reuse = reuse
            self.parse_calls = 0

        def fetch(self, stations, products, rendered_windows, window, config, transport, *, scope, known_series):
            payload = replace(
                _payload("station-1", coordinates, fetched),
                acquisition_id="fixed-acq-1",
                scope=scope,
                known_series=known_series,
                attempt_traces=attempts,
                content=b'{"raw": 1}',
                prerequisite_acquisition_ids=(),
            )
            if not self.reuse:
                return SourceAcquisition(value=(payload,))
            parsed = _parsed(rows, payload, config)
            return SourceAcquisition(
                value=(payload,),
                interpretations=(InterpretedPayload.from_payload(payload, parsed),),
            )

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            self.parse_calls += 1
            return _parsed(rows, payload, config)

    baseline_provider = _Provider(reuse=False)
    reused_provider = _Provider(reuse=True)
    provenance = _provenance(request)

    baseline = driver_module.drive(request, baseline_provider, provenance=provenance, receipts=ReceiptMode.INCLUDE)
    reused = driver_module.drive(request, reused_provider, provenance=provenance, receipts=ReceiptMode.INCLUDE)

    assert baseline_provider.parse_calls == 1
    assert reused_provider.parse_calls == 0
    pl_testing.assert_frame_equal(reused.canonical_rows, baseline.canonical_rows)
    assert reused.source_series == baseline.source_series
    assert reused.inventories == baseline.inventories
    assert reused.outcomes == baseline.outcomes
    assert reused.issues == baseline.issues
    assert reused.provenance == baseline.provenance
    assert [(entry.content, entry.origin, entry.authorship) for entry in reused.receipts.entries] == [
        (entry.content, entry.origin, entry.authorship) for entry in baseline.receipts.entries
    ]
    assert reused.receipts.entries[0].content == b'{"raw": 1}'
    assert reused.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD


@pytest.mark.parametrize(
    "mutation",
    [
        "falsy_known_series",
        "scope",
        "station_products",
        "source_coordinates",
        "fetch_window",
        "acquisition_axis",
        "origin_retrieved_at",
        "attempt_traces",
    ],
)
def test_context_change_falls_back_to_provider_parse(mutation: str) -> None:
    requested, fetched = _windows()
    cfg = _provider_config()
    coordinates = cfg.products[ProductId("level")].coordinates
    known_def = SourceSeries(
        series_id="station-1:level",
        provider_id="throwaway",
        station_id="station-1",
        product_id="level",
        identity=SourceIdentity(
            namespace="catalogue-ns",
            published_id="station-1:level",
            description="Catalogue description",
            origin="catalogue",
            evidence=("catalogue",),
        ),
        facts=(
            PhysicalFacts(
                facts_id="station-1:level:facts",
                quantity=known("stage", "catalogue"),
                source_unit=known("cm", "catalogue"),
                normalized_unit="cm",
                frequency=known("PT15M", "catalogue"),
            ),
        ),
    )
    request = ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=("station-1",),
        products=(ProductId("level"),),
        window=requested,
        known_series=(known_def,) if mutation == "falsy_known_series" else (),
    )

    class _FallbackProvider:
        config = cfg
        window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def __init__(self) -> None:
            self.parse_calls = 0

        def fetch(self, stations, products, rendered_windows, window, config, transport, *, scope, known_series):
            base_payload = replace(
                _payload("station-1", coordinates, fetched),
                scope=scope,
                known_series=() if mutation == "falsy_known_series" else known_series,
            )
            stale_parsed = _parsed(_rows("station-1", 12, 99.0), base_payload, config)

            if mutation == "falsy_known_series":
                # Fetch recorded known_series=(), which driver replaces via `or pair_series`.
                handed_context = InterpretationContext.from_payload(base_payload)
            else:
                alt_payload = base_payload
                if mutation == "scope":
                    alt_payload = replace(
                        base_payload,
                        scope=SeriesScope(provider_ids=("throwaway",), station_ids=("other",)),
                    )
                elif mutation == "station_products":
                    alt_payload = replace(
                        base_payload,
                        station_products=(("station-1", ProductId("level")), ("station-1", ProductId("other"))),
                    )
                elif mutation == "source_coordinates":
                    alt_payload = replace(base_payload, source_coordinates=SourceCoordinates({"route": "stale"}))
                elif mutation == "fetch_window":
                    alt_payload = replace(
                        base_payload,
                        fetch_window=_make_fetch_window(
                            WindowEndpoint.from_datetime(datetime(2026, 1, 2)),
                            fetched.end,
                        ),
                    )
                elif mutation == "acquisition_axis":
                    alt_payload = replace(base_payload, acquisition_axis=TimeAxis.UTC)
                elif mutation == "origin_retrieved_at":
                    alt_payload = replace(
                        base_payload,
                        origin=replace(base_payload.origin, retrieved_at=datetime(2026, 1, 9, tzinfo=UTC)),
                    )
                elif mutation == "attempt_traces":
                    alt_payload = replace(
                        base_payload,
                        attempt_traces=(
                            TransportAttempt(
                                "different-attempt",
                                "https://example.invalid/obs",
                                {},
                                datetime(2026, 1, 1, tzinfo=UTC),
                                status_code=200,
                            ),
                        ),
                    )
                handed_context = InterpretationContext.from_payload(alt_payload)
            return SourceAcquisition(
                value=(base_payload,),
                interpretations=(InterpretedPayload(context=handed_context, parsed=stale_parsed),),
            )

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            self.parse_calls += 1
            parsed = _parsed(_rows("station-1", 12, 10.0), payload, config)
            if payload.known_series:
                # Reflect effective known_series in identity to prove fallback got updated payload.
                updated_series = tuple(
                    item.model_copy(update={"identity": payload.known_series[0].identity}) for item in parsed.series
                )
                return replace(parsed, series=updated_series)
            return parsed

    provider = _FallbackProvider()
    result = driver_module.drive(request, provider, provenance=_provenance(request))
    assert provider.parse_calls == 1
    assert result.canonical_rows["value"].to_list() == [0.1]
    if mutation == "falsy_known_series":
        assert result.source_series[0].identity.origin == "catalogue"


def test_reused_interpretation_still_enforces_fatal_validation_on_zero_row_invalid_series() -> None:
    requested, fetched = _windows()
    request = _request(requested, ("station-1",))
    cfg = _provider_config()
    coordinates = cfg.products[ProductId("level")].coordinates

    class _InvalidZeroRowProvider:
        config = cfg
        window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(self, stations, products, rendered_windows, window, config, transport, *, scope, known_series):
            payload = replace(_payload("station-1", coordinates, fetched), scope=scope, known_series=known_series)
            empty_parsed = _parsed(pl.DataFrame(schema=RowsSchema.polars_schema), payload, config)
            corrupt_series = empty_parsed.series[0].model_copy(update={"facts": ()})
            invalid_parsed = replace(empty_parsed, series=(corrupt_series,))
            return SourceAcquisition(
                value=(payload,),
                interpretations=(InterpretedPayload.from_payload(payload, invalid_parsed),),
            )

        def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
            raise AssertionError("Matching context should reuse and validate the handed-off ParsedSeries")

    with pytest.raises(FatalContractError, match="Native series requires valid admitted physical facts"):
        driver_module.drive(request, _InvalidZeroRowProvider(), provenance=_provenance(request))


def test_reused_interpretation_rejects_duplicate_outcome_ids_unknown_acquisitions_duplicates_and_bad_types() -> None:
    requested, fetched = _windows()
    request = _request(requested, ("station-1",))
    cfg = _provider_config()
    coordinates = cfg.products[ProductId("level")].coordinates
    payload = replace(
        _payload("station-1", coordinates, fetched),
        scope=SeriesScope(provider_ids=("throwaway",), station_ids=("station-1",), product_ids=("level",)),
    )
    valid_parsed = _parsed(_rows("station-1", 12, 10.0), payload, cfg)

    class _StaticProvider:
        config = cfg
        window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def __init__(self, acquisition: SourceAcquisition) -> None:
            self._acq = acquisition

        def fetch(self, *args, **kwargs):
            return self._acq

        def parse(self, payload, config):
            raise AssertionError("Should fail validation before or during reuse")

    dup_outcome = valid_parsed.outcomes[0]
    with pytest.raises(FatalContractError, match="duplicate outcome_id"):
        driver_module.drive(
            request,
            _StaticProvider(
                SourceAcquisition(
                    value=(payload,),
                    interpretations=(
                        InterpretedPayload.from_payload(
                            payload, replace(valid_parsed, outcomes=(dup_outcome, dup_outcome))
                        ),
                    ),
                )
            ),
            provenance=_provenance(request),
        )

    other_payload = replace(payload, acquisition_id="unknown-acq-id")
    with pytest.raises(FatalContractError, match="unknown acquisition"):
        driver_module.drive(
            request,
            _StaticProvider(
                SourceAcquisition(
                    value=(payload,),
                    interpretations=(InterpretedPayload.from_payload(other_payload, valid_parsed),),
                )
            ),
            provenance=_provenance(request),
        )

    dup_entry = InterpretedPayload.from_payload(payload, valid_parsed)
    with pytest.raises(FatalContractError, match="Duplicate payload interpretation"):
        driver_module.drive(
            request,
            _StaticProvider(
                SourceAcquisition(
                    value=(payload,),
                    interpretations=(dup_entry, dup_entry),
                )
            ),
            provenance=_provenance(request),
        )

    with pytest.raises(FatalContractError, match="InterpretedPayload"):
        driver_module.drive(
            request,
            _StaticProvider(
                SourceAcquisition(
                    value=(payload,),
                    interpretations=("not-an-interpretation",),  # type: ignore[arg-type]
                )
            ),
            provenance=_provenance(request),
        )


def test_receipt_omit_releases_prior_payload_bytes_and_reused_parsed_rows() -> None:
    requested, fetched = _windows()
    request = _request(requested, ("station-1",))
    cfg = _provider_config()
    coordinates = cfg.products[ProductId("level")].coordinates

    retained_refs: list[weakref.ref[object]] = []

    class _TwoPageProvider:
        config = cfg
        window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(self, stations, products, rendered_windows, window, config, transport, *, scope, known_series):
            p1 = replace(
                _payload("station-1", coordinates, fetched),
                acquisition_id="page-1",
                content=b"page-1-" + (b"x" * 2048),
                scope=scope,
                known_series=known_series,
            )
            p2 = replace(
                _payload("station-1", coordinates, fetched),
                acquisition_id="page-2",
                content=b"page-2-" + (b"y" * 2048),
                scope=scope,
                known_series=known_series,
            )
            marker_rows_1 = _rows("station-1", 12, 10.0)
            marker_rows_2 = _rows("station-1", 13, 20.0)
            parsed_1 = _parsed(marker_rows_1, p1, config)
            parsed_2 = _parsed(marker_rows_2, p2, config)
            retained_refs.append(weakref.ref(parsed_1.rows))
            retained_refs.append(weakref.ref(parsed_2.rows))
            retained_refs.append(weakref.ref(parsed_1.outcomes[0]))
            retained_refs.append(weakref.ref(parsed_2.outcomes[0]))
            return SourceAcquisition(
                value=(p1, p2),
                interpretations=(
                    InterpretedPayload.from_payload(p1, parsed_1),
                    InterpretedPayload.from_payload(p2, parsed_2),
                ),
            )

        def parse(self, payload, config):
            raise AssertionError("Should reuse handed-off interpretations")

    result = driver_module.drive(
        request, _TwoPageProvider(), provenance=_provenance(request), receipts=ReceiptMode.OMIT
    )
    gc.collect()
    assert result.canonical_rows.height == 2
    assert all(ref() is None for ref in retained_refs)


def test_window_acquisition_forwards_interpretations_and_still_matches_when_prerequisites_prepended() -> None:
    cfg = _provider_config()
    coordinates = cfg.products[ProductId("level")].coordinates
    window = RenderedWindow(
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:04Z",
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 1, 0, 0, 3, 999999)),
        ),
    )
    requests = 0

    def acquire(child: RenderedWindow) -> WindowAcquisition:
        nonlocal requests
        requests += 1
        assert child.bounds is not None
        if requests == 1:
            origin = SourceCallOrigin(
                "https://example.invalid/overflow",
                {},
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                UnknownOriginFact(),
                UnknownOriginFact(),
                acquisition_id="parent-overflow",
            )
            failure = RetrievalOutcome(
                outcome_id="overflow",
                series_id=None,
                station_id="station-1",
                product_id="level",
                window=SeriesWindow(
                    start=datetime.fromisoformat(child.bounds.start.isoformat()),
                    end=datetime.fromisoformat(child.bounds.end.isoformat()),
                ),
                status=OutcomeStatus.FAILED,
                reason="overflow",
                calls=("parent-overflow",),
            )
            return WindowAcquisition(
                SourceAcquisition((), calls=(origin,), outcomes=(failure,)),
                WindowResponseMeaning.OVERFLOW,
                ("overflow",),
            )
        payload = replace(
            _payload("station-1", coordinates, child.bounds),
            acquisition_id=f"child-{requests}",
        )
        parsed = _parsed(pl.DataFrame(schema=RowsSchema.polars_schema), payload, cfg)
        return WindowAcquisition(
            SourceAcquisition(value=(payload,), interpretations=(InterpretedPayload.from_payload(payload, parsed),))
        )

    acquired = acquire_window(window, precision=timedelta(seconds=1), acquire=acquire)
    assert len(acquired.value) == 2
    assert len(acquired.interpretations) == 2
    for payload, interp in zip(acquired.value, acquired.interpretations, strict=True):
        assert payload.prerequisite_acquisition_ids == ("parent-overflow",)
        assert interp.context == InterpretationContext.from_payload(payload)


def test_shared_acquisition_reuses_per_product_contexts_and_releases_after_final_consumer() -> None:
    from rivretrieve._internal.engine import (
        Daily,
        DailyLabelTime,
        DayDefinition,
        ProductConfig,
        ProductWindowDeclarations,
        StopConvention,
        Unit,
        WindowDeclaration,
        WindowGranularity,
        WindowRenderingVocabulary,
        ZoneValue,
    )
    from rivretrieve._internal.source_series import ClippingAxis

    products = (ProductId("flow"), ProductId("level"))
    coords = SourceCoordinates({"route": "shared"})
    shared_cfg = ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId("flow"): ProductConfig(
                coords, Unit.M3_S, Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))
            ),
            ProductId("level"): ProductConfig(coords, Unit.M, Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))),
        },
    )
    decl = WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)
    shared_decls = ProductWindowDeclarations(dict.fromkeys(products, decl))
    requested = engine_req_window = (
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
    )
    from rivretrieve._internal.engine import RequestedWindow

    req = ObservationRequest(ProviderId("throwaway"), ("station-1",), products, RequestedWindow(*engine_req_window))
    fw = _make_fetch_window(*requested)
    retained_refs: list[weakref.ref[object]] = []
    parse_calls = 0

    class _SharedTransport:
        def send(self, request):
            return TransportResponse(
                content=b"shared-json-" + b"z" * 2048,
                status_code=200,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                content_type="application/json",
                url="https://example.invalid/shared",
                request_parameters={},
            )

    def _interpret_shared_group(payload, pair_payloads, cfg):
        series_win = SeriesWindow(
            start=datetime.fromisoformat(fw.start.isoformat()),
            end=datetime.fromisoformat(fw.end.isoformat()),
        )
        out: dict[tuple[str, ProductId], ParsedSeries] = {}
        for prod, unit_str, qty, val in (
            (ProductId("flow"), "m3/s", "discharge", 15.0),
            (ProductId("level"), "m", "stage", 2.5),
        ):
            facts = PhysicalFacts(
                facts_id=f"{prod}:facts",
                quantity=known(qty, "test"),
                source_unit=known(unit_str, "test"),
                normalized_unit=unit_str,
                frequency=known("P1D", "test"),
                clipping_axis=ClippingAxis.CALENDAR_DATE,
                label_time="00:00",
            )
            sid = f"station-1:{prod}"
            definition = SourceSeries(
                series_id=sid,
                provider_id="throwaway",
                station_id="station-1",
                product_id=str(prod),
                identity=SourceIdentity(namespace="test", published_id=sid, origin="response", evidence=("test",)),
                facts=(facts,),
            )
            rows = pl.DataFrame(
                {
                    "station_id": ["station-1"],
                    "product_id": [str(prod)],
                    "time": [datetime(2025, 1, 1, 0, 0)],
                    "value": [val],
                    "time_zone": ["unknown"],
                    "series_id": [sid],
                    "facts_id": [facts.facts_id],
                    "source_unit": [unit_str],
                },
                schema=RowsSchema.polars_schema,
            )
            outcome = RetrievalOutcome(
                outcome_id=f"{prod}:outcome",
                series_id=sid,
                station_id="station-1",
                product_id=str(prod),
                window=series_win,
                status=OutcomeStatus.SUCCESS,
                facts_ids=(facts.facts_id,),
                calls=(payload.acquisition_id,),
            )
            parsed = ParsedSeries(rows, (definition,), (), (outcome,), ())
            retained_refs.append(weakref.ref(parsed.rows))
            retained_refs.append(weakref.ref(parsed.outcomes[0]))
            out[("station-1", prod)] = parsed
        return out

    class _SharedPlanner:
        def plan_lookups(self, needs, cfg):
            return ()

        def plan_observations(self, needs, lookups, cfg):
            return ObservationPlan(
                requests=(
                    PlannedObservationRequest(
                        consumers=needs,
                        request=TransportRequest(HttpMethod.GET, "https://example.invalid/shared"),
                        source_coordinates=coords,
                        fetch_window=fw,
                        interpret_group=_interpret_shared_group,
                    ),
                )
            )

    class _SharedProvider:
        request_planner = _SharedPlanner()
        config = shared_cfg
        window_declarations = shared_decls

        def parse(self, payload, cfg):
            nonlocal parse_calls
            parse_calls += 1
            raise AssertionError("Shared contexts should both be reused")

    result = driver_module.drive(
        req,
        _SharedProvider(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_SharedTransport(),
    )
    gc.collect()
    assert parse_calls == 0
    assert result.canonical_rows.height == 2
    assert set(result.canonical_rows["product_id"].to_list()) == {"flow", "level"}
    assert all(ref() is None for ref in retained_refs)
