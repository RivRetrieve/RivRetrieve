from __future__ import annotations

import json
import warnings
from collections.abc import Callable, Iterator, Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import UTC, datetime

import polars as pl
import polars.testing as pl_testing
import pytest
from pydantic import BaseModel

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact, load_packaged_catalogue_artifact
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    FetchWindow,
    Instant,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RenderedWindow,
    Rows,
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
from rivretrieve._internal.issues import (
    FatalContractError,
    InvalidObservationRequestError,
    Issue,
    IssuePolicyError,
    ObservationsUnavailableError,
)
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    ObservationResult,
    Receipts,
)
from rivretrieve._internal.primitives import OnIssue, ProductId, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo, ProviderInfoValidationError
from rivretrieve._internal.providers.ca_eccc.config import config as ca_eccc_config
from rivretrieve._internal.registry import ProviderRegistry, UnknownProviderError, _ProviderHandle, _registry
from rivretrieve._internal.results import CatalogProvenance
from tests._stubs import stub_provider
from tests.conftest import RegisteredStub


def _instance_values(value: object) -> Iterator[object]:
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _instance_values(getattr(value, name))
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from _instance_values(getattr(value, field.name))
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _instance_values(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _instance_values(item)
    elif isinstance(value, pl.DataFrame):
        for row in value.iter_rows():
            yield from _instance_values(row)
    else:
        yield value


def _assert_sentinel_unreachable(result: ObservationResult) -> None:
    assert not any(value == b"test payload" for value in _instance_values(result))


def _origin() -> SourceCallOrigin:
    unknown = UnknownOriginFact()
    return SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown)


