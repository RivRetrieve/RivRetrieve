from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.issues import (
    AnnotationSchemaViolationError,
    InvalidObservationRequestError,
    IssuePolicyError,
    ObservationsUnavailableError,
)
from rivretrieve._internal.observations import (
    AnnotationSchema,
    AnnotationTable,
    ObservationDataSchema,
    ObservationProvenance,
    ObservationRequest,
    ObservationResult,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.registry import ProviderRegistry, _registry
from tests._stubs import stub_provider
from tests.conftest import RegisteredStub


def _issue_policy_error_chain(exc: BaseException) -> list[IssuePolicyError]:
    found = []
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, IssuePolicyError):
            found.append(current)
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
    return found


def _expected_data(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=ObservationDataSchema.polars_schema)


def _expected_row_annotations(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=RowAnnotationTableSchema.polars_schema)


def _expected_series_annotations(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SeriesAnnotationTableSchema.polars_schema)


def _valid_result(
    *,
    row_annotation: str = "stub.quality",
    series_annotation: str = "stub.native_unit",
) -> ObservationResult:
    observed_at = datetime(2026, 1, 1)
    return ObservationResult(
        data=_expected_data(
            [
                {
                    "time": observed_at,
                    "station_id": "station-1",
                    "product_id": "level",
                    "value": 1.0,
                }
            ]
        ),
        row_annotations=AnnotationTable(
            _expected_row_annotations(
                [
                    {
                        "time": observed_at,
                        "station_id": "station-1",
                        "product_id": "level",
                        "annotation": row_annotation,
                        "value": "good",
                    }
                ]
            ),
            RowAnnotationTableSchema,
        ),
        series_annotations=AnnotationTable(
            _expected_series_annotations(
                [
                    {
                        "station_id": "station-1",
                        "product_id": "level",
                        "annotation": series_annotation,
                        "value": "m",
                    }
                ]
            ),
            SeriesAnnotationTableSchema,
        ),
        provenance=ObservationProvenance(source="stub", provider_id=ProviderId("stub_provider")),
    )


def _artifact_only_handle(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
):
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    return registry.register("stub_provider", artifact)


def _registered_handle_with_module(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    module: object,
):
    registry = ProviderRegistry()
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    return registry.register("stub_provider", artifact, provider_module=cast(Any, module))


def test_provider_handle_observations_single_station_product_returns_valid_result(
    registered_stub: RegisteredStub,
) -> None:
    result = registered_stub.handle.observations(
        stations="station-1",
        products="level",
        start="2026-01-01",
        end="2026-01-02",
    )

    pl_testing.assert_frame_equal(
        result.data,
        _expected_data(
            [
                {
                    "time": datetime(2026, 1, 1),
                    "station_id": "station-1",
                    "product_id": "level",
                    "value": 1.0,
                },
                {
                    "time": datetime(2026, 1, 2),
                    "station_id": "station-1",
                    "product_id": "level",
                    "value": 2.0,
                },
            ]
        ),
    )
    pl_testing.assert_frame_equal(
        result.row_annotations.data,
        _expected_row_annotations(
            [
                {
                    "time": datetime(2026, 1, 1),
                    "station_id": "station-1",
                    "product_id": "level",
                    "annotation": "stub.quality",
                    "value": "good",
                },
                {
                    "time": datetime(2026, 1, 2),
                    "station_id": "station-1",
                    "product_id": "level",
                    "annotation": "stub.quality",
                    "value": "good",
                },
            ]
        ),
    )
    pl_testing.assert_frame_equal(
        result.series_annotations.data,
        _expected_series_annotations(
            [
                {
                    "station_id": "station-1",
                    "product_id": "level",
                    "annotation": "stub.native_unit",
                    "value": "m",
                }
            ]
        ),
    )
    assert result.provenance.request == {
        "provider_id": "stub_provider",
        "stations": ["station-1"],
        "products": ["level"],
        "start": "2026-01-01T00:00:00",
        "end": "2026-01-02T00:00:00",
    }


def test_provider_handle_observations_bulk_station_product_returns_valid_result(
    registered_stub: RegisteredStub,
) -> None:
    result = registered_stub.handle.observations(
        stations=["station-1", "station-2"],
        products=["level", "flow"],
        start="2026-01-01",
        end="2026-01-02",
    )

    assert result.data.shape == (8, 4)
    assert result.row_annotations.data.shape == (8, 5)
    assert result.series_annotations.data.shape == (4, 4)
    assert result.data["value"].to_list() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]


