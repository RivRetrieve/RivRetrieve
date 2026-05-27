from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import date

import polars as pl
import pytest

from rivretrieve._internal.catalogues.artifact import (
    PackagedCatalogArtifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.schemas import AvailabilityDtype
from rivretrieve._internal.registry import ProviderRegistry, _ProviderHandle, _registry


@dataclass(frozen=True)
class RegisteredStub:
    registry: ProviderRegistry
    handle: _ProviderHandle


def _provider_info(provider_id: str, catalogue_version: str | None) -> dict[str, object]:
    return {
        "provider_id": provider_id,
        "name": f"{provider_id} Provider",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": catalogue_version,
        "metadata": {"homepage": f"https://{provider_id}.example.invalid"},
    }


def _products(provider_id: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "provider_id": [provider_id],
            "product_id": ["level"],
            "observed_property": ["water_level"],
            "frequency": ["daily"],
            "statistic": ["mean"],
            "period_type": ["calendar_day"],
            "period_anchor": ["UTC"],
            "unit": ["m"],
            "native_id": ["WATER_LEVEL"],
            "derived": [False],
            "derivation_method": [None],
            "metadata": ["{}"],
        },
        schema={
            "provider_id": pl.Utf8,
            "product_id": pl.Utf8,
            "observed_property": pl.Utf8,
            "frequency": pl.Utf8,
            "statistic": pl.Utf8,
            "period_type": pl.Utf8,
            "period_anchor": pl.Utf8,
            "unit": pl.Utf8,
            "native_id": pl.Utf8,
            "derived": pl.Boolean,
            "derivation_method": pl.Utf8,
            "metadata": pl.Utf8,
        },
    )


def _stations(provider_id: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "provider_id": [provider_id],
            "station_id": ["station-1"],
            "name": ["Station 1"],
            "latitude": [46.2],
            "longitude": [7.1],
            "country": ["CH"],
            "elevation_m": [None],
            "drainage_area_km2": [56.7],
            "start_date": [date(2020, 1, 1)],
            "end_date": [None],
            "metadata": ["{}"],
        },
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "name": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "country": pl.Utf8,
            "elevation_m": pl.Float64,
            "drainage_area_km2": pl.Float64,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "metadata": pl.Utf8,
        },
    )


def _station_products(provider_id: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "provider_id": [provider_id],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "availability": ["available"],
            "availability_reason": [None],
            "start_date": [date(2020, 1, 1)],
            "end_date": [None],
            "last_catalogue_check": [date(2026, 1, 1)],
            "metadata": ["{}"],
        },
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": AvailabilityDtype,
            "availability_reason": pl.Utf8,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "last_catalogue_check": pl.Date,
            "metadata": pl.Utf8,
        },
    )


@pytest.fixture
def stub_packaged_catalogue_artifact() -> Callable[..., PackagedCatalogArtifact]:
    def build(
        provider_id: str = "stub_provider",
        *,
        catalogue_version: str | None = "2026.01",
    ) -> PackagedCatalogArtifact:
        return packaged_catalogue_artifact_from_components(
            _provider_info(provider_id, catalogue_version),
            _products(provider_id),
            _stations(provider_id),
            _station_products(provider_id),
            on_issue="raise",
        )

    return build


@pytest.fixture(autouse=True)
def clear_provider_registry() -> Generator[None]:
    _registry.clear()
    yield
    _registry.clear()


@pytest.fixture
def fresh_registry() -> ProviderRegistry:
    return ProviderRegistry()


@pytest.fixture
def registered_stub(
    fresh_registry: ProviderRegistry,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> RegisteredStub:
    from tests._stubs import stub_provider

    artifact = stub_provider.build_artifact(stub_packaged_catalogue_artifact)
    handle = fresh_registry.register("stub_provider", artifact)
    return RegisteredStub(registry=fresh_registry, handle=handle)
