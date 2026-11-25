from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.assembly import _AssemblyResult
from rivretrieve._internal.assembly import assemble as real_assemble
from rivretrieve._internal.conversion import convert as real_convert
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    Daily,
    DailyLabelTime,
    DayDefinition,
    FetchWindow,
    Instant,
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
    UnknownOriginReason,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    WithIssues,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.observations import (
    ObservationProvenance,
    ReceiptAuthorship,
    ReceiptEntry,
    ReceiptMode,
    Receipts,
)
from rivretrieve._internal.primitives import IssueSeverity, ProductId, ProviderId
from rivretrieve._internal.source_series import (
    ClippingAxis,
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
)


def _parsed(rows: Rows, payload: Payload, config: ProviderConfig, issues: tuple[Issue, ...] = ()) -> ParsedSeries:
    """A response-owned concrete definition and outcome for each test payload coordinate."""
    definitions = []
    outcomes = []
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    for station, product_id in payload.station_products:
        product = config.products[product_id]
        key = f"{station}:{product_id}"
        daily = isinstance(product.semantics, Daily)
        fact = PhysicalFacts(
            facts_id=f"{key}:facts",
            quantity=known("stage", "test source definition"),
            source_unit=known(product.unit.value, "test source definition"),
            normalized_unit=product.unit.value,
            frequency=known("P1D" if daily else "PT15M", "test source definition"),
            clipping_axis=ClippingAxis.CALENDAR_DATE if daily else ClippingAxis.SOURCE_TIMESTAMP,
            label_time=product.semantics.label_time.value if daily else None,
        )
        definitions.append(
            SourceSeries(
                series_id=key,
                provider_id="throwaway",
                station_id=station,
                product_id=str(product_id),
                identity=SourceIdentity(
                    namespace="test-source", published_id=key, origin="response", evidence=("test payload",)
                ),
                facts=(fact,),
            )
        )
        outcomes.append(
            RetrievalOutcome(
                outcome_id=f"{key}:outcome",
                series_id=key,
                station_id=station,
                product_id=str(product_id),
                window=window,
                status=OutcomeStatus.EMPTY if rows.is_empty() else OutcomeStatus.SUCCESS,
                facts_ids=(fact.facts_id,),
            )
        )
    scope = payload.scope or SeriesScope(provider_ids=("throwaway",))
    inventory = InventorySnapshot(
        snapshot_id="inventory:" + ":".join(item.series_id for item in definitions),
        scope=scope,
        members=tuple(item.series_id for item in definitions),
        completeness=InventoryCompleteness.COMPLETE,
        access="test source",
        origin="response",
        window=window,
        evidence=("test response inventory",),
    )
    return ParsedSeries(rows, tuple(definitions), (inventory,), tuple(outcomes), issues)


_STATIONS = (
    "station-1",
    "station-2",
    "station-3",
    "station-4",
    "station-5",
)
_PRODUCTS = (ProductId("level"),)
_LEVEL_WINDOW_DECLARATIONS = ProductWindowDeclarations(
    {
        ProductId("level"): WindowDeclaration(
            WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE
        )
    }
)


class _ThrowawayProvider:
    def __init__(
        self,
        config: ProviderConfig,
        payloads: tuple[Payload, ...],
        rows_by_station: dict[str, Rows],
        parse_issues_by_station: dict[str, tuple[Issue, ...]],
        fetch_issues: tuple[Issue, ...],
        events: list[str],
    ) -> None:
        self.config = config
        self.window_declarations = _LEVEL_WINDOW_DECLARATIONS
        self._payloads = payloads
        self._rows_by_station = rows_by_station
        self._parse_issues_by_station = parse_issues_by_station
        self._fetch_issues = fetch_issues
        self._events = events

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        window: FetchWindow,
        config: ProviderConfig,
        transport: object,
        *,
        scope: SeriesScope,
        known_series: tuple[SourceSeries, ...],
    ) -> WithIssues[tuple[Payload, ...]]:
        self._events.append("fetch")
        assert len(stations) == len(products) == 1
        assert products == _PRODUCTS
        assert rendered_windows == {ProductId("level"): (RenderedWindow(window.start.date, window.end.date),)}
        assert all(payload.fetch_window == window for payload in self._payloads)
        assert isinstance(window, FetchWindow)
        assert not isinstance(window, RequestedWindow)
        assert config is self.config
        matching = tuple(payload for payload in self._payloads if payload.station_products[0][0] == stations[0])
        issues = self._fetch_issues if stations[0] == _STATIONS[0] else ()
        if matching:
            return WithIssues(value=matching, issues=issues)
        return SourceAcquisition(
            value=(),
            issues=issues,
            outcomes=(
                RetrievalOutcome(
                    outcome_id=f"{stations[0]}:failed",
                    series_id=None,
                    station_id=stations[0],
                    product_id=str(products[0]),
                    window=SeriesWindow(
                        start=datetime.fromisoformat(window.start.isoformat()),
                        end=datetime.fromisoformat(window.end.isoformat()),
                    ),
                    status=OutcomeStatus.FAILED,
                    reason="Test source reported station not found",
                ),
            ),
        )

    def parse(
        self,
        payload: Payload,
        config: ProviderConfig,
    ) -> ParsedSeries:
        station_id = payload.station_products[0][0]
        self._events.append(f"parse:{station_id}")
        expected_payload = next(
            candidate for candidate in self._payloads if candidate.station_products == payload.station_products
        )
        assert payload.content is expected_payload.content
        assert payload.fetch_window is expected_payload.fetch_window
        assert payload.station_products == expected_payload.station_products
        assert payload.content is expected_payload.content
        assert payload.origin is expected_payload.origin
        assert config is self.config
        return _parsed(self._rows_by_station[station_id], payload, config, self._parse_issues_by_station[station_id])


def _issue(
    code: str,
    *,
    severity: IssueSeverity = "warning",
    station_id: str = "",
) -> Issue:
    return Issue(
        severity=severity,
        code=code,
        message=f"{code} occurred for {station_id}",
        details={"code": code, "station_id": station_id},
        provider_id=ProviderId("throwaway"),
    )


def _request(window: RequestedWindow, stations: tuple[str, ...] = _STATIONS) -> ObservationRequest:
    return ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=stations,
        products=_PRODUCTS,
        window=window,
    )


def _config(coordinates: SourceCoordinates) -> ProviderConfig:
    return ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("level"): ProductConfig(
                coordinates=coordinates,
                unit=Unit.CM,
                semantics=Instant(),
            )
        },
    )


@pytest.mark.parametrize("provider_id", ["throwaway", "lt_lhmt"])
@pytest.mark.parametrize("equal_renderings", [False, True])
def test_drive_plans_each_requested_product_and_passes_immutable_keyed_renderings(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    equal_renderings: bool,
) -> None:
    products = (ProductId("date_product"), ProductId("year_product"))
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 2, 23, 59, 59, 999999)),
    )
    request = ObservationRequest(ProviderId(provider_id), ("station-1",), products, requested)
    product_config = ProductConfig(SourceCoordinates({"field": "value"}), Unit.M, Instant())
    config = ProviderConfig(ZoneValue("+00:00"), dict.fromkeys(products, product_config))
    declarations = ProductWindowDeclarations(
        {
            products[0]: WindowDeclaration(
                WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE
            ),
            products[1]: WindowDeclaration(
                WindowGranularity("date" if equal_renderings else "year"),
                WindowRenderingVocabulary.DATE if equal_renderings else WindowRenderingVocabulary.YEAR,
                StopConvention.INCLUSIVE,
            ),
        }
    )
    shared = provider_id == "lt_lhmt" and equal_renderings
    received: list[tuple[Mapping[ProductId, tuple[RenderedWindow, ...]], FetchWindow]] = []
    planned_with: list[FetchWindow] = []
    real_plan_windows = driver_module.plan_windows

    def recording_plan_windows(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
        planned_with.append(fetch_window)
        return real_plan_windows(fetch_window, declaration)

    monkeypatch.setattr(driver_module, "plan_windows", recording_plan_windows)

    class _CapturingProvider:
        window_declarations = declarations
        shared_acquisition_products = (frozenset(products),) if provider_id == "lt_lhmt" else ()

        def __init__(self) -> None:
            self.config = config

        def fetch(
            self,
            stations: tuple[str, ...],
            supplied_products: tuple[ProductId, ...],
            rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
            fetch_window: FetchWindow,
            supplied_config: ProviderConfig,
            transport: object,
            *,
            scope: SeriesScope,
            known_series: tuple[SourceSeries, ...],
        ) -> WithIssues[tuple[Payload, ...]]:
            assert stations == ("station-1",)
            assert len(supplied_products) == (2 if shared else 1)
            assert set(supplied_products).issubset(products)
            assert supplied_config is config
            received.append((rendered_windows, fetch_window))
            return WithIssues(())

        def parse(self, payload: Payload, supplied_config: ProviderConfig) -> ParsedSeries:
            raise AssertionError("parse must not run")

    result = driver_module.drive(
        request, _CapturingProvider(), provenance=_provenance(request), receipts=ReceiptMode.OMIT
    )

    assert result.canonical_rows.is_empty()
    assert len(received) == (1 if shared else 2)
    assert [tuple(rendered) for rendered, _ in received] == ([products] if shared else [(products[0],), (products[1],)])
    rendered_by_product = {product: rendered[product] for rendered, _ in received for product in rendered}
    assert rendered_by_product == {
        ProductId("date_product"): (RenderedWindow("2025-12-30", "2026-01-04"),),
        ProductId("year_product"): (
            (RenderedWindow("2025-12-30", "2026-01-04"),)
            if equal_renderings
            else (RenderedWindow("2025", None), RenderedWindow("2026", None))
        ),
    }
    rendered_windows, fetch_window = received[0]
    with pytest.raises(TypeError):
        rendered_windows[ProductId("date_product")] = ()  # type: ignore[index]
    assert fetch_window == _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 12, 30)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 4, 23, 59, 59, 999999)),
    )
    assert len(planned_with) == 2
    assert all(planned_window == fetch_window for planned_window in planned_with)