class _EngineModule:
    observation_source = "test-engine"
    coordinates = SourceCoordinates({"field": "value"})
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("level"): ProductConfig(
                coordinates=coordinates,
                unit=Unit.M,
                semantics=Instant(),
            )
        },
    )
    window_declarations = ProductWindowDeclarations(
        {
            ProductId("level"): WindowDeclaration(
                WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE
            )
        }
    )
    events: list[str] = []
    emitted_payload: Payload | None = None
    fetched_window: FetchWindow | None = None
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]] | None = None

    @staticmethod
    def fetch(
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        window: FetchWindow,
        config: ProviderConfig,
        transport: object,
    ) -> WithIssues[tuple[Payload, ...]]:
        _EngineModule.events.append("fetch")
        _EngineModule.fetched_window = window
        _EngineModule.rendered_windows = rendered_windows
        payload = Payload(
            source_coordinates=_EngineModule.coordinates,
            station_products=((stations[0], products[0]),),
            fetch_window=window,
            content=b"test payload",
            origin=_origin(),
            prerequisite_calls=(),
        )
        _EngineModule.emitted_payload = payload
        return WithIssues(
            value=(payload,),
            issues=(
                Issue(
                    severity="warning",
                    code="test.engine.warning",
                    message="engine warning",
                    provider_id=ProviderId("test_provider"),
                ),
            ),
        )

    @staticmethod
    def parse(payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
        _EngineModule.events.append("parse")
        assert payload is _EngineModule.emitted_payload
        return WithIssues(
            value=pl.DataFrame(
                {
                    "station_id": ["station-1"],
                    "product_id": ["level"],
                    "time": [datetime(2026, 1, 1)],
                    "value": [1.5],
                    "time_zone": ["+00:00"],
                },
                schema=RowsSchema.polars_schema,
            )
        )

    @staticmethod
    def info():
        raise NotImplementedError

    @staticmethod
    def products():
        raise NotImplementedError

    @staticmethod
    def stations():
        raise NotImplementedError

    @staticmethod
    def station_products():
        raise NotImplementedError


class _InfoOnlyEngineModule(_EngineModule):
    @staticmethod
    def fetch(
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        window: FetchWindow,
        config: ProviderConfig,
        transport: object,
    ) -> WithIssues[tuple[Payload, ...]]:
        fetched = _EngineModule.fetch(stations, products, rendered_windows, window, config, transport)
        return WithIssues(value=fetched.value)


def test_registry_initially_empty() -> None:
    registry = ProviderRegistry()

    assert registry.list_provider_ids() == []
    assert registry.iter_records() == ()


def test_registry_registers_stub_provider_and_returns_handle(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")

    handle = registry.register("stub_provider", artifact)

    assert isinstance(handle, _ProviderHandle)
    assert handle.provider_id == "stub_provider"
    assert registry.get("stub_provider") is handle


def test_registry_module_without_engine_stages_rejects_observation_dispatch(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    called = False

    def legacy_observations(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(stub_provider, "observations", legacy_observations)

    handle = registry.register("stub_provider", artifact, provider_module=stub_provider)

    assert handle._module is stub_provider
    assert registry.get("stub_provider") is handle
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider stub_provider has no observation stages registered",
    ):
        handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end="2026-01-02",
        )
    assert called is False


def test_registry_passes_widened_fetch_window_and_preserves_requested_provenance(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("test_provider")
    _EngineModule.events = []
    handle = registry.register(
        "test_provider",
        artifact,
        engine_provider_module=_EngineModule,
    )

    result = handle.observations(
        stations="station-1",
        products="level",
        start="2026-01-01",
        end="2026-01-02",
        on_issue="ignore",
    )

    assert _EngineModule.events == ["fetch", "parse"]
    assert isinstance(_EngineModule.fetched_window, FetchWindow)
    assert isinstance(_EngineModule.fetched_window.start, WindowEndpoint)
    assert _EngineModule.fetched_window.start.isoformat() == "2025-12-30T00:00:00"
    assert _EngineModule.fetched_window.end.isoformat() == "2026-01-04T23:59:59.999999"
    assert _EngineModule.rendered_windows == {ProductId("level"): (RenderedWindow("2025-12-30", "2026-01-04"),)}
    pl_testing.assert_frame_equal(
        result.data,
        pl.DataFrame(
            {
                "time": [datetime(2026, 1, 1)],
                "time_zone": ["+00:00"],
                "station_id": ["station-1"],
                "product_id": ["level"],
                "value": [1.5],
            },
            schema=ObservationDataSchema.polars_schema,
        ),
        check_exact=True,
    )
    assert tuple(type(result).model_fields) == ("data", "provenance", "issues", "receipts")
    assert result.provenance.source == "test-engine"
    assert result.provenance.request is not None
    assert result.provenance.request["start"] == "2026-01-01T00:00:00"
    assert result.provenance.request["end"] == "2026-01-02T23:59:59.999999"
    assert result.receipts == Receipts(provider_id=ProviderId("test_provider"), entries=())
    _assert_sentinel_unreachable(result)
    assert [issue.code for issue in result.issues] == [
        "test.engine.warning",
        "provenance.license_not_established",
        "provenance.citation_not_established",
    ]


def test_registry_ignores_unverified_provider_info_words(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    stub_artifact = stub_packaged_catalogue_artifact("test_provider")
    artifact = PackagedCatalogArtifact(
        provider_info={
            "provider_id": "test_provider",
            "name": "test_provider Provider",
            "live_stations": False,
            "live_products": False,
            "live_station_products": False,
            "bulk_observations": "none",
            "catalogue_version": "2026.01",
            "license": "https://terms.example.test/provider-license",
            "citation": "Example Hydrology Agency (2026), Gauge observations.",
        },
        products=stub_artifact.products,
        stations=stub_artifact.stations,
        station_products=stub_artifact.station_products,
    )
    handle = registry.register(
        "test_provider",
        artifact,
        engine_provider_module=_InfoOnlyEngineModule,
    )

    result = handle.observations(
        stations="station-1",
        products="level",
        start="2026-01-01",
        end="2026-01-02",
        on_issue="ignore",
    )

    assert result.provenance.license is None
    assert result.provenance.citation is None
    assert {issue.code for issue in result.issues} == {
        "provenance.license_not_established",
        "provenance.citation_not_established",
    }


@pytest.mark.parametrize("on_issue", ("warn", "raise"))
def test_registry_null_license_and_citation_are_silent_info_issues(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    capsys: pytest.CaptureFixture[str],
    on_issue: OnIssue,
) -> None:
    registry = ProviderRegistry()
    stub_artifact = stub_packaged_catalogue_artifact("test_provider")
    artifact = PackagedCatalogArtifact(
        provider_info={
            "provider_id": "test_provider",
            "name": "test_provider Provider",
            "live_stations": False,
            "live_products": False,
            "live_station_products": False,
            "bulk_observations": "none",
            "catalogue_version": "2026.01",
            "license": None,
            "citation": None,
        },
        products=stub_artifact.products,
        stations=stub_artifact.stations,
        station_products=stub_artifact.station_products,
    )
    handle = registry.register(
        "test_provider",
        artifact,
        engine_provider_module=_InfoOnlyEngineModule,
    )

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        result = handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end="2026-01-02",
            on_issue=on_issue,
        )
    captured = capsys.readouterr()

    assert result.provenance.license is None
    assert result.provenance.citation is None
    assert result.issues == (
        Issue(
            severity="info",
            code="provenance.license_not_established",
            message="RivRetrieve has not yet established the license for provider test_provider.",
            details={"field": "license"},
            provider_id=ProviderId("test_provider"),
        ),
        Issue(
            severity="info",
            code="provenance.citation_not_established",
            message="RivRetrieve has not yet established the citation for provider test_provider.",
            details={"field": "citation"},
            provider_id=ProviderId("test_provider"),
        ),
    )
    assert recorded_warnings == []
    assert captured.out == ""
    assert captured.err == ""


def test_registry_preserves_explicit_midnight_end(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    _EngineModule.events = []
    handle = registry.register(
        "test_provider",
        stub_packaged_catalogue_artifact("test_provider"),
        engine_provider_module=_EngineModule,
    )

    result = handle.observations(
        stations="station-1",
        products="level",
        start="2026-01-01",
        end="2026-01-02 00:00",
        on_issue="ignore",
    )

    assert _EngineModule.fetched_window is not None
    assert _EngineModule.fetched_window.end.isoformat() == "2026-01-04T00:00:00"
    assert result.provenance.request is not None
    assert result.provenance.request["end"] == "2026-01-02T00:00:00"


def test_registry_observations_converter_leak_raises_fatal_contract_error_naming_row(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    _EngineModule.events = []
    _registry.register(
        "test_provider",
        stub_packaged_catalogue_artifact("test_provider"),
        engine_provider_module=_EngineModule,
    )

    def faulty_convert(
        rows: Rows,
        config: ProviderConfig,
        window: object,
    ) -> WithIssues[CanonicalRows]:
        return WithIssues(
            value=pl.DataFrame(
                {
                    "time": [datetime(2026, 1, 3)],
                    "time_zone": ["+00:00"],
                    "station_id": ["station-1"],
                    "product_id": ["level"],
                    "value": [1.5],
                },
                schema=CanonicalRowsSchema.polars_schema,
            )
        )

    monkeypatch.setattr(driver_module, "convert", faulty_convert)

    with pytest.raises(FatalContractError) as exc_info:
        _registry.get("test_provider").observations(
            stations="station-1",
            products="level",
            start="2026-01-01T00:00:00",
            end="2026-01-02T23:59:59.999999",
            on_issue="ignore",
        )

    assert not isinstance(exc_info.value, IssuePolicyError)
    assert exc_info.value.issues == ()
    assert str(exc_info.value) == (
        "CanonicalRows zero-based row index 0 is outside RequestedWindow on the Instant timestamp axis: "
        "timestamp=2026-01-03T00:00:00, time_zone='+00:00', station_id='station-1', "
        "product_id='level', requested_start=2026-01-01T00:00:00, "
        "requested_end=2026-01-02T23:59:59.999999. This is a convert-stage contract breach; please "
        "report this row and request window."
    )
    assert _EngineModule.events == ["fetch", "parse"]


def test_registry_observations_exclusive_stop_source_keeps_reading_at_closed_requested_end(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)

    class _ExclusiveStopModule:
        observation_source = "exclusive-stop-test"
        coordinates = SourceCoordinates({"field": "value"})
        config = ProviderConfig(
            zone=ZoneValue("+00:00"),
            products={
                ProductId("level"): ProductConfig(
                    coordinates=coordinates,
                    unit=Unit.M,
                    semantics=Instant(),
                )
            },
        )
        window_declarations = ProductWindowDeclarations(
            {
                ProductId("level"): WindowDeclaration(
                    WindowGranularity("iso-instant"),
                    WindowRenderingVocabulary.ISO_INSTANT,
                    StopConvention.EXCLUSIVE,
                )
            }
        )
        events: list[str] = []
        renderings: tuple[RenderedWindow, ...] = ()

        @staticmethod
        def fetch(
            stations: tuple[str, ...],
            products: tuple[ProductId, ...],
            rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
            window: FetchWindow,
            config: ProviderConfig,
            transport: object,
        ) -> WithIssues[tuple[Payload, ...]]:
            _ExclusiveStopModule.events.append("fetch")
            _ExclusiveStopModule.renderings = rendered_windows[ProductId("level")]
            rendered = _ExclusiveStopModule.renderings[0]
            rendered_start = datetime.fromisoformat(rendered.start.removesuffix("Z"))
            assert rendered.stop is not None
            rendered_stop = datetime.fromisoformat(rendered.stop.removesuffix("Z"))
            reading = datetime(2026, 1, 2, 12)
            selected = (reading,) if rendered_start <= reading < rendered_stop else ()
            return WithIssues(
                value=(
                    Payload(
                        source_coordinates=_ExclusiveStopModule.coordinates,
                        station_products=((stations[0], products[0]),),
                        fetch_window=window,
                        content=json.dumps([value.isoformat() for value in selected]).encode(),
                        origin=_origin(),
                        prerequisite_calls=(),
                    ),
                )
            )

        @staticmethod
        def parse(payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
            _ExclusiveStopModule.events.append("parse")
            readings = tuple(datetime.fromisoformat(value) for value in json.loads(payload.content))
            return WithIssues(
                value=pl.DataFrame(
                    {
                        "station_id": ["station-1" for _ in readings],
                        "product_id": ["level" for _ in readings],
                        "time": list(readings),
                        "value": [1.5 for _ in readings],
                        "time_zone": ["+00:00" for _ in readings],
                    },
                    schema=RowsSchema.polars_schema,
                )
            )

    _registry.register(
        "exclusive_stop_provider",
        stub_packaged_catalogue_artifact("exclusive_stop_provider"),
        engine_provider_module=_ExclusiveStopModule,
    )

    result = _registry.get("exclusive_stop_provider").observations(
        stations="station-1",
        products="level",
        start="2026-01-02T12:00:00",
        end="2026-01-02T12:00:00",
        on_issue="ignore",
    )

    assert _ExclusiveStopModule.renderings == (
        RenderedWindow(
            start="2025-12-31T12:00:00Z",
            stop="2026-01-04T12:00:00.000001Z",
        ),
    )
    expected = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 12)],
            "time_zone": ["+00:00"],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "value": [1.5],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.data, expected, check_exact=True)
    assert result.issues == (
        Issue(
            severity="info",
            code="provenance.license_not_established",
            message="RivRetrieve has not yet established the license for provider exclusive_stop_provider.",
            details={"field": "license"},
            provider_id=ProviderId("exclusive_stop_provider"),
        ),
        Issue(
            severity="info",
            code="provenance.citation_not_established",
            message="RivRetrieve has not yet established the citation for provider exclusive_stop_provider.",
            details={"field": "citation"},
            provider_id=ProviderId("exclusive_stop_provider"),
        ),
    )
    assert _ExclusiveStopModule.events == ["fetch", "parse"]


def test_registry_observations_parameterless_fixed_span_returns_rows_and_undercoverage_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    undercoverage_issue = Issue(
        severity="warning",
        code="fetch.source_under_coverage",
        message="ba_fhmzbih-shaped fixed-span source covers less than the requested window",
        details={
            "available_start": "2026-01-01T00:00:00",
            "available_end": "2026-01-02T00:00:00",
        },
        provider_id=ProviderId("fixed_span_provider"),
    )

    class _FixedSpanModule:
        observation_source = "fixed-span-test"
        coordinates = SourceCoordinates({"field": "value"})
        config = ProviderConfig(
            zone=ZoneValue("+00:00"),
            products={
                ProductId("level"): ProductConfig(
                    coordinates=coordinates,
                    unit=Unit.M,
                    semantics=Instant(),
                )
            },
        )
        window_declarations = ProductWindowDeclarations(
            {
                ProductId("level"): WindowDeclaration(
                    WindowGranularity("none"), WindowRenderingVocabulary.NONE, StopConvention.INCLUSIVE
                )
            }
        )
        events: list[str] = []
        renderings: tuple[RenderedWindow, ...] | None = None

        @staticmethod
        def fetch(
            stations: tuple[str, ...],
            products: tuple[ProductId, ...],
            rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
            window: FetchWindow,
            config: ProviderConfig,
            transport: object,
        ) -> WithIssues[tuple[Payload, ...]]:
            _FixedSpanModule.events.append("fetch")
            _FixedSpanModule.renderings = rendered_windows[ProductId("level")]
            assert _FixedSpanModule.renderings == ()
            return WithIssues(
                value=(
                    Payload(
                        source_coordinates=_FixedSpanModule.coordinates,
                        station_products=((stations[0], products[0]),),
                        fetch_window=window,
                        content=b'["2026-01-01T00:00:00","2026-01-02T00:00:00"]',
                        origin=_origin(),
                        prerequisite_calls=(),
                    ),
                ),
                issues=(undercoverage_issue,),
            )

        @staticmethod
        def parse(payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
            _FixedSpanModule.events.append("parse")
            readings = tuple(datetime.fromisoformat(value) for value in json.loads(payload.content))
            return WithIssues(
                value=pl.DataFrame(
                    {
                        "station_id": ["station-1", "station-1"],
                        "product_id": ["level", "level"],
                        "time": list(readings),
                        "value": [1.0, 2.0],
                        "time_zone": ["+00:00", "+00:00"],
                    },
                    schema=RowsSchema.polars_schema,
                )
            )

    _registry.register(
        "fixed_span_provider",
        stub_packaged_catalogue_artifact("fixed_span_provider"),
        engine_provider_module=_FixedSpanModule,
    )

    result = _registry.get("fixed_span_provider").observations(
        stations="station-1",
        products="level",
        start="2025-01-01T00:00:00",
        end="2026-01-03T00:00:00",
        on_issue="ignore",
    )

    assert _FixedSpanModule.renderings == ()
    expected = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1), datetime(2026, 1, 2)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["station-1", "station-1"],
            "product_id": ["level", "level"],
            "value": [1.0, 2.0],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.data, expected, check_exact=True)
    assert result.issues == (
        undercoverage_issue,
        Issue(
            severity="info",
            code="provenance.license_not_established",
            message="RivRetrieve has not yet established the license for provider fixed_span_provider.",
            details={"field": "license"},
            provider_id=ProviderId("fixed_span_provider"),
        ),
        Issue(
            severity="info",
            code="provenance.citation_not_established",
            message="RivRetrieve has not yet established the citation for provider fixed_span_provider.",
            details={"field": "citation"},
            provider_id=ProviderId("fixed_span_provider"),
        ),
    )
    assert isinstance(result.issues[0], Issue)
    assert _FixedSpanModule.events == ["fetch", "parse"]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            "start must be wall-clock time without a time zone; remove it with `start = start.replace(tzinfo=None)`.",
        ),
        (
            "2026-01-01T00:00:00+02:00",
            "start must be wall-clock time without a time zone; remove it with `start = datetime.fromisoformat(start).replace(tzinfo=None)`.",
        ),
    ],
)
def test_registry_rejects_zone_carrying_endpoint_before_fetch(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    value: object,
    message: str,
) -> None:
    registry = ProviderRegistry()
    _EngineModule.events = []
    handle = registry.register(
        "test_provider",
        stub_packaged_catalogue_artifact("test_provider"),
        engine_provider_module=_EngineModule,
    )

    with pytest.raises(InvalidObservationRequestError) as exc_info:
        handle.observations(
            stations="station-1",
            products="level",
            start=value,
            end="2026-01-02",
            on_issue="ignore",
        )

    assert str(exc_info.value) == message
    assert _EngineModule.events == []


