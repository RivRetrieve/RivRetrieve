from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pandas.testing as pd_testing
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.issues import (
    AnnotationSchemaViolationError,
    InvalidCatalogueSourceError,
    InvalidObservationRequestError,
    IssuePolicyError,
)
from rivretrieve._internal.observations import AnnotationTable, ObservationRequest, ObservationResult
from rivretrieve._internal.registry import UnknownProviderError, _registry
from rivretrieve._internal.results import CatalogResult
from tests._stubs import stub_provider


def test_m2_exit_criteria_public_surface_sweep(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact = stub_packaged_catalogue_artifact_rich("stub_provider")
    _registry.register("stub_provider", artifact, provider_module=stub_provider)

    assert rr.providers() == ["stub_provider"]
    with pytest.raises(UnknownProviderError):
        rr.provider("missing")

    handle = rr.provider("stub_provider")
    assert isinstance(handle, rr.ProviderHandle)
    assert _public_protocol_methods(rr.ProviderHandle) == {
        "info",
        "products",
        "stations",
        "station_products",
        "row_annotation_schema",
        "series_annotation_schema",
        "observations",
    }

    packaged_results = [
        rr.provider_info(),
        rr.products(),
        rr.product_info(),
        rr.stations(),
        handle.products(),
        handle.products(observed_property="water_level", frequency="hourly", statistic="instantaneous"),
        handle.stations(),
        handle.station_products(stations=["station-1", "station-2"]),
    ]
    assert all(isinstance(result, CatalogResult) for result in packaged_results)
    assert all(isinstance(result.data, pl.DataFrame) for result in packaged_results)
    assert all(result.provenance.source == "packaged" for result in packaged_results)
    assert handle.products().data["product_id"].to_list() == ["level", "flow", "level_hourly", "level_max"]
    assert handle.stations().data["station_id"].to_list() == ["station-1", "station-2"]
    assert handle.station_products().data["product_id"].to_list() == [
        "level",
        "flow",
        "level_hourly",
        "level_max",
    ]

    with pytest.raises(InvalidCatalogueSourceError):
        handle.products(source=cast(Any, "invalid"))

    with pytest.warns(RuntimeWarning, match="does not support live catalogue"):
        live_warn = handle.products(source="live", on_issue="warn")
    assert len(live_warn.issues) == 1
    with pytest.raises(IssuePolicyError):
        handle.products(source="live", on_issue="raise")
    live_ignore = handle.products(source="live", on_issue="ignore")
    assert len(live_ignore.issues) == 1

    calls = {"observations": 0}
    original_observations = stub_provider.observations

    def observation_spy(request: ObservationRequest, *, on_issue: Any = "warn") -> ObservationResult:
        calls["observations"] += 1
        return original_observations(request, on_issue=on_issue)

    monkeypatch.setattr(stub_provider, "observations", observation_spy)

    with pytest.raises(InvalidObservationRequestError, match="start is required"):
        handle.observations(stations="station-1", products="level", start=None, end="2026-01-02")
    with pytest.raises(InvalidObservationRequestError, match="end is required"):
        handle.observations(stations="station-1", products="level", start="2026-01-01", end=None)
    assert calls == {"observations": 0}

    single = handle.observations(
        stations="station-1",
        products="level",
        start="2026-01-01",
        end="2026-01-02",
    )
    many = handle.observations(
        stations=["station-1", "station-2"],
        products=["level", "flow"],
        start="2026-01-01",
        end="2026-01-02",
    )
    assert isinstance(single, ObservationResult)
    assert isinstance(many, ObservationResult)
    assert single.data.height == 2
    assert many.data.height == 8
    assert calls == {"observations": 2}

    pl_testing.assert_frame_equal(single.data, single.to_polars())
    assert single.data is single.to_polars()
    pd_testing.assert_frame_equal(single.to_pandas(), single.data.to_pandas())

    def bad_annotation_observations(request: ObservationRequest, *, on_issue: Any = "warn") -> ObservationResult:
        result = original_observations(request, on_issue=on_issue)
        bad_rows = result.row_annotations.data.with_columns(pl.lit("row.bad").alias("annotation"))
        return result.model_copy(
            update={
                "row_annotations": AnnotationTable(
                    bad_rows,
                    result.row_annotations.schema,
                )
            }
        )

    monkeypatch.setattr(stub_provider, "observations", bad_annotation_observations)
    with pytest.raises(AnnotationSchemaViolationError, match="row.bad"):
        handle.observations(
            stations="station-1",
            products="level",
            start="2026-01-01",
            end="2026-01-02",
        )


def _public_protocol_methods(protocol: type[object]) -> set[str]:
    protocol_attrs = getattr(protocol, "__protocol_attrs__", None)
    if protocol_attrs is not None:
        return set(protocol_attrs)
    return {name for name, value in vars(protocol).items() if not name.startswith("_") and callable(value)}