def test_drive_rejects_missing_product_window_declaration_before_fetch() -> None:
    events: list[str] = []
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 2)),
    )
    request = ObservationRequest(ProviderId("throwaway"), ("station-1",), (ProductId("missing"),), requested)
    config = ProviderConfig(
        ZoneValue("+00:00"),
        {ProductId("missing"): ProductConfig(SourceCoordinates({}), Unit.M, Instant())},
    )

    class _MissingDeclarationProvider:
        window_declarations = ProductWindowDeclarations({})

        def __init__(self) -> None:
            self.config = config

        def fetch(
            self, *args: object, scope: SeriesScope, known_series: tuple[SourceSeries, ...]
        ) -> WithIssues[tuple[Payload, ...]]:
            events.append("fetch")
            return WithIssues(())

        def parse(self, payload: Payload, supplied_config: ProviderConfig) -> ParsedSeries:
            raise AssertionError("parse must not run")

    with pytest.raises(FatalContractError) as caught:
        driver_module.drive(
            request, _MissingDeclarationProvider(), provenance=_provenance(request), receipts=ReceiptMode.OMIT
        )

    assert str(caught.value) == ("Missing window declaration for missing")
    assert caught.value.issues == ()
    assert events == []


def _payload(
    station_id: str,
    coordinates: SourceCoordinates,
    fetch_window: FetchWindow,
) -> Payload:
    return Payload(
        source_coordinates=coordinates,
        station_products=((station_id, ProductId("level")),),
        fetch_window=fetch_window,
        content=(f'{{"station_id":"{station_id}"}}').encode(),
        origin=_origin(),
        prerequisite_calls=(),
    )


@pytest.mark.parametrize("acquisition_axis", ["native", "utc"])
def test_drive_enforces_payload_interval_ownership_without_deduplicating_rows(acquisition_axis):
    from dataclasses import replace

    from rivretrieve._internal.time_axis import TimeAxis

    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    request = _request(_windows()[0], ("station-1",))
    axis = TimeAxis(acquisition_axis)
    # UTC ownership must compare instants, not the source's +02:00 labels.
    offset = 2 if axis is TimeAxis.UTC else 0
    zone = "+02:00" if offset else "+00:00"
    boundary = datetime(2026, 1, 2, 12 - offset)
    windows = (
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2026, 1, 2)),
            WindowEndpoint.from_datetime(boundary - timedelta(microseconds=1)),
        ),
        _make_fetch_window(
            WindowEndpoint.from_datetime(boundary),
            WindowEndpoint.from_datetime(datetime(2026, 1, 2, 23)),
        ),
    )
    payloads = tuple(
        replace(
            _payload("station-1", coordinates, window),
            content=f"original response {index}".encode(),
            acquisition_axis=axis,
        )
        for index, window in enumerate(windows)
    )
    snapshots = (
        pl.concat(
            [_rows("station-1", 11, 100.0, time_zone=zone)] * 2 + [_rows("station-1", 12, 999.0, time_zone=zone)]
        ),
        pl.concat([_rows("station-1", 11, 888.0, time_zone=zone), _rows("station-1", 12, 200.0, time_zone=zone)]),
    )

    class PartitionedProvider:
        window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def __init__(self):
            self.config = config

        def fetch(self, *args, **kwargs):
            return WithIssues(payloads)

        def parse(self, payload, supplied_config):
            index = next(i for i, original in enumerate(payloads) if original.content == payload.content)
            assert payload.content is payloads[index].content
            return _parsed(snapshots[index], payload, supplied_config)

    result = driver_module.drive(
        request,
        PartitionedProvider(),
        provenance=_provenance(request),
        receipts=ReceiptMode.INCLUDE,
    )
    expected = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 11), datetime(2026, 1, 2, 11), datetime(2026, 1, 2, 12)],
            "value": [1.0, 1.0, 2.0],
        }
    )
    pl_testing.assert_frame_equal(result.canonical_rows.select("time", "value"), expected)
    assert tuple(entry.content for entry in result.receipts.entries) == tuple(payload.content for payload in payloads)


def _origin() -> SourceCallOrigin:
    unknown = UnknownOriginFact()
    return SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown)


def _rows(
    station_id: str,
    hour: int,
    value: float,
    *,
    time_zone: str = "+00:00",
) -> Rows:
    return pl.DataFrame(
        {
            "station_id": [station_id],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, hour)],
            "value": [value],
            "time_zone": [time_zone],
            "series_id": [f"{station}:{product}" for station, product in zip([station_id], ["level"], strict=True)],
            "facts_id": [
                f"{station}:{product}:facts" for station, product in zip([station_id], ["level"], strict=True)
            ],
            "source_unit": ["cm"] * len([station_id]),
        },
        schema=RowsSchema.polars_schema,
    )


def _provenance(request: ObservationRequest) -> ObservationProvenance:
    return ObservationProvenance(
        source="test",
        provider_id=request.provider_id,
        request={
            "stations": list(_STATIONS),
            "products": ["level"],
        },
    )


def _windows() -> tuple[RequestedWindow, FetchWindow]:
    requested = RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 0)),
        end=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 23)),
    )
    fetched = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 12, 31, 0)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 4, 23)),
    )
    return requested, fetched


@pytest.mark.parametrize("invalid_receipts", [False, True, "include", None])
def test_drive_rejects_invalid_receipts_modes_before_provider_work(invalid_receipts: object) -> None:
    request = _request(_windows()[0])

    with pytest.raises(TypeError, match="^receipts must be ReceiptMode$"):
        driver_module.drive(
            request,
            cast("driver_module.ProviderStages", object()),
            provenance=_provenance(request),
            receipts=cast("ReceiptMode", invalid_receipts),
        )


def test_drive_default_omit_never_constructs_receipt_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_window, fetch_window = _windows()
    request = _request(requested_window, ("station-1",))
    coordinates = SourceCoordinates({"parameter": "height"})
    payload = _payload("station-1", coordinates, fetch_window)
    provider = _ThrowawayProvider(
        _config(coordinates),
        (payload,),
        {"station-1": _rows("station-1", 12, 250.0)},
        {"station-1": ()},
        (),
        [],
    )

    def forbidden_receipt_entry(*args: object, **kwargs: object) -> ReceiptEntry:
        raise AssertionError("ReceiptEntry must not be constructed under OMIT")

    monkeypatch.setattr(driver_module, "ReceiptEntry", forbidden_receipt_entry)

    result = driver_module.drive(request, provider, provenance=_provenance(request))

    assert result.receipts == Receipts(provider_id=request.provider_id, entries=())


@pytest.mark.parametrize(
    ("case", "requested_start", "requested_end", "expected_start", "expected_end"),
    [
        (
            "month-seam",
            datetime(2026, 3, 1, 1, 2, 3, 456789),
            datetime(2026, 3, 30, 21, 22, 23, 654321),
            "2026-02-27T01:02:03.456789",
            "2026-04-01T21:22:23.654321",
        ),
        (
            "year-seam",
            datetime(2025, 12, 31, 12, 34, 56, 123456),
            datetime(2026, 1, 1, 23, 59, 59, 999999),
            "2025-12-29T12:34:56.123456",
            "2026-01-03T23:59:59.999999",
        ),
    ],
)
def test_drive_widens_fetch_window_by_exactly_two_calendar_days_across_month_and_year_seams(
    case: str,
    requested_start: datetime,
    requested_end: datetime,
    expected_start: str,
    expected_end: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(requested_start),
        WindowEndpoint.from_datetime(requested_end),
    )
    request = _request(requested, ("station-1",))
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    received: list[FetchWindow] = []

    class _CapturingProvider:
        def __init__(self) -> None:
            self.config = config
            self.window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(
            self,
            stations: tuple[str, ...],
            products: tuple[ProductId, ...],
            rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
            window: FetchWindow,
            supplied_config: ProviderConfig,
            transport: object,
            *,
            scope: SeriesScope,
            known_series: tuple[SourceSeries, ...],
        ) -> WithIssues[tuple[Payload, ...]]:
            assert stations == ("station-1",)
            assert products == _PRODUCTS
            assert supplied_config is config
            received.append(window)
            return WithIssues(value=())

        def parse(self, payload: Payload, supplied_config: ProviderConfig) -> ParsedSeries:
            raise AssertionError("parse must not run without payloads")

    def recording_convert(
        rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
        *,
        series: tuple[SourceSeries, ...],
    ) -> WithIssues[CanonicalRows]:
        assert supplied_config is config
        assert window is requested
        return real_convert(rows, supplied_config, window, series=series)

    monkeypatch.setattr(driver_module, "convert", recording_convert)
    driver_module.drive(
        request,
        _CapturingProvider(),
        provenance=_provenance(request),
        receipts=ReceiptMode.OMIT,
    )

    assert case in {"month-seam", "year-seam"}
    assert len(received) == 1
    fetched = received[0]
    assert isinstance(fetched, FetchWindow)
    assert not isinstance(fetched, RequestedWindow)
    assert fetched.start.isoformat() == expected_start
    assert fetched.end.isoformat() == expected_end
    fetch_start = datetime(
        fetched.start.year,
        fetched.start.month,
        fetched.start.day,
        fetched.start.hour,
        fetched.start.minute,
        fetched.start.second,
        fetched.start.microsecond,
    )
    fetch_end = datetime(
        fetched.end.year,
        fetched.end.month,
        fetched.end.day,
        fetched.end.hour,
        fetched.end.minute,
        fetched.end.second,
        fetched.end.microsecond,
    )
    assert requested_start - fetch_start == timedelta(days=2)
    assert fetch_end - requested_end == timedelta(days=2)


