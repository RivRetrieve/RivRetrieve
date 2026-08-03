from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.engine import (
    FetchWindow,
    Instant,
    Payload,
    ProductConfig,
    ProviderConfig,
    Rows,
    RowsSchema,
    SourceCoordinates,
    Unit,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError, Issue, IssuePolicyError, ObservationsUnavailableError
from rivretrieve._internal.observations import (
    AnnotationSchema,
    RawPayload,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo, ProviderInfoValidationError
from rivretrieve._internal.registry import ProviderRegistry, UnknownProviderError, _ProviderHandle
from rivretrieve._internal.results import CatalogProvenance
from tests._stubs import stub_provider
from tests.conftest import RegisteredStub


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
    events: list[str] = []
    emitted_payload: Payload | None = None
    fetched_window: FetchWindow | None = None

    @staticmethod
    def fetch(
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        window: FetchWindow,
        config: ProviderConfig,
    ) -> WithIssues[tuple[Payload, ...]]:
        _EngineModule.events.append("fetch")
        _EngineModule.fetched_window = window
        payload = Payload(
            source_coordinates=_EngineModule.coordinates,
            station_products=((stations[0], products[0]),),
            fetch_window=window,
            content=b"test payload",
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

    @staticmethod
    def row_annotation_schema() -> list[AnnotationSchema]:
        return [AnnotationSchema("declared_row", "declared row", "string")]

    @staticmethod
    def series_annotation_schema() -> list[AnnotationSchema]:
        return [AnnotationSchema("declared_series", "declared series", "string")]


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
    assert handle.row_annotation_schema() == stub_provider.row_annotation_schema()
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


def test_registry_engine_module_drives_and_packages_public_result(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
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
    assert set(result.data.columns) == {"time", "station_id", "product_id", "value"}
    pl_testing.assert_frame_equal(
        result.row_annotations.data,
        pl.DataFrame(schema=RowAnnotationTableSchema.polars_schema),
        check_exact=True,
    )
    pl_testing.assert_frame_equal(
        result.series_annotations.data,
        pl.DataFrame(schema=SeriesAnnotationTableSchema.polars_schema),
        check_exact=True,
    )
    assert result.provenance.source == "test-engine"
    assert result.raw == RawPayload(provider_id=ProviderId("test_provider"))
    assert [issue.code for issue in result.issues] == ["test.engine.warning"]


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


def test_minimal_engine_module_declares_nonempty_row_schema() -> None:
    assert [schema.annotation_id for schema in _EngineModule.row_annotation_schema()] == ["declared_row"]


def test_minimal_engine_module_declares_nonempty_series_schema() -> None:
    assert [schema.annotation_id for schema in _EngineModule.series_annotation_schema()] == ["declared_series"]


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


def test_provider_handle_info_fatal_failures_are_direct(
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


def test_provider_handle_info_reads_packaged_artifact_row(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")

    handle = registry.register("stub_provider", artifact)

    assert handle.info() == ProviderInfo.from_row(artifact.provider_info)


def test_provider_handle_info_malformed_artifact_row_raises_provider_info_validation_error(
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


def test_provider_handle_products_reads_artifact_not_provider_module(registered_stub: RegisteredStub) -> None:
    with pytest.raises(NotImplementedError):
        stub_provider.products()

    result = registered_stub.handle.products()

    pl_testing.assert_frame_equal(result.data, registered_stub.handle._artifact.products, check_exact=True)
    assert result.issues == ()


def test_provider_handle_stations_reads_artifact_not_provider_module(registered_stub: RegisteredStub) -> None:
    with pytest.raises(NotImplementedError):
        stub_provider.stations()

    result = registered_stub.handle.stations()

    pl_testing.assert_frame_equal(result.data, registered_stub.handle._artifact.stations, check_exact=True)
    assert result.issues == ()


def test_provider_handle_station_products_reads_artifact_not_provider_module(registered_stub: RegisteredStub) -> None:
    with pytest.raises(NotImplementedError):
        stub_provider.station_products()

    result = registered_stub.handle.station_products()

    pl_testing.assert_frame_equal(result.data, registered_stub.handle._artifact.station_products, check_exact=True)
    assert result.issues == ()


def test_provider_handle_catalogue_methods_have_registered_provider_provenance(
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
