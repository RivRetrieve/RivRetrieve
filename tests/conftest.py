from __future__ import annotations

import os
import sys
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.catalogues.artifact import (
    ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS,
    PackagedCatalogArtifact,
    load_packaged_catalogue_artifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.catalogues.schemas import AvailabilityDtype
from rivretrieve._internal.registry import ProviderRegistry, _ProviderHandle, _registry

pytest_plugins = ("tests._distribution",)


@pytest.fixture(scope="session")
def retained_evidence_root() -> Path:
    """Locate explicitly supplied archive inputs in their repository-relative layout."""
    from tests._evidence import resolve_retained_evidence_root

    return resolve_retained_evidence_root(os.environ.get("RIVRETRIEVE_TEST_EVIDENCE_ROOT"))


def _packaged_provenance(provider_id: str) -> CatalogueEvidence | None:
    if provider_id not in ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS:
        return None
    path = (
        Path(__file__).parents[1]
        / "src"
        / "rivretrieve"
        / "_internal"
        / "providers"
        / provider_id
        / "catalogue"
        / "provenance.json"
    )
    return load_packaged_catalogue_artifact(path.parent, on_issue="raise").acquisition_provenance


@dataclass(frozen=True)
class RegisteredStub:
    registry: ProviderRegistry
    handle: _ProviderHandle


def _provider_info(
    provider_id: str,
    catalogue_version: str | None,
    *,
    live_stations: bool = False,
    live_products: bool = False,
    live_station_products: bool = False,
) -> dict[str, object]:
    return {
        "provider_id": provider_id,
        "name": f"{provider_id} Provider",
        "live_stations": live_stations,
        "live_products": live_products,
        "live_station_products": live_station_products,
        "bulk_observations": "none",
        "catalogue_version": catalogue_version,
        "license": None,
        "citation": None,
    }


def _products(provider_id: str, *, rich: bool = False) -> pl.DataFrame:
    rows = [
        {
            "provider_id": provider_id,
            "product_id": "level",
            "observed_property": "water_level",
            "frequency": "daily",
            "statistic": "mean",
            "period_type": "calendar_day",
            "period_anchor": "UTC",
            "unit": "m",
            "native_id": "WATER_LEVEL",
        }
    ]
    if rich:
        rows.extend(
            [
                {
                    "provider_id": provider_id,
                    "product_id": "flow",
                    "observed_property": "discharge",
                    "frequency": "daily",
                    "statistic": "mean",
                    "period_type": "calendar_day",
                    "period_anchor": "UTC",
                    "unit": "m3/s",
                    "native_id": "FLOW",
                },
                {
                    "provider_id": provider_id,
                    "product_id": "level_hourly",
                    "observed_property": "water_level",
                    "frequency": "hourly",
                    "statistic": "instantaneous",
                    "period_type": "instant",
                    "period_anchor": "UTC",
                    "unit": "m",
                    "native_id": "WATER_LEVEL_HOURLY",
                },
                {
                    "provider_id": provider_id,
                    "product_id": "level_max",
                    "observed_property": "water_level",
                    "frequency": "daily",
                    "statistic": "max",
                    "period_type": "calendar_day",
                    "period_anchor": "UTC",
                    "unit": "m",
                    "native_id": "WATER_LEVEL_MAX",
                },
            ]
        )

    return pl.DataFrame(
        rows,
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
        },
    )


def _stations(provider_id: str, *, rich: bool = False) -> pl.DataFrame:
    rows = [
        {
            "provider_id": provider_id,
            "station_id": "station-1",
            "latitude": 46.2,
            "longitude": 7.1,
            "crs": "unknown",
        }
    ]
    if rich:
        rows.append(
            {
                "provider_id": provider_id,
                "station_id": "station-2",
                "latitude": 47.1,
                "longitude": 8.3,
                "crs": "unknown",
            }
        )

    return pl.DataFrame(
        rows,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "crs": pl.Utf8,
        },
    )


def _station_products(provider_id: str, *, rich: bool = False) -> pl.DataFrame:
    rows = [
        {
            "provider_id": provider_id,
            "station_id": "station-1",
            "product_id": "level",
            "availability": "available",
            "availability_reason": None,
            "published_record_start_date": date(2020, 1, 1),
            "published_record_end_date": None,
            "last_catalogue_check": date(2026, 1, 1),
        }
    ]
    if rich:
        rows.extend(
            [
                {
                    "provider_id": provider_id,
                    "station_id": "station-1",
                    "product_id": "flow",
                    "availability": "unknown",
                    "availability_reason": "not_catalogued",
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2026, 1, 1),
                },
                {
                    "provider_id": provider_id,
                    "station_id": "station-2",
                    "product_id": "level_hourly",
                    "availability": "available",
                    "availability_reason": None,
                    "published_record_start_date": date(2021, 1, 1),
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2026, 1, 1),
                },
                {
                    "provider_id": provider_id,
                    "station_id": "station-2",
                    "product_id": "level_max",
                    "availability": "unavailable",
                    "availability_reason": "derived_not_supported",
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2026, 1, 1),
                },
            ]
        )

    return pl.DataFrame(
        rows,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": AvailabilityDtype,
            "availability_reason": pl.Utf8,
            "published_record_start_date": pl.Date,
            "published_record_end_date": pl.Date,
            "last_catalogue_check": pl.Date,
        },
    )