def test_drive_accumulates_every_stage_issue_in_encounter_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    requested_window, fetch_window = _windows()
    request = _request(requested_window, ("station-1", "station-2"))
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    payloads = (
        _payload("station-1", coordinates, fetch_window),
        _payload("station-2", coordinates, fetch_window),
    )
    fetch_issues = (
        _issue("fetch.first", severity="info"),
        _issue("fetch.second", severity="error"),
    )
    parse_issues = {
        "station-1": (
            _issue("parse.station-1.first", severity="error"),
            _issue("parse.station-1.second", severity="info"),
        ),
        "station-2": (_issue("parse.station-2", severity="warning"),),
    }
    rows_by_station = {
        "station-1": _rows("station-1", 12, 250.0),
        "station-2": _rows("station-2", 13, 300.0, time_zone="unknown"),
    }
    provider = _ThrowawayProvider(
        config,
        payloads,
        rows_by_station,
        parse_issues,
        fetch_issues,
        events,
    )
    provenance = _provenance(request)

    def recording_convert(
        supplied_rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
        *,
        series: tuple[SourceSeries, ...],
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        expected_rows = pl.concat(
            [
                rows_by_station["station-1"],
                rows_by_station["station-2"],
            ]
        )
        pl_testing.assert_frame_equal(supplied_rows, expected_rows)
        assert supplied_config is config
        assert window is requested_window
        assert window is not fetch_window
        return real_convert(supplied_rows, supplied_config, window, series=series)

    def recording_assemble(
        canonical_rows: CanonicalRows,
        supplied_provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        supplied_receipts: Receipts,
        **metadata,
    ) -> _AssemblyResult:
        events.append("assemble")
        assert supplied_provenance.model_copy(update={"calls_made": ()}) == provenance
        assert len(supplied_provenance.calls_made) == len(payloads)
        assert tuple(issue.code for issue in issues) == (
            "fetch.first",
            "fetch.second",
            "parse.station-1.first",
            "parse.station-1.second",
            "parse.station-2",
        )
        assert supplied_receipts.provider_id == request.provider_id
        assert len(supplied_receipts.entries) == 2
        for entry, payload in zip(supplied_receipts.entries, payloads, strict=True):
            assert entry.content is payload.content
            assert entry.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
            assert entry.origin is payload.origin
        return real_assemble(canonical_rows, supplied_provenance, issues, supplied_receipts, **metadata)

    monkeypatch.setattr(driver_module, "convert", recording_convert)
    monkeypatch.setattr(driver_module, "assemble", recording_assemble)

    result = driver_module.drive(
        request,
        provider,
        provenance=provenance,
        receipts=ReceiptMode.INCLUDE,
    )

    expected = pl.DataFrame(
        {
            "time": [
                datetime(2026, 1, 2, 12),
                datetime(2026, 1, 2, 13),
            ],
            "time_zone": ["+00:00", "unknown"],
            "station_id": ["station-1", "station-2"],
            "product_id": ["level", "level"],
            "value": [2.5, 3.0],
            "series_id": ["station-1:level", "station-2:level"],
            "facts_id": ["station-1:level:facts", "station-2:level:facts"],
            "source_unit": ["cm", "cm"],
            "quantity": ["stage", "stage"],
            "unit": ["m", "m"],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.provenance.model_copy(update={"calls_made": ()}) == provenance
    assert len(result.provenance.calls_made) == len(payloads)
    assert tuple(issue.code for issue in result.issues) == (
        "fetch.first",
        "fetch.second",
        "parse.station-1.first",
        "parse.station-1.second",
        "parse.station-2",
    )
    assert result.receipts.provider_id == request.provider_id
    assert len(result.receipts.entries) == 2
    for entry, payload in zip(result.receipts.entries, payloads, strict=True):
        assert entry.content is payload.content
        assert entry.origin is payload.origin
    assert events == [
        "fetch",
        "parse:station-1",
        "fetch",
        "parse:station-2",
        "convert",
        "assemble",
    ]


def test_drive_clips_unknown_zone_instants_at_both_closed_edges_without_warning() -> None:
    events: list[str] = []
    requested_window = RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 12)),
        end=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 13)),
    )
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 12, 31, 12)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 4, 13)),
    )
    request = _request(requested_window)
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    timestamps = (
        datetime(2026, 1, 2, 11, 59, 59, 999999),
        datetime(2026, 1, 2, 12),
        datetime(2026, 1, 2, 12, 30),
        datetime(2026, 1, 2, 13),
        datetime(2026, 1, 2, 13, 0, 0, 1),
    )
    payloads = tuple(_payload(station_id, coordinates, fetch_window) for station_id in _STATIONS)
    rows_by_station = {
        station_id: pl.DataFrame(
            {
                "station_id": [station_id],
                "product_id": ["level"],
                "time": [timestamp],
                "value": [value],
                "time_zone": ["unknown"],
                "series_id": [f"{station}:{product}" for station, product in zip([station_id], ["level"], strict=True)],
                "facts_id": [
                    f"{station}:{product}:facts" for station, product in zip([station_id], ["level"], strict=True)
                ],
                "source_unit": ["cm"] * len([station_id]),
            },
            schema=RowsSchema.polars_schema,
        )
        for station_id, timestamp, value in zip(
            _STATIONS,
            timestamps,
            (100.0, 200.0, 300.0, 400.0, 500.0),
            strict=True,
        )
    }
    provider = _ThrowawayProvider(
        config,
        payloads,
        rows_by_station,
        dict.fromkeys(_STATIONS, ()),
        (),
        events,
    )

    result = driver_module.drive(
        request,
        provider,
        provenance=_provenance(request),
        receipts=ReceiptMode.OMIT,
    )

    expected = pl.DataFrame(
        {
            "time": [
                datetime(2026, 1, 2, 12),
                datetime(2026, 1, 2, 12, 30),
                datetime(2026, 1, 2, 13),
            ],
            "time_zone": ["unknown", "unknown", "unknown"],
            "station_id": ["station-2", "station-3", "station-4"],
            "product_id": ["level", "level", "level"],
            "value": [2.0, 3.0, 4.0],
            "series_id": ["station-2:level", "station-3:level", "station-4:level"],
            "facts_id": ["station-2:level:facts", "station-3:level:facts", "station-4:level:facts"],
            "source_unit": ["cm", "cm", "cm"],
            "quantity": ["stage", "stage", "stage"],
            "unit": ["m", "m", "m"],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.issues == ()


def test_drive_returns_four_stations_and_one_issue_when_one_of_five_fails() -> None:
    events: list[str] = []
    requested_window, fetch_window = _windows()
    request = _request(requested_window)
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    successful_stations = (
        "station-1",
        "station-2",
        "station-4",
        "station-5",
    )
    payloads = tuple(_payload(station_id, coordinates, fetch_window) for station_id in successful_stations)
    rows_by_station = {
        "station-1": _rows("station-1", 11, 100.0),
        "station-2": _rows("station-2", 12, 200.0),
        "station-4": _rows("station-4", 14, 400.0),
        "station-5": _rows("station-5", 15, 500.0),
    }
    provider = _ThrowawayProvider(
        config,
        payloads,
        rows_by_station,
        dict.fromkeys(successful_stations, ()),
        (_issue("fetch.station-3-not-found", severity="error"),),
        events,
    )
    provenance = _provenance(request)

    result = driver_module.drive(
        request,
        provider,
        provenance=provenance,
        receipts=ReceiptMode.OMIT,
    )

    expected = pl.DataFrame(
        {
            "time": [
                datetime(2026, 1, 2, 11),
                datetime(2026, 1, 2, 12),
                datetime(2026, 1, 2, 14),
                datetime(2026, 1, 2, 15),
            ],
            "time_zone": ["+00:00", "+00:00", "+00:00", "+00:00"],
            "station_id": [
                "station-1",
                "station-2",
                "station-4",
                "station-5",
            ],
            "product_id": ["level", "level", "level", "level"],
            "value": [1.0, 2.0, 4.0, 5.0],
            "series_id": ["station-1:level", "station-2:level", "station-4:level", "station-5:level"],
            "facts_id": [
                "station-1:level:facts",
                "station-2:level:facts",
                "station-4:level:facts",
                "station-5:level:facts",
            ],
            "source_unit": ["cm", "cm", "cm", "cm"],
            "quantity": ["stage", "stage", "stage", "stage"],
            "unit": ["m", "m", "m", "m"],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert tuple(issue.code for issue in result.issues) == ("fetch.station-3-not-found",)
    failed = tuple(item for item in result.outcomes if item.status is OutcomeStatus.FAILED)
    assert len(failed) == 1
    assert failed[0].station_id == "station-3"
    assert failed[0].reason == "Test source reported station not found"
    assert sum(item.status is OutcomeStatus.SUCCESS for item in result.outcomes) == 4
    assert result.provenance.model_copy(update={"calls_made": ()}) == provenance
    assert len(result.provenance.calls_made) == len(payloads)
    assert result.receipts == Receipts(provider_id=request.provider_id, entries=())
    assert events == [
        "fetch",
        "parse:station-1",
        "fetch",
        "parse:station-2",
        "fetch",
        "fetch",
        "parse:station-4",
        "fetch",
        "parse:station-5",
    ]


def test_drive_all_source_failure_reaches_convert_and_assemble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    requested_window, _ = _windows()
    request = _request(requested_window)
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    fetch_issues = tuple(
        _issue("fetch.station_not_found", severity=severity, station_id=station_id)
        for station_id, severity in zip(
            _STATIONS,
            ("info", "warning", "error", "info", "error"),
            strict=True,
        )
    )
    provider = _ThrowawayProvider(
        config,
        (),
        {},
        {},
        fetch_issues,
        events,
    )
    provenance = _provenance(request)

    def recording_convert(
        supplied_rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
        *,
        series: tuple[SourceSeries, ...],
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        expected_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
        pl_testing.assert_frame_equal(supplied_rows, expected_rows)
        assert supplied_config is config
        assert window is requested_window
        return real_convert(supplied_rows, supplied_config, window, series=series)

    def recording_assemble(
        canonical_rows: CanonicalRows,
        supplied_provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        supplied_receipts: Receipts,
        **metadata,
    ) -> _AssemblyResult:
        events.append("assemble")
        expected_canonical = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
        pl_testing.assert_frame_equal(canonical_rows, expected_canonical)
        assert supplied_provenance is provenance
        assert issues == fetch_issues
        assert supplied_receipts == Receipts(provider_id=request.provider_id, entries=())
        return real_assemble(canonical_rows, supplied_provenance, issues, supplied_receipts, **metadata)

    monkeypatch.setattr(driver_module, "convert", recording_convert)
    monkeypatch.setattr(driver_module, "assemble", recording_assemble)

    result = driver_module.drive(
        request,
        provider,
        provenance=provenance,
        receipts=ReceiptMode.OMIT,
    )

    expected = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.issues == fetch_issues
    assert result.provenance is provenance
    assert result.receipts == Receipts(provider_id=request.provider_id, entries=())
    assert events == ["fetch"] * 5 + ["convert", "assemble"]
    assert {name for name in dir(provider) if not name.startswith("_")} == {
        "config",
        "fetch",
        "parse",
        "window_declarations",
    }


class _BoundaryProvider:
    def __init__(
        self,
        config: ProviderConfig,
        payloads: tuple[Payload, ...],
        rows_by_payload: tuple[Rows, ...],
        events: list[str],
    ) -> None:
        self.config = config
        self.window_declarations = _LEVEL_WINDOW_DECLARATIONS
        self._payloads = payloads
        self._rows_by_payload = rows_by_payload
        self._events = events

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        window: FetchWindow,
        config: ProviderConfig,
        transport: object,
        *,
        scope: SeriesScope,
        known_series: tuple[SourceSeries, ...],
    ) -> WithIssues[tuple[Payload, ...]]:
        self._events.append("fetch")
        assert len(stations) == len(products) == 1
        assert products == (ProductId("level"),)
        assert window == self._payloads[0].fetch_window
        assert config is self.config
        return WithIssues(
            value=tuple(payload for payload in self._payloads if payload.station_products[0][0] == stations[0])
        )

    def parse(
        self,
        payload: Payload,
        config: ProviderConfig,
    ) -> ParsedSeries:
        index = next(index for index, candidate in enumerate(self._payloads) if candidate.content is payload.content)
        self._events.append(f"parse-{index + 1}")
        assert config is self.config
        return _parsed(self._rows_by_payload[index], payload, config, ())


def _drive_boundary_rows(
    rows_by_payload: tuple[Rows, ...],
    events: list[str],
) -> _AssemblyResult:
    requested_window = RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 0)),
        end=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 23)),
    )
    request = ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=tuple(f"station-{index}" for index in range(1, len(rows_by_payload) + 1)),
        products=(ProductId("level"),),
        window=requested_window,
    )
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 12, 31, 0)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 4, 23)),
    )
    coordinates = SourceCoordinates({"parameter": "height"})
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("level"): ProductConfig(
                coordinates=coordinates,
                unit=Unit.CM,
                semantics=Instant(),
            )
        },
    )
    payloads = tuple(
        Payload(
            source_coordinates=coordinates,
            station_products=((station_id, ProductId("level")),),
            fetch_window=fetch_window,
            content=(f'{{"payload_index":{index}}}').encode(),
            origin=_origin(),
            prerequisite_calls=(),
        )
        for index, station_id in enumerate(request.stations, start=1)
    )
    provider = _BoundaryProvider(config, payloads, rows_by_payload, events)
    provenance = ObservationProvenance(
        source="test",
        provider_id=request.provider_id,
        request={"stations": list(request.stations), "products": ["level"]},
    )
    return driver_module.drive(
        request,
        provider,
        provenance=provenance,
        receipts=ReceiptMode.OMIT,
    )