def test_registry_engine_module_warns_for_accumulated_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    handle = registry.register(
        "test_provider",
        stub_packaged_catalogue_artifact("test_provider"),
        engine_provider_module=_EngineModule,
    )

    with pytest.warns(RuntimeWarning, match="engine warning"):
        handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end="2026-01-02",
            on_issue="warn",
        )


def test_registry_engine_module_raises_for_accumulated_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    handle = registry.register(
        "test_provider",
        stub_packaged_catalogue_artifact("test_provider"),
        engine_provider_module=_EngineModule,
    )

    with pytest.raises(IssuePolicyError):
        handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end="2026-01-02",
            on_issue="raise",
        )


def test_registry_rejects_both_module_registration_modes(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("test_provider")

    with pytest.raises(
        FatalContractError,
        match="Register either provider_module or engine_provider_module, not both",
    ):
        registry.register(
            "test_provider",
            artifact,
            provider_module=_EngineModule,
            engine_provider_module=_EngineModule,
        )


def test_registry_register_artifact_only_remains_back_compatible(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")

    handle = registry.register("stub_provider", artifact)

    assert handle._module is None
    assert handle.info() == ProviderInfo.from_row(artifact.provider_info)


def test_registry_rejects_duplicate_provider_id(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    registry.register("stub_provider", artifact)

    with pytest.raises(FatalContractError):
        registry.register("stub_provider", artifact)


@pytest.mark.parametrize("provider_id", ["", "ProviderId", "BAD-Provider", "provider.id", "1provider"])
def test_registry_rejects_invalid_provider_id_format(
    provider_id: str,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")

    with pytest.raises(FatalContractError):
        registry.register(provider_id, artifact)


def test_registry_rejects_provider_id_mismatch(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")

    with pytest.raises(FatalContractError):
        registry.register("other_provider", artifact)


def test_registry_get_unknown_provider_raises_unknown_provider_error() -> None:
    registry = ProviderRegistry()

    with pytest.raises(UnknownProviderError) as exc_info:
        registry.get("missing")

    assert isinstance(exc_info.value, FatalContractError)
    assert not isinstance(exc_info.value, IssuePolicyError)


def _has_issue_policy_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, IssuePolicyError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def test_registered_runtime_info_fatal_failures_are_direct(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    bad_artifact = PackagedCatalogArtifact(
        provider_info={**artifact.provider_info, "name": 123},
        products=artifact.products,
        stations=artifact.stations,
        station_products=artifact.station_products,
    )
    handle = _ProviderHandle(provider_id=ProviderId("stub_provider"), _artifact=bad_artifact)

    with pytest.raises(ProviderInfoValidationError) as exc_info:
        handle.info()

    assert not _has_issue_policy_error(exc_info.value)


def test_registered_runtime_info_reads_packaged_artifact_row(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")

    handle = registry.register("stub_provider", artifact)

    assert handle.info() == ProviderInfo.from_row(artifact.provider_info)


def test_registered_ca_runtime_is_bulk_and_rejects_removed_extras() -> None:
    rr.providers()
    handle = _registry.get("ca_eccc")

    assert handle._stages is None
    assert handle._store_config is ca_eccc_config
    assert handle._store_root is not None
    for attribute in ("cache_status", "refresh_cache", "row_annotation_schema"):
        with pytest.raises(AttributeError, match=rf"Provider 'ca_eccc' has no attribute '{attribute}'"):
            getattr(handle, attribute)


def test_registered_runtime_info_malformed_artifact_row_raises_provider_info_validation_error(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    bad_artifact = PackagedCatalogArtifact(
        provider_info={**artifact.provider_info, "live_products": None},
        products=artifact.products,
        stations=artifact.stations,
        station_products=artifact.station_products,
    )
    handle = _ProviderHandle(provider_id=ProviderId("stub_provider"), _artifact=bad_artifact)

    with pytest.raises(ProviderInfoValidationError):
        handle.info()


def test_registered_runtime_products_reads_artifact_not_provider_module(registered_stub: RegisteredStub) -> None:
    with pytest.raises(NotImplementedError):
        stub_provider.products()

    result = registered_stub.handle.products()

    pl_testing.assert_frame_equal(result.data, registered_stub.handle._artifact.products, check_exact=True)
    assert result.issues == ()


def test_registered_runtime_stations_reads_artifact_not_provider_module(registered_stub: RegisteredStub) -> None:
    with pytest.raises(NotImplementedError):
        stub_provider.stations()

    result = registered_stub.handle.stations()

    pl_testing.assert_frame_equal(result.data, registered_stub.handle._artifact.stations, check_exact=True)
    assert result.issues == ()


def test_registered_runtime_station_products_reads_artifact_not_provider_module(
    registered_stub: RegisteredStub,
) -> None:
    with pytest.raises(NotImplementedError):
        stub_provider.station_products()

    result = registered_stub.handle.station_products()

    pl_testing.assert_frame_equal(result.data, registered_stub.handle._artifact.station_products, check_exact=True)
    assert result.issues == ()


def test_registered_runtime_catalogue_methods_have_registered_provider_provenance(
    registered_stub: RegisteredStub,
) -> None:
    expected = CatalogProvenance(
        source="packaged",
        provider_id=ProviderId("stub_provider"),
        rivretrieve_version=rr.__version__,
        catalogue_version="2026.01",
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )

    assert registered_stub.handle.products().provenance == expected
    assert registered_stub.handle.stations().provenance == expected
    assert registered_stub.handle.station_products().provenance == expected


def test_observation_result_carries_shared_acquisition_provenance(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    from tests._catalogue import catalogue_path

    original = load_packaged_catalogue_artifact(catalogue_path("jp_mlit")).acquisition_provenance
    assert original is not None
    shared = original.model_copy(update={"header": original.header.model_copy(update={"provider_id": "test_provider"})})
    artifact = replace(
        stub_packaged_catalogue_artifact("test_provider"),
        acquisition_provenance=shared,
    )
    registry = ProviderRegistry()
    handle = registry.register("test_provider", artifact, engine_provider_module=_EngineModule)

    result = handle.observations(
        stations="station-1",
        products="level",
        start="2026-01-01",
        end="2026-01-02",
        on_issue="ignore",
    )

    assert result.provenance.acquisition_provenance is shared
    assert result.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]


@pytest.mark.parametrize("provider_id", ("usgs_nwis", "za_dws", "ca_eccc", "ch_foen", "fr_hubeau", "pl_imgw", "br_ana"))
def test_registry_terms_come_from_verified_acquisition_statements(
    source_terms_catalogue_artifact: Callable[[str], PackagedCatalogArtifact],
    provider_id: str,
) -> None:
    artifact = source_terms_catalogue_artifact(provider_id)
    provenance = artifact.acquisition_provenance
    assert provenance is not None
    handle = ProviderRegistry().register(provider_id, artifact, engine_provider_module=_InfoOnlyEngineModule)
    result = handle.observations(
        stations="station-1", products="level", start="2026-01-01", end="2026-01-02", on_issue="ignore"
    )
    expected = {
        statement.kind: statement.exact_text
        for source in provenance.header.source_records
        if source.source_id != "ch_existenz" and provider_id not in ("pl_imgw", "br_ana")
        for statement in source.statements
        if statement.kind in ("license", "citation")
    }
    assert result.provenance.license == expected.get("license")
    assert result.provenance.citation == expected.get("citation")
    assert {issue.code for issue in result.issues} == (
        {"provenance.license_not_established", "provenance.citation_not_established"}
        if provider_id in ("za_dws", "pl_imgw", "br_ana")
        else set()
    )