def test_provider_handle_observations_unknown_station_or_product_returns_empty_result(
    registered_stub: RegisteredStub,
) -> None:
    result = registered_stub.handle.observations(
        stations=["unknown-station"],
        products=["unknown-product"],
        start="2026-01-01",
        end="2026-01-02",
    )

    pl_testing.assert_frame_equal(result.data, _expected_data([]))
    pl_testing.assert_frame_equal(result.row_annotations.data, _expected_row_annotations([]))
    pl_testing.assert_frame_equal(result.series_annotations.data, _expected_series_annotations([]))
    assert result.issues == ()


def test_provider_handle_observations_constructs_normalized_request_before_dispatch(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[ObservationRequest] = []
    original = stub_provider.observations

    def spy(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        received.append(request)
        return original(request, on_issue=on_issue)

    monkeypatch.setattr(stub_provider, "observations", spy)

    registered_stub.handle.observations(
        stations="station-1",
        products=["level"],
        start="2026-01-01",
        end="2026-01-02",
    )

    assert received == [
        ObservationRequest(
            provider_id=ProviderId("stub_provider"),
            stations=("station-1",),
            products=("level",),
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 2),
        )
    ]


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_passes_on_issue_to_module(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
    on_issue: OnIssue,
) -> None:
    received: list[OnIssue] = []
    original = stub_provider.observations

    def spy(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        received.append(on_issue)
        return original(request, on_issue=on_issue)

    monkeypatch.setattr(stub_provider, "observations", spy)

    registered_stub.handle.observations(
        stations="station-1",
        products="level",
        start="2026-01-01",
        end="2026-01-02",
        on_issue=on_issue,
    )

    assert received == [on_issue]


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_missing_start_raises_before_provider_execution(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
    on_issue: OnIssue,
) -> None:
    called = False

    def spy(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        nonlocal called
        called = True
        return stub_provider.observations(request, on_issue=on_issue)

    monkeypatch.setattr(stub_provider, "observations", spy)

    with pytest.raises(InvalidObservationRequestError) as exc_info:
        registered_stub.handle.observations(
            stations="station-1",
            products="level",
            start=cast(Any, None),
            end="2026-01-02",
            on_issue=on_issue,
        )

    assert _issue_policy_error_chain(exc_info.value) == []
    assert called is False


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_missing_end_raises_before_provider_execution(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
    on_issue: OnIssue,
) -> None:
    called = False

    def spy(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        nonlocal called
        called = True
        return stub_provider.observations(request, on_issue=on_issue)

    monkeypatch.setattr(stub_provider, "observations", spy)

    with pytest.raises(InvalidObservationRequestError) as exc_info:
        registered_stub.handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end=cast(Any, None),
            on_issue=on_issue,
        )

    assert _issue_policy_error_chain(exc_info.value) == []
    assert called is False


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_empty_stations_raises_before_provider_execution(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
    on_issue: OnIssue,
) -> None:
    called = False

    def spy(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        nonlocal called
        called = True
        return stub_provider.observations(request, on_issue=on_issue)

    monkeypatch.setattr(stub_provider, "observations", spy)

    with pytest.raises(InvalidObservationRequestError) as exc_info:
        registered_stub.handle.observations(
            stations=[],
            products="level",
            start="2026-01-01",
            end="2026-01-02",
            on_issue=on_issue,
        )

    assert _issue_policy_error_chain(exc_info.value) == []
    assert called is False


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_empty_products_raises_before_provider_execution(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
    on_issue: OnIssue,
) -> None:
    called = False

    def spy(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        nonlocal called
        called = True
        return stub_provider.observations(request, on_issue=on_issue)

    monkeypatch.setattr(stub_provider, "observations", spy)

    with pytest.raises(InvalidObservationRequestError) as exc_info:
        registered_stub.handle.observations(
            stations="station-1",
            products=[],
            start="2026-01-01",
            end="2026-01-02",
            on_issue=on_issue,
        )

    assert _issue_policy_error_chain(exc_info.value) == []
    assert called is False


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_bad_station_product_types_raise_before_provider_execution(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
    on_issue: OnIssue,
) -> None:
    called = False

    def spy(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        nonlocal called
        called = True
        return stub_provider.observations(request, on_issue=on_issue)

    monkeypatch.setattr(stub_provider, "observations", spy)

    with pytest.raises(InvalidObservationRequestError) as exc_info:
        registered_stub.handle.observations(
            stations=[cast(Any, 42)],
            products="level",
            start="2026-01-01",
            end="2026-01-02",
            on_issue=on_issue,
        )

    assert _issue_policy_error_chain(exc_info.value) == []
    assert called is False


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_no_module_registered_raises_direct_fatal_for_every_on_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    on_issue: OnIssue,
) -> None:
    handle = _artifact_only_handle(stub_packaged_catalogue_artifact)

    with pytest.raises(ObservationsUnavailableError) as exc_info:
        handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end="2026-01-02",
            on_issue=on_issue,
        )

    assert _issue_policy_error_chain(exc_info.value) == []


def test_provider_handle_row_annotation_schema_no_module_registered_raises_direct_fatal(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    handle = _artifact_only_handle(stub_packaged_catalogue_artifact)

    with pytest.raises(ObservationsUnavailableError):
        handle.row_annotation_schema()


def test_provider_handle_series_annotation_schema_no_module_registered_raises_direct_fatal(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    handle = _artifact_only_handle(stub_packaged_catalogue_artifact)

    with pytest.raises(ObservationsUnavailableError):
        handle.series_annotation_schema()


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_undeclared_row_annotation_raises_direct_fatal(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
    on_issue: OnIssue,
) -> None:
    def bad_observations(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        return _valid_result(row_annotation="row.bad")

    monkeypatch.setattr(stub_provider, "observations", bad_observations)

    with pytest.raises(AnnotationSchemaViolationError) as exc_info:
        registered_stub.handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end="2026-01-02",
            on_issue=on_issue,
        )

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_provider_handle_observations_undeclared_series_annotation_raises_direct_fatal(
    registered_stub: RegisteredStub,
    monkeypatch: pytest.MonkeyPatch,
    on_issue: OnIssue,
) -> None:
    def bad_observations(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
        return _valid_result(series_annotation="series.bad")

    monkeypatch.setattr(stub_provider, "observations", bad_observations)

    with pytest.raises(AnnotationSchemaViolationError) as exc_info:
        registered_stub.handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end="2026-01-02",
            on_issue=on_issue,
        )

    assert _issue_policy_error_chain(exc_info.value) == []


def test_provider_handle_observations_validates_row_and_series_annotation_names(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    class BadRowModule:
        @staticmethod
        def row_annotation_schema() -> list[AnnotationSchema]:
            return stub_provider.row_annotation_schema()

        @staticmethod
        def series_annotation_schema() -> list[AnnotationSchema]:
            return stub_provider.series_annotation_schema()

        @staticmethod
        def observations(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
            return _valid_result(row_annotation="row.bad", series_annotation="stub.native_unit")

    class BadSeriesModule:
        @staticmethod
        def row_annotation_schema() -> list[AnnotationSchema]:
            return stub_provider.row_annotation_schema()

        @staticmethod
        def series_annotation_schema() -> list[AnnotationSchema]:
            return stub_provider.series_annotation_schema()

        @staticmethod
        def observations(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult:
            return _valid_result(row_annotation="stub.quality", series_annotation="series.bad")

    row_handle = _registered_handle_with_module(stub_packaged_catalogue_artifact, BadRowModule)
    series_handle = _registered_handle_with_module(stub_packaged_catalogue_artifact, BadSeriesModule)

    with pytest.raises(AnnotationSchemaViolationError, match="row.bad"):
        row_handle.observations(stations="station-1", products="level", start="2026-01-01", end="2026-01-02")
    with pytest.raises(AnnotationSchemaViolationError, match="series.bad"):
        series_handle.observations(stations="station-1", products="level", start="2026-01-01", end="2026-01-02")


def test_provider_handle_row_annotation_schema_delegates_to_module(registered_stub: RegisteredStub) -> None:
    assert registered_stub.handle.row_annotation_schema() == stub_provider.row_annotation_schema()


def test_provider_handle_series_annotation_schema_delegates_to_module(registered_stub: RegisteredStub) -> None:
    assert registered_stub.handle.series_annotation_schema() == stub_provider.series_annotation_schema()


def test_registered_stub_fixture_registers_artifact_and_module_in_fresh_registry_only(
    registered_stub: RegisteredStub,
) -> None:
    result = registered_stub.handle.observations(
        stations="station-1",
        products="level",
        start="2026-01-01",
        end="2026-01-02",
    )

    assert result.data.height == 2
    assert registered_stub.registry.list_provider_ids() == ["stub_provider"]
    assert _registry.list_provider_ids() == []