def test_drive_rejects_each_malformed_parse_result_before_later_parse_or_convert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    malformed_rows = pl.DataFrame(
        {
            "station_id": ["station-1"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 12)],
            "value": [250.0],
        },
        schema={
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "time": pl.Datetime(),
            "value": pl.Float64,
        },
    )
    later_rows = pl.DataFrame(
        {
            "station_id": ["station-2"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 13)],
            "value": [300.0],
            "time_zone": ["+00:00"],
            "series_id": ["station-2:level"],
            "facts_id": ["station-2:level:facts"],
            "source_unit": ["cm"],
        },
        schema=RowsSchema.polars_schema,
    )

    def forbidden_convert(
        rows: Rows,
        config: ProviderConfig,
        window: RequestedWindow,
        *,
        series: tuple[SourceSeries, ...],
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        raise AssertionError("convert must not run after a malformed parse result")

    monkeypatch.setattr(driver_module, "convert", forbidden_convert)

    with pytest.raises(FatalContractError, match="Rows is missing required columns: time_zone"):
        _drive_boundary_rows((malformed_rows, later_rows), events)

    assert events == ["fetch", "parse-1"]


def test_drive_rejects_malformed_second_parse_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    first_rows = pl.DataFrame(
        {
            "station_id": ["station-1"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 12)],
            "value": [250.0],
            "time_zone": ["+00:00"],
            "series_id": ["station-1:level"],
            "facts_id": ["station-1:level:facts"],
            "source_unit": ["cm"],
        },
        schema=RowsSchema.polars_schema,
    )
    malformed_rows = pl.DataFrame(
        {
            "station_id": ["station-2"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 13)],
            "value": [300.0],
        },
        schema={
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "time": pl.Datetime(),
            "value": pl.Float64,
        },
    )

    def forbidden_convert(
        rows: Rows,
        config: ProviderConfig,
        window: RequestedWindow,
        *,
        series: tuple[SourceSeries, ...],
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        raise AssertionError("convert must not run after a malformed parse result")

    monkeypatch.setattr(driver_module, "convert", forbidden_convert)

    with pytest.raises(FatalContractError, match="Rows is missing required columns: time_zone"):
        _drive_boundary_rows((first_rows, malformed_rows), events)

    assert events == ["fetch", "parse-1", "fetch", "parse-2"]


def test_drive_rejects_malformed_canonical_rows_before_assemble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    parsed_rows = pl.DataFrame(
        {
            "station_id": ["station-1"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 12)],
            "value": [250.0],
            "time_zone": ["+00:00"],
            "series_id": ["station-1:level"],
            "facts_id": ["station-1:level:facts"],
            "source_unit": ["cm"],
        },
        schema=RowsSchema.polars_schema,
    )
    malformed_canonical_rows = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 12)],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "value": [2.5],
        },
        schema={
            "time": pl.Datetime(),
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "value": pl.Float64,
        },
    )

    def malformed_convert(
        rows: Rows,
        config: ProviderConfig,
        window: RequestedWindow,
        *,
        series: tuple[SourceSeries, ...],
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        return WithIssues(value=malformed_canonical_rows)

    def forbidden_assemble(
        canonical_rows: CanonicalRows,
        provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        receipts: Receipts,
        **metadata,
    ) -> _AssemblyResult:
        events.append("assemble")
        raise AssertionError("assemble must not run after malformed canonical rows")

    monkeypatch.setattr(driver_module, "convert", malformed_convert)
    monkeypatch.setattr(driver_module, "assemble", forbidden_assemble)

    with pytest.raises(FatalContractError, match="CanonicalRows is missing required columns: time_zone"):
        _drive_boundary_rows((parsed_rows,), events)

    assert events == ["fetch", "parse-1", "convert"]


def test_drive_accepts_well_formed_empty_rows_at_both_boundaries() -> None:
    events: list[str] = []
    empty_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
    result = _drive_boundary_rows((empty_rows,), events)

    expected = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.issues == ()
    assert events == ["fetch", "parse-1"]


def test_drive_rejects_engine_created_fetch_window_that_does_not_contain_request_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2026, 1, 2, 0)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 2, 23)),
    )
    request = _request(requested)
    config = _config(SourceCoordinates({"parameter": "height"}))

    class _ForbiddenProvider:
        def __init__(self) -> None:
            self.config = config
            self.window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(
            self,
            stations: tuple[str, ...],
            products: tuple[ProductId, ...],
            rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
            window: FetchWindow,
            supplied_config: ProviderConfig,
            transport: object,
            *,
            scope: SeriesScope,
            known_series: tuple[SourceSeries, ...],
        ) -> WithIssues[tuple[Payload, ...]]:
            events.append("fetch")
            raise AssertionError("fetch must not run for a narrowed engine window")

        def parse(self, payload: Payload, supplied_config: ProviderConfig) -> ParsedSeries:
            events.append("parse")
            raise AssertionError("parse must not run for a narrowed engine window")

    def forbidden_convert(
        rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
        *,
        series: tuple[SourceSeries, ...],
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        raise AssertionError("convert must not run for a narrowed engine window")

    def forbidden_assemble(
        canonical_rows: CanonicalRows,
        provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        receipts: Receipts,
        **metadata,
    ) -> _AssemblyResult:
        events.append("assemble")
        raise AssertionError("assemble must not run for a narrowed engine window")

    monkeypatch.setattr(driver_module, "_FETCH_WINDOW_PADDING", timedelta(microseconds=-1))
    monkeypatch.setattr(driver_module, "convert", forbidden_convert)
    monkeypatch.setattr(driver_module, "assemble", forbidden_assemble)

    with pytest.raises(FatalContractError) as exc_info:
        driver_module.drive(
            request,
            _ForbiddenProvider(),
            provenance=_provenance(request),
            receipts=ReceiptMode.OMIT,
        )

    assert exc_info.value.issues == ()
    assert str(exc_info.value) == (
        "Engine-created FetchWindow does not contain RequestedWindow: "
        "fetch_start=2026-01-02T00:00:00.000001, fetch_end=2026-01-02T22:59:59.999999, "
        "requested_start=2026-01-02T00:00:00, requested_end=2026-01-02T23:00:00. This is an "
        "internal engine contract breach before provider fetch; please report it with these four endpoints."
    )
    assert events == []


@pytest.mark.parametrize(
    ("semantics", "requested_start", "requested_end", "row_time", "expected_message"),
    [
        (
            Instant(),
            datetime(2026, 1, 2, 0),
            datetime(2026, 1, 2, 23),
            datetime(2026, 1, 2, 23, 0, 0, 1),
            "CanonicalRows contain observations outside the RequestedWindow physical axis",
        ),
        (
            Daily(DayDefinition("00:00"), DailyLabelTime("00:00")),
            datetime(2026, 1, 2, 12),
            datetime(2026, 1, 2, 18),
            datetime(2026, 1, 3, 0),
            "CanonicalRows contain observations outside the RequestedWindow physical axis",
        ),
    ],
)
def test_drive_rejects_post_convert_row_outside_fact_defined_axis_before_assembly(
    semantics: Instant | Daily,
    requested_start: datetime,
    requested_end: datetime,
    row_time: datetime,
    expected_message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(requested_start),
        WindowEndpoint.from_datetime(requested_end),
    )
    request = _request(requested, ("station-1",))
    coordinates = SourceCoordinates({"parameter": "height"})
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("level"): ProductConfig(
                coordinates=coordinates,
                unit=Unit.CM,
                semantics=semantics,
            )
        },
    )

    class _EmptyProvider:
        def __init__(self) -> None:
            self.config = config
            self.window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(
            self,
            stations: tuple[str, ...],
            products: tuple[ProductId, ...],
            rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
            window: FetchWindow,
            supplied_config: ProviderConfig,
            transport: object,
            *,
            scope: SeriesScope,
            known_series: tuple[SourceSeries, ...],
        ) -> WithIssues[tuple[Payload, ...]]:
            events.append("fetch")
            return WithIssues(value=(_payload("station-1", coordinates, window),))

        def parse(self, payload: Payload, supplied_config: ProviderConfig) -> ParsedSeries:
            events.append("parse")
            return _parsed(pl.DataFrame(schema=RowsSchema.polars_schema), payload, supplied_config)

    def faulty_convert(
        rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
        *,
        series: tuple[SourceSeries, ...],
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        return WithIssues(
            value=pl.DataFrame(
                {
                    "time": [row_time],
                    "time_zone": ["+00:00"],
                    "station_id": ["station-1"],
                    "product_id": ["level"],
                    "value": [2.5],
                    "series_id": ["station-1:level"],
                    "facts_id": ["station-1:level:facts"],
                    "source_unit": ["cm"],
                    "quantity": ["stage"],
                    "unit": ["m"],
                },
                schema=CanonicalRowsSchema.polars_schema,
            )
        )

    def forbidden_assemble(
        canonical_rows: CanonicalRows,
        provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        receipts: Receipts,
        **metadata,
    ) -> _AssemblyResult:
        events.append("assemble")
        raise AssertionError("assemble must not run after a converter row leak")

    monkeypatch.setattr(driver_module, "convert", faulty_convert)
    monkeypatch.setattr(driver_module, "assemble", forbidden_assemble)

    with pytest.raises(FatalContractError) as exc_info:
        driver_module.drive(
            request,
            _EmptyProvider(),
            provenance=_provenance(request),
            receipts=ReceiptMode.OMIT,
        )

    assert exc_info.value.issues == ()
    assert str(exc_info.value) == expected_message
    assert events == ["fetch", "parse", "convert"]


def test_drive_daily_product_accepts_midday_start_and_returns_that_dates_row() -> None:
    events: list[str] = []
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2026, 1, 2, 12)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 2, 18)),
    )
    request = _request(requested, ("station-1",))
    coordinates = SourceCoordinates({"parameter": "height"})
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("level"): ProductConfig(
                coordinates=coordinates,
                unit=Unit.CM,
                semantics=Daily(DayDefinition("00:00"), DailyLabelTime("00:00")),
            )
        },
    )

    class _DailyProvider:
        def __init__(self) -> None:
            self.config = config
            self.window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(
            self,
            stations: tuple[str, ...],
            products: tuple[ProductId, ...],
            rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
            window: FetchWindow,
            supplied_config: ProviderConfig,
            transport: object,
            *,
            scope: SeriesScope,
            known_series: tuple[SourceSeries, ...],
        ) -> WithIssues[tuple[Payload, ...]]:
            events.append("fetch")
            return WithIssues(value=(_payload("station-1", coordinates, window),))

        def parse(self, payload: Payload, supplied_config: ProviderConfig) -> ParsedSeries:
            events.append("parse:station-1")
            return _parsed(_rows("station-1", 0, 250.0), payload, supplied_config, ())

    result = driver_module.drive(
        request,
        _DailyProvider(),
        provenance=_provenance(request),
        receipts=ReceiptMode.OMIT,
    )

    expected = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 0)],
            "time_zone": ["+00:00"],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "value": [2.5],
            "series_id": ["station-1:level"],
            "facts_id": ["station-1:level:facts"],
            "source_unit": ["cm"],
            "quantity": ["stage"],
            "unit": ["m"],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.issues == ()
    assert events == ["fetch", "parse:station-1"]