@pytest.fixture
def stub_packaged_catalogue_artifact() -> Callable[..., PackagedCatalogArtifact]:
    def build(
        provider_id: str = "stub_provider",
        *,
        catalogue_version: str | None = "2026.01",
        live_stations: bool = False,
        live_products: bool = False,
        live_station_products: bool = False,
    ) -> PackagedCatalogArtifact:
        return packaged_catalogue_artifact_from_components(
            _provider_info(
                provider_id,
                catalogue_version,
                live_stations=live_stations,
                live_products=live_products,
                live_station_products=live_station_products,
            ),
            _products(provider_id),
            _stations(provider_id),
            _station_products(provider_id),
            acquisition_provenance=_packaged_provenance(provider_id),
            withheld_rows_already_applied=True,
            on_issue="raise",
        )

    return build


@pytest.fixture
def stub_packaged_catalogue_artifact_rich() -> Callable[..., PackagedCatalogArtifact]:
    def build(
        provider_id: str = "stub_provider",
        *,
        catalogue_version: str | None = "2026.01",
        live_stations: bool = False,
        live_products: bool = False,
        live_station_products: bool = False,
    ) -> PackagedCatalogArtifact:
        return packaged_catalogue_artifact_from_components(
            _provider_info(
                provider_id,
                catalogue_version,
                live_stations=live_stations,
                live_products=live_products,
                live_station_products=live_station_products,
            ),
            _products(provider_id, rich=True),
            _stations(provider_id, rich=True),
            _station_products(provider_id, rich=True),
            acquisition_provenance=_packaged_provenance(provider_id),
            withheld_rows_already_applied=True,
            on_issue="raise",
        )

    return build


@pytest.fixture
def stub_packaged_catalogue_artifact_live_capable(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> Callable[..., PackagedCatalogArtifact]:
    def build(
        provider_id: str = "stub_provider", *, catalogue_version: str | None = "2026.01"
    ) -> PackagedCatalogArtifact:
        return stub_packaged_catalogue_artifact(
            provider_id,
            catalogue_version=catalogue_version,
            live_stations=True,
            live_products=True,
            live_station_products=True,
        )

    return build


@pytest.fixture(scope="session")
def packaged_catalogue_inputs():
    from rivretrieve._internal.catalogues import artifact as artifact_module
    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
    from tests._catalogue_inputs import PackagedCatalogueInputs

    providers = Path(artifact_module.__file__).parents[1] / "providers"
    return PackagedCatalogueInputs(
        (providers / provider / "catalogue" for provider in BUILTIN_PROVIDER_IDS),
        lambda path: artifact_module.load_packaged_catalogue_artifact(path, on_issue="raise"),
    )


@pytest.fixture
def reuse_packaged_catalogues(monkeypatch, packaged_catalogue_inputs) -> None:
    """Reuse detached package inputs, while registering a fresh real manifest.

    Opt in with ``pytest.mark.usefixtures("reuse_packaged_catalogues")`` only for
    behavior tests whose subject is not artifact loading or registration. Changed
    and unlisted paths still reach the real loader. Registry isolation, dynamic
    declarations, credentials and cache-root composition remain unchanged.
    """
    from functools import wraps

    from rivretrieve._internal.providers import registration

    register = registration.register_manifest

    @wraps(register)
    def register_with_inputs(*args, **kwargs):
        kwargs.setdefault("artifact_loader", packaged_catalogue_inputs.load)
        return register(*args, **kwargs)

    def provenance(provider_id: str) -> CatalogueEvidence | None:
        if provider_id not in ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS:
            return None
        from tests._catalogue import catalogue_path

        return packaged_catalogue_inputs.load(catalogue_path(provider_id)).acquisition_provenance

    monkeypatch.setattr(registration, "register_manifest", register_with_inputs)
    monkeypatch.setattr(sys.modules[__name__], "_packaged_provenance", provenance)


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
    handle = fresh_registry.register("stub_provider", artifact, provider_module=stub_provider)
    return RegisteredStub(registry=fresh_registry, handle=handle)


@pytest.fixture
def source_terms_catalogue_artifact() -> Callable[[str], PackagedCatalogArtifact]:
    """Wire real verified source terms to synthetic engine rows, not certify a catalogue.

    Only registry source-terms unit tests use this direct contract carrier. Ordinary
    stub catalogues continue through the shared component validator. The real
    metadata keeps all its national locator requirements unchanged.
    """

    def build(provider_id: str) -> PackagedCatalogArtifact:
        return PackagedCatalogArtifact(
            provider_info=_provider_info(provider_id, "2026.01"),
            products=_products(provider_id),
            stations=_stations(provider_id),
            station_products=_station_products(provider_id),
            acquisition_provenance=_packaged_provenance(provider_id),
        )

    return build
