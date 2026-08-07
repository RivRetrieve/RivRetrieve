from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.issues import InvalidCatalogueSourceError, IssuePolicyError
from rivretrieve._internal.registry import UnknownProviderError, _registry
from rivretrieve._internal.results import CatalogResult
from tests._stubs import stub_provider


def test_m2_exit_criteria_public_surface_sweep(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    _registry.clear()
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


def _public_protocol_methods(protocol: type[object]) -> set[str]:
    protocol_attrs = getattr(protocol, "__protocol_attrs__", None)
    if protocol_attrs is not None:
        return set(protocol_attrs)
    return {name for name, value in vars(protocol).items() if not name.startswith("_") and callable(value)}