def test_payload_origins_enrich_provenance_as_json_safe_ordered_facts() -> None:
    from dataclasses import replace
    from datetime import UTC

    from rivretrieve._internal.engine import SourceQuery

    requested_window, fetch_window = _windows()
    request = _request(requested_window, ("station-1", "station-2"))
    coordinates = SourceCoordinates({"parameter": "height"})
    first = replace(
        _payload("station-1", coordinates, fetch_window),
        origin=SourceCallOrigin(
            "https://same.test/data",
            {
                "none": None,
                "text": "x",
                "integer": 1,
                "float": 1.5,
                "bytes": b"\xff",
            },
            200,
            datetime(2026, 1, 2, 1, tzinfo=UTC),
            "text/csv",
            "/one",
            SourceQuery("first", (None, "x", 1, 1.5, b"\xff")),
        ),
    )
    second = replace(
        _payload("station-2", coordinates, fetch_window),
        origin=SourceCallOrigin(
            "https://same.test/data",
            UnknownOriginFact(UnknownOriginReason.UNAVAILABLE),
            UnknownOriginFact(UnknownOriginReason.UNAVAILABLE),
            datetime(2026, 1, 2, 2, tzinfo=UTC),
            UnknownOriginFact(UnknownOriginReason.UNAVAILABLE),
            UnknownOriginFact(UnknownOriginReason.UNAVAILABLE),
            SourceQuery("second", ("2",)),
        ),
    )
    unknown = _payload("station-3", coordinates, fetch_window)
    base = _provenance(request)

    # Equal source bytes/origins from an independent acquisition retain a distinct call.
    repeated = replace(first, acquisition_id="independent-repeat")
    enriched = driver_module._provenance_with_payload_origins(base, (first, repeated, second, unknown))

    assert enriched.source == base.source
    assert enriched.request == base.request
    assert enriched.endpoints == ("https://same.test/data",)
    assert enriched.retrieved_at == datetime(2026, 1, 2, 2, tzinfo=UTC)
    assert len(enriched.calls_made) == 4
    assert enriched.calls_made[0]["call_id"] != enriched.calls_made[1]["call_id"]
    assert {key: value for key, value in enriched.calls_made[0].items() if key != "call_id"} == {
        key: value for key, value in enriched.calls_made[1].items() if key != "call_id"
    }
    assert tuple(call["url"] for call in enriched.calls_made[:3]) == (
        "https://same.test/data",
        "https://same.test/data",
        "https://same.test/data",
    )
    assert set(enriched.calls_made[3]) == {
        "call_id",
        "prerequisite_acquisition_ids",
        "url",
        "request_parameters",
        "status_code",
        "retrieved_at",
        "content_type",
        "source_path",
        "query",
        "station_products",
    }
    assert enriched.calls_made[3]["station_products"] == (("station-3", "level"),)
    assert enriched.calls_made[3]["prerequisite_acquisition_ids"] == ()
    assert all(
        value == {"status": "unknown", "reason": "unknown"}
        for key, value in enriched.calls_made[3].items()
        if key not in ("station_products", "call_id", "prerequisite_acquisition_ids")
    )
    assert enriched.calls_made[2]["request_parameters"] == {
        "status": "unknown",
        "reason": "unavailable",
    }
    assert enriched.query == {
        "calls": (
            {
                "statement": "first",
                "parameters": (
                    None,
                    "x",
                    1,
                    1.5,
                    {"encoding": "base64", "value": "/w=="},
                ),
            },
            {"statement": "second", "parameters": ("2",)},
        )
    }
    dumped = enriched.model_dump_json()
    assert '"retrieved_at":"2026-01-02T02:00:00Z"' in dumped
    assert '"encoding":"base64","value":"/w=="' in dumped
    assert "authorization" not in dumped.lower()
    assert "header" not in dumped.lower()


def test_payload_origin_enrichment_rejects_prepopulated_call_derived_provenance() -> None:
    requested_window, fetch_window = _windows()
    request = _request(requested_window)
    payload = _payload("station-1", SourceCoordinates({"parameter": "height"}), fetch_window)
    populated = _provenance(request).model_copy(update={"calls_made": ({"url": "already"},)})
    with pytest.raises(FatalContractError, match="requires empty call-derived base provenance"):
        driver_module._provenance_with_payload_origins(populated, (payload,))


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), float("-inf")])
def test_source_call_parameters_reject_boolean_and_non_finite_float(value: object) -> None:
    from rivretrieve._internal.engine import SourceQuery

    with pytest.raises(TypeError, match="unsupported value"):
        SourceQuery("query", (value,))  # ty: ignore[invalid-argument-type]
    unknown = UnknownOriginFact()
    with pytest.raises(TypeError, match="unsupported value"):
        SourceCallOrigin(
            unknown,
            {"invalid": value},  # ty: ignore[invalid-argument-type]
            unknown,
            unknown,
            unknown,
            unknown,
            unknown,
        )


def test_prerequisite_calls_are_interleaved_before_each_actual_payload_origin() -> None:
    from dataclasses import replace
    from datetime import UTC

    from rivretrieve._internal.transport import HttpMethod, RequestBodyShape, SecretCallTrace

    requested_window, fetch_window = _windows()
    request = _request(requested_window)
    coordinates = SourceCoordinates({"parameter": "height"})

    def auth(minute: int) -> SecretCallTrace:
        return SecretCallTrace(
            HttpMethod.GET,
            "https://auth.test/token",
            {"User-Agent": "RivRetrieve"},
            None,
            RequestBodyShape.NONE,
            ("Identificador", "Senha"),
            200,
            datetime(2026, 1, 2, 0, minute, tzinfo=UTC),
            "application/json",
        )

    def data(station: str, minute: int, traces=()):
        return replace(
            _payload(station, coordinates, fetch_window),
            station_products=((station, ProductId("level")), (station, ProductId("flow"))),
            origin=SourceCallOrigin(
                f"https://data.test/{station}",
                {},
                200,
                datetime(2026, 1, 2, 0, minute, tzinfo=UTC),
                "application/json",
                UnknownOriginFact(),
                UnknownOriginFact(),
            ),
            prerequisite_calls=traces,
        )

    payloads = (data("A", 1, (auth(0),)), data("B", 2), data("C", 4, (auth(3),)))
    enriched = driver_module._provenance_with_payload_origins(_provenance(request), payloads)
    assert tuple(call["url"] for call in enriched.calls_made) == (
        "https://auth.test/token",
        "https://data.test/A",
        "https://data.test/B",
        "https://auth.test/token",
        "https://data.test/C",
    )
    assert enriched.endpoints == (
        "https://auth.test/token",
        "https://data.test/A",
        "https://data.test/B",
        "https://data.test/C",
    )
    assert enriched.retrieved_at == datetime(2026, 1, 2, 0, 4, tzinfo=UTC)
    assert enriched.calls_made[0]["response_disposition"] == "secret_response_withheld"
    assert set(enriched.calls_made[0]) == {
        "method",
        "url",
        "request_parameters",
        "request_body_shape",
        "credential_header_names",
        "status_code",
        "retrieved_at",
        "content_type",
        "response_disposition",
        "station_products",
        "acquisition_id",
    }
    assert enriched.calls_made[0]["station_products"] == (("A", "level"), ("A", "flow"))
    assert enriched.calls_made[0]["acquisition_id"] == payloads[0].acquisition_id
    assert enriched.calls_made[3]["acquisition_id"] == payloads[2].acquisition_id
    assert enriched.calls_made[0]["credential_header_names"] == ("Identificador", "Senha")


@pytest.mark.parametrize(
    "update",
    [
        {"calls_made": ({"url": "already"},)},
        {"endpoints": ("https://already.test",)},
        {"retrieved_at": datetime(2026, 1, 1)},
        {"query": {"statement": "already"}},
    ],
)
def test_payload_origin_enrichment_refuses_each_ambiguous_base_field_even_without_payloads(update) -> None:
    requested_window, _ = _windows()
    with pytest.raises(FatalContractError, match="requires empty call-derived base provenance"):
        driver_module._provenance_with_payload_origins(
            _provenance(_request(requested_window)).model_copy(update=update), ()
        )


@pytest.mark.derived("tests/test_data/ca_eccc_02GA010_2020_01_derived_input.zip")
@pytest.mark.parametrize("restriction", ["selected", "no-match"])
def test_compiled_query_keeps_inventory_definitions_and_fact_filtered_receipts(
    tmp_path, restriction, retained_evidence_root: Path
) -> None:
    from io import BytesIO

    import rivretrieve as rr
    from rivretrieve._internal.observations import ObservationResult
    from rivretrieve._internal.providers.ca_eccc.config import config as hydat_config
    from rivretrieve._internal.source_series import PhysicalPredicate, RestrictionKind
    from rivretrieve._internal.store import StoreReader
    from tests.test_ca_eccc_boundary_probe import _compiled_derived_store

    store = _compiled_derived_store(tmp_path, retained_evidence_root / "tests/test_data")
    manifest = StoreReader().status(store, ProviderId("ca_eccc")).manifest
    assert manifest is not None
    level = next(item for item in manifest.series if item.product_id == "stage_daily_mean")
    scope = SeriesScope(
        provider_ids=("ca_eccc",),
        station_ids=("02GA010",),
        product_ids=("stage_daily_mean",),
        predicates=(PhysicalPredicate(field="quantity", value="stage"),),
        restriction=RestrictionKind.EXPLICIT,
        series_ids=(level.series_id if restriction == "selected" else "absent-local-series",),
    )
    request = ObservationRequest(
        ProviderId("ca_eccc"),
        ("02GA010",),
        (ProductId("stage_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2020, 1, 1, 23, 59, 59, 999999)),
        ),
        scope=scope,
    )
    assembled = driver_module.drive_store(
        request,
        hydat_config,
        store,
        provenance=ObservationProvenance(source="local HYDAT", provider_id=ProviderId("ca_eccc")),
        receipts=ReceiptMode.INCLUDE,
    )
    retained = {item.series_id for item in assembled.source_series}
    assert assembled.provenance.calls_made == manifest.source_calls == ()
    if restriction == "selected":
        entry = assembled.receipts.entries[0]
        assert entry.executed_query.facts_ids == tuple(fact.facts_id for fact in level.facts)
        physical = pl.read_parquet(BytesIO(entry.content))
        assert set(physical["facts_id"]) == {fact.facts_id for fact in level.facts}
        assert assembled.outcomes[0].status is OutcomeStatus.SUCCESS
    else:
        assert assembled.canonical_rows.is_empty()
        assert assembled.receipts.entries == ()
        assert assembled.outcomes[0].status is OutcomeStatus.NO_MATCH
    assert all(set(inventory.members).issubset(retained) for inventory in assembled.inventories)
    result = ObservationResult(
        data=assembled.canonical_rows,
        provenance=assembled.provenance,
        issues=assembled.issues,
        receipts=assembled.receipts,
        source_series=assembled.source_series,
        inventories=assembled.inventories,
        outcomes=assembled.outcomes,
        scope=scope,
    )
    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(restored.data, result.data)
    assert restored.source_series == result.source_series
    assert restored.inventories == result.inventories
    assert restored.outcomes == result.outcomes


@pytest.mark.parametrize("existing", [None, "payload", [], ["other"], ["payload", "payload"]])
def test_storage_issue_lineage_never_overwrites_conflicting_source_context(existing):
    from rivretrieve._internal.issues import Issue

    issue = Issue(
        severity="info",
        code="source_quality_code",
        message="Native code",
        details={
            "source_quality_code": "Q",
            "count": 7,
            "acquisition_ids": existing,
        },
    )
    with pytest.raises(FatalContractError, match="acquisition references contradict"):
        driver_module._issue_with_acquisition_references(issue, ("payload",))
    assert issue.details == {"source_quality_code": "Q", "count": 7, "acquisition_ids": existing}


def test_storage_issue_lineage_preserves_native_issue_and_original_count():
    from rivretrieve._internal.issues import Issue

    issue = Issue(
        severity="info",
        code="source_quality_code",
        message="Native code",
        details={
            "source_quality_code": "Q",
            "count": 7,
        },
    )
    stored = driver_module._issue_with_acquisition_references(issue, ("payload",))
    assert stored.details == {"source_quality_code": "Q", "count": 7, "acquisition_ids": ("payload",)}
    assert stored.code == issue.code and stored.message == issue.message
    assert issue.details == {"source_quality_code": "Q", "count": 7}
    assert driver_module._issue_with_acquisition_references(stored, ("payload",)) == stored


@pytest.mark.parametrize("details", [None, {}, {"count": 7, "native_label": "authored"}])
def test_public_issue_projection_preserves_exact_original_context(details):
    from rivretrieve._internal.issues import Issue

    original = Issue(severity="info", code="source.authored", message="Authored note", details=details)
    stored = driver_module._issue_with_acquisition_references(original, ("authored-acquisition",))
    assert stored.details["acquisition_ids"] == ("authored-acquisition",)
    assert driver_module._public_issues((original,)) == (original,)
    assert driver_module._public_issues((stored,)) == (original,)
    assert original.details == details
    assert driver_module._issue_with_acquisition_references(stored, ("authored-acquisition",)) == stored


def test_issue_context_marker_cannot_overwrite_publisher_context():
    from rivretrieve._internal.issues import Issue

    original = Issue(
        severity="info",
        code="source.authored",
        message="Authored note",
        details={"_source_details_state": "publisher vocabulary"},
    )
    with pytest.raises(FatalContractError, match="conflicts with storage-only context"):
        driver_module._issue_with_acquisition_references(original, ("authored-acquisition",))
    assert driver_module._public_issues((original,)) == (original,)


@pytest.mark.parametrize(
    ("fetch_padding", "expected_start", "expected_end", "expected_pairs"),
    [
        (
            None,
            datetime(2026, 10, 20),
            datetime(2026, 11, 22),
            (("2026-09-24", "2026-10-23"), ("2026-10-24", "2026-11-22")),
        ),
        (timedelta(0), datetime(2026, 10, 22), datetime(2026, 11, 20), (("2026-10-22", "2026-11-20"),)),
    ],
)
def test_driver_honors_declaration_fetch_padding_override(
    fetch_padding: timedelta | None,
    expected_start: datetime,
    expected_end: datetime,
    expected_pairs: tuple[tuple[str, str], ...],
) -> None:
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2026, 10, 22)),
        WindowEndpoint.from_datetime(datetime(2026, 11, 20)),
    )
    request = _request(requested, ("station-1",))
    seen_windows: list[tuple[FetchWindow, tuple[tuple[str, str | None], ...]]] = []
    product = ProductId("level")
    provider_config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            product: ProductConfig(
                coordinates=SourceCoordinates({"parameter": "height"}),
                unit=Unit.CM,
                semantics=Instant(),
            )
        },
    )
    declarations = ProductWindowDeclarations(
        {
            product: WindowDeclaration(
                WindowGranularity("fixed-backward-span"),
                WindowRenderingVocabulary.DATE,
                StopConvention.INCLUSIVE,
                size=30,
                fetch_padding=fetch_padding,
            )
        }
    )

    class _Provider:
        config = provider_config
        window_declarations = declarations

        def fetch(self, stations, products, windows, window, config, transport, **_kwargs):
            seen_windows.append((window, tuple((item.start, item.stop) for item in windows[product])))
            return WithIssues(())

        def parse(self, payload, config):
            raise AssertionError("parse should not run without payloads")

    driver_module.drive(
        request,
        _Provider(),
        provenance=_provenance(request),
        receipts=ReceiptMode.OMIT,
    )
    assert len(seen_windows) == 1
    actual_window, actual_pairs = seen_windows[0]
    assert actual_window.start == WindowEndpoint.from_datetime(expected_start)
    assert actual_window.end == WindowEndpoint.from_datetime(expected_end)
    assert actual_pairs == expected_pairs


def test_require_canonical_rows_within_requested_is_independent_and_deduped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rivretrieve._internal.conversion as conv_mod
    import rivretrieve._internal.source_series as ss_mod

    facts_cfs = PhysicalFacts(
        facts_id="facts-cfs",
        quantity=known("discharge", "test"),
        source_unit=known("ft3/s", "test"),
        normalized_unit="ft3/s",
        frequency=known("PT15M", "test"),
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    )
    facts_cms = PhysicalFacts(
        facts_id="facts-cms",
        quantity=known("discharge", "test"),
        source_unit=known("m3/s", "test"),
        normalized_unit="m3/s",
        frequency=known("P1D", "test"),
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_time="00:00",
    )
    series = SourceSeries(
        series_id="s-multi",
        provider_id="throwaway",
        station_id="station-1",
        product_id="level",
        identity=SourceIdentity(namespace="test", published_id="s-multi", origin="response", evidence=("test",)),
        facts=(facts_cfs, facts_cms),
    )
    window = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2026, 1, 1, 8, 0)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 1, 16, 0)),
    )

    n_each = 50
    rows = pl.DataFrame(
        {
            "time": [*([datetime(2026, 1, 1, 12, 0)] * n_each), *([datetime(2026, 1, 1, 0, 0)] * n_each)],
            "time_zone": ["+00:00"] * (2 * n_each),
            "station_id": ["station-1"] * (2 * n_each),
            "product_id": ["level"] * (2 * n_each),
            "series_id": ["s-multi"] * (2 * n_each),
            "facts_id": [*["facts-cfs"] * n_each, *["facts-cms"] * n_each],
            "quantity": ["discharge"] * (2 * n_each),
            "source_unit": [*["ft3/s"] * n_each, *["m3/s"] * n_each],
            "unit": ["m3/s"] * (2 * n_each),
            "value": [float(i) for i in range(2 * n_each)],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )

    counts = {"native_window": 0, "admission": 0}
    orig_nw = conv_mod.native_window
    orig_adm_conv = conv_mod.admission
    orig_adm_ss = ss_mod.admission

    def spy_nw(s, e, fact):
        counts["native_window"] += 1
        return orig_nw(s, e, fact)

    def spy_adm_conv(fact):
        counts["admission"] += 1
        return orig_adm_conv(fact)

    def spy_adm_ss(fact):
        counts["admission"] += 1
        return orig_adm_ss(fact)

    with monkeypatch.context() as mp:
        mp.setattr(conv_mod, "native_window", spy_nw)
        mp.setattr(conv_mod, "admission", spy_adm_conv)
        mp.setattr(ss_mod, "admission", spy_adm_ss)
        driver_module._require_canonical_rows_within_requested(rows, (series,), window)

    assert counts["native_window"] <= 2
    assert counts["admission"] <= 4

    # Independent boundary failures still raise even with zero rows or bad converted output
    empty = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
    with pytest.raises(FatalContractError, match="Native series requires valid admitted physical facts"):
        driver_module._require_canonical_rows_within_requested(
            empty, (series.model_copy(update={"facts": ()}),), window
        )
    with pytest.raises(FatalContractError, match="outside the RequestedWindow physical axis"):
        driver_module._require_canonical_rows_within_requested(
            rows.with_columns(pl.lit(datetime(2026, 1, 2, 12, 0)).alias("time")),
            (series,),
            window,
        )
    with pytest.raises(FatalContractError, match="contradicts its admitted physical facts"):
        driver_module._require_canonical_rows_within_requested(
            rows.with_columns(pl.lit("ft3/s").alias("unit")),
            (series,),
            window,
        )

    # Even if drive's convert stage returns out-of-window rows, _require_canonical_rows_within_requested catches it
    coords = SourceCoordinates({"parameter": "height"})
    config = _config(coords)
    request = _request(window, ("station-1",))
    fetch_window = _make_fetch_window(window.start, window.end)
    from datetime import UTC

    payload = Payload(
        source_coordinates=coords,
        station_products=(("station-1", ProductId("level")),),
        fetch_window=fetch_window,
        content=b"[]",
        origin=SourceCallOrigin(
            url="https://example.invalid/obs",
            request_parameters={},
            status_code=200,
            retrieved_at=datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
            content_type="application/json",
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
        prerequisite_calls=(),
    )

    class _Provider:
        def __init__(self) -> None:
            self.config = config
            self.window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(self, stations, products, rendered_windows, window_arg, config_arg, transport, **_kw):
            return WithIssues((payload,))

        def parse(self, received, config_arg):
            native = pl.DataFrame(
                {
                    "station_id": ["station-1"],
                    "product_id": ["level"],
                    "time": [datetime(2026, 1, 1, 12, 0)],
                    "value": [1.0],
                    "time_zone": ["+00:00"],
                    "series_id": ["s-multi"],
                    "facts_id": ["facts-cms"],
                    "source_unit": ["m3/s"],
                },
                schema=RowsSchema.polars_schema,
            )
            bad_series = SourceSeries(
                series_id="s-multi",
                provider_id="throwaway",
                station_id="station-1",
                product_id="level",
                identity=series.identity,
                facts=(facts_cms,),
            )
            return ParsedSeries(
                rows=native.with_columns(pl.lit(datetime(2026, 1, 1, 0, 0)).alias("time")),
                series=(bad_series,),
                inventories=(),
                outcomes=(
                    RetrievalOutcome(
                        outcome_id="o1",
                        series_id="s-multi",
                        station_id="station-1",
                        product_id="level",
                        window=SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2)),
                        status=OutcomeStatus.SUCCESS,
                        facts_ids=("facts-cms",),
                    ),
                ),
            )

    monkeypatch.setattr(
        driver_module,
        "convert",
        lambda *a, **kw: WithIssues(rows.tail(1).with_columns(pl.lit(datetime(2026, 1, 2, 12, 0)).alias("time"))),
    )
    with pytest.raises(FatalContractError, match="outside the RequestedWindow physical axis"):
        driver_module.drive(request, _Provider(), provenance=_provenance(request), receipts=ReceiptMode.OMIT)


def test_drive_releases_payload_bodies_after_consumers_and_preserves_provenance_and_receipts() -> None:
    import gc
    import sys
    from datetime import UTC

    from rivretrieve._internal.transport import HttpMethod, RequestBodyShape, SecretCallTrace, TransportAttempt

    requested = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 2, 23, 59, 59, 999999)),
    )
    products = (ProductId("flow"), ProductId("level"))
    coords = SourceCoordinates({"parameter": "shared"})
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("flow"): ProductConfig(coordinates=coords, unit=Unit.M3_S, semantics=Instant()),
            ProductId("level"): ProductConfig(coordinates=coords, unit=Unit.M, semantics=Instant()),
        },
    )
    declarations = ProductWindowDeclarations(
        {
            p: WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)
            for p in products
        }
    )
    fetch_window = _make_fetch_window(requested.start, requested.end)
    prereq = SecretCallTrace(
        method=HttpMethod.POST,
        url="https://example.invalid/token",
        ordinary_headers={},
        request_parameters=None,
        request_body_shape=RequestBodyShape.NONE,
        credential_header_names=("Authorization",),
        status_code=200,
        retrieved_at=datetime(2026, 1, 3, 9, 0, tzinfo=UTC),
        content_type="application/json",
    )
    attempt = TransportAttempt(
        attempt_id="attempt-1",
        url="https://example.invalid/page1",
        request_parameters={"page": "1"},
        retrieved_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
        status_code=200,
        content_type="application/json",
    )

    def _origin(page: str, retrieved: datetime) -> SourceCallOrigin:
        return SourceCallOrigin(
            url=f"https://example.invalid/{page}",
            request_parameters={"page": page},
            status_code=200,
            retrieved_at=retrieved,
            content_type="application/json",
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        )

    # Fresh heap-allocated bytes (distinct id, not interned)
    body1 = b"shared-page1-" + b"a" * 65536
    body2 = b"flow-only-page2-" + b"b" * 65536
    base1 = sys.getrefcount(body1)
    base2 = sys.getrefcount(body2)
    observed: list[tuple[str, bool, int]] = []

    class _SharedProvider:
        shared_acquisition_products = (frozenset(products),)

        def __init__(self) -> None:
            self.config = config
            self.window_declarations = declarations

        def fetch(self, stations, prod_arg, rendered_windows, window_arg, config_arg, transport, **_kw):
            p1 = Payload(
                source_coordinates=coords,
                station_products=(("station-1", ProductId("flow")), ("station-1", ProductId("level"))),
                fetch_window=fetch_window,
                content=body1,
                origin=_origin("1", datetime(2026, 1, 3, 9, 1, tzinfo=UTC)),
                prerequisite_calls=(prereq,),
                attempt_traces=(attempt,),
                acquisition_id="acq-page-1",
            )
            p2 = Payload(
                source_coordinates=coords,
                station_products=(("station-1", ProductId("flow")),),
                fetch_window=fetch_window,
                content=body2,
                origin=_origin("2", datetime(2026, 1, 3, 9, 2, tzinfo=UTC)),
                prerequisite_calls=(),
                acquisition_id="acq-page-2",
                prerequisite_acquisition_ids=("acq-page-1",),
            )
            return WithIssues((p1, p2))

        def parse(self, payload: Payload, config_arg: ProviderConfig) -> ParsedSeries:
            gc.collect()
            body1_held = any(isinstance(r, (Payload, ReceiptEntry)) for r in gc.get_referrers(body1))
            observed.append(
                (f"{payload.acquisition_id}:{payload.station_products[0][1]}", body1_held, sys.getrefcount(body1))
            )
            station, product = payload.station_products[0]
            ts = datetime(2026, 1, 1, 12, 0) if payload.acquisition_id == "acq-page-1" else datetime(2026, 1, 2, 12, 0)
            unit_str = config_arg.products[product].unit.value
            qty = "discharge" if product == ProductId("flow") else "stage"
            fact = PhysicalFacts(
                facts_id=f"{station}:{product}:facts",
                quantity=known(qty, "test"),
                source_unit=known(unit_str, "test"),
                normalized_unit=unit_str,
                frequency=known("PT15M", "test"),
            )
            s_def = SourceSeries(
                series_id=f"{station}:{product}",
                provider_id="lt_lhmt",
                station_id=station,
                product_id=str(product),
                identity=SourceIdentity(
                    namespace="test", published_id=f"{station}:{product}", origin="response", evidence=("test",)
                ),
                facts=(fact,),
            )
            row_df = pl.DataFrame(
                {
                    "station_id": [station],
                    "product_id": [str(product)],
                    "time": [ts],
                    "value": [1.5],
                    "time_zone": ["+00:00"],
                    "series_id": [s_def.series_id],
                    "facts_id": [fact.facts_id],
                    "source_unit": [unit_str],
                },
                schema=RowsSchema.polars_schema,
            )
            return ParsedSeries(
                rows=row_df,
                series=(s_def,),
                inventories=(),
                outcomes=(
                    RetrievalOutcome(
                        outcome_id=f"{payload.acquisition_id}:{product}",
                        series_id=s_def.series_id,
                        station_id=station,
                        product_id=str(product),
                        window=SeriesWindow(
                            start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
                            end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
                        ),
                        status=OutcomeStatus.SUCCESS,
                        facts_ids=(fact.facts_id,),
                    ),
                ),
            )

    request = ObservationRequest(ProviderId("lt_lhmt"), ("station-1",), products, requested)
    omitted = driver_module.drive(
        request,
        _SharedProvider(),
        provenance=ObservationProvenance(source="test", provider_id=ProviderId("lt_lhmt")),
        receipts=ReceiptMode.OMIT,
        cache="bypass",
    )
    gc.collect()
    # consumer 1 (flow on page1) sees page1 alive; page2 starts BEFORE level consumer finishes?
    # Note loop order is flow (page1, page2) -> level (page1), so consumer 2 runs for level!
    # Therefore body1 must remain alive through flow(page2) until level(page1) finishes,
    # and once drive returns (and zero consumers remain), body1 & body2 must have NO Payload/ReceiptEntry refs!
    assert sys.getrefcount(body1) == base1
    assert sys.getrefcount(body2) == base2
    assert not any(isinstance(r, (Payload, ReceiptEntry)) for r in gc.get_referrers(body1))
    assert not any(isinstance(r, (Payload, ReceiptEntry)) for r in gc.get_referrers(body2))
    assert omitted.receipts.entries == ()
    assert len(observed) == 3
    assert observed[0][:2] == ("acq-page-1:flow", True)
    assert observed[1][:2] == ("acq-page-2:flow", True)  # still alive for level consumer!
    assert observed[2][:2] == ("acq-page-1:level", True)

    # Now single-product multi-page check: consumer count == 1 for page1, so BEFORE page2 starts parse(), page1 MUST be released!
    single_req = ObservationRequest(ProviderId("throwaway"), ("station-1",), (ProductId("flow"),), requested)
    single_observed: list[tuple[str, bool, int]] = []

    class _SingleProvider:
        def __init__(self) -> None:
            self.config = ProviderConfig(
                zone=ZoneValue("+00:00"),
                products={ProductId("flow"): config.products[ProductId("flow")]},
            )
            self.window_declarations = ProductWindowDeclarations(
                {ProductId("flow"): declarations.products[ProductId("flow")]}
            )

        def fetch(self, stations, prod_arg, rendered_windows, window_arg, config_arg, transport, **_kw):
            return WithIssues(
                (
                    Payload(
                        source_coordinates=coords,
                        station_products=(("station-1", ProductId("flow")),),
                        fetch_window=fetch_window,
                        content=body1,
                        origin=_origin("1", datetime(2026, 1, 3, 9, 1, tzinfo=UTC)),
                        prerequisite_calls=(prereq,),
                        attempt_traces=(attempt,),
                        acquisition_id="acq-page-1",
                    ),
                    Payload(
                        source_coordinates=coords,
                        station_products=(("station-1", ProductId("flow")),),
                        fetch_window=fetch_window,
                        content=body2,
                        origin=_origin("2", datetime(2026, 1, 3, 9, 2, tzinfo=UTC)),
                        prerequisite_calls=(),
                        acquisition_id="acq-page-2",
                        prerequisite_acquisition_ids=("acq-page-1",),
                    ),
                )
            )

        def parse(self, payload: Payload, config_arg: ProviderConfig) -> ParsedSeries:
            gc.collect()
            body1_held = any(isinstance(r, (Payload, ReceiptEntry)) for r in gc.get_referrers(body1))
            single_observed.append((payload.acquisition_id, body1_held, sys.getrefcount(body1)))
            ts = datetime(2026, 1, 1, 12, 0) if payload.acquisition_id == "acq-page-1" else datetime(2026, 1, 2, 12, 0)
            fact = PhysicalFacts(
                facts_id="station-1:flow:facts",
                quantity=known("discharge", "test"),
                source_unit=known("m3/s", "test"),
                normalized_unit="m3/s",
                frequency=known("PT15M", "test"),
            )
            s_def = SourceSeries(
                series_id="station-1:flow",
                provider_id="throwaway",
                station_id="station-1",
                product_id="flow",
                identity=SourceIdentity(
                    namespace="test", published_id="station-1:flow", origin="response", evidence=("test",)
                ),
                facts=(fact,),
            )
            row_df = pl.DataFrame(
                {
                    "station_id": ["station-1"],
                    "product_id": ["flow"],
                    "time": [ts],
                    "value": [2.5],
                    "time_zone": ["+00:00"],
                    "series_id": [s_def.series_id],
                    "facts_id": [fact.facts_id],
                    "source_unit": ["m3/s"],
                },
                schema=RowsSchema.polars_schema,
            )
            return ParsedSeries(
                rows=row_df,
                series=(s_def,),
                inventories=(),
                outcomes=(
                    RetrievalOutcome(
                        outcome_id=f"{payload.acquisition_id}:flow",
                        series_id=s_def.series_id,
                        station_id="station-1",
                        product_id="flow",
                        window=SeriesWindow(
                            start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
                            end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
                        ),
                        status=OutcomeStatus.SUCCESS,
                        facts_ids=(fact.facts_id,),
                    ),
                ),
            )

    single_omitted = driver_module.drive(
        single_req,
        _SingleProvider(),
        provenance=ObservationProvenance(source="test", provider_id=ProviderId("throwaway")),
        receipts=ReceiptMode.OMIT,
        cache="bypass",
    )
    single_included = driver_module.drive(
        single_req,
        _SingleProvider(),
        provenance=ObservationProvenance(source="test", provider_id=ProviderId("throwaway")),
        receipts=ReceiptMode.INCLUDE,
        cache="bypass",
    )
    # In OMIT mode, page-1 bytes were released BEFORE page-2 parse began; INCLUDE retains exact bytes!
    assert single_observed[0][:2] == ("acq-page-1", True)
    assert single_observed[1][:2] == ("acq-page-2", False)
    assert single_observed[1][2] == base1
    assert single_observed[3][:2] == ("acq-page-2", True)
    # Provenance is identical across OMIT and INCLUDE, while INCLUDE keeps exact bytes
    assert single_omitted.provenance == single_included.provenance
    assert single_omitted.provenance.retrieved_at == datetime(2026, 1, 3, 9, 2, tzinfo=UTC)
    assert any(
        c.get("acquisition_id") == "acq-page-1" and c.get("call_id") == "attempt-1"
        for c in single_omitted.provenance.calls_made
    )
    assert any(
        c.get("url") == "https://example.invalid/token" and c.get("acquisition_id") == "acq-page-1"
        for c in single_omitted.provenance.calls_made
    )
    assert any(
        c.get("prerequisite_acquisition_ids") == ("acq-page-1",) and c.get("call_id") == "acq-page-2"
        for c in single_omitted.provenance.calls_made
    )
    assert [e.content for e in single_included.receipts.entries] == [body1, body2]
