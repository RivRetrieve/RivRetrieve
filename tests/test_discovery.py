from __future__ import annotations

from collections.abc import Callable

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
)
from rivretrieve._internal.discovery import product_info, products, stations
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.registry import UnknownProviderError, _ProviderHandle, _registry
from rivretrieve._internal.results import CatalogProvenance, CatalogResult


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


def _disable_default_provider_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    _registry.clear()


def test_providers_empty_registry_returns_default_providers() -> None:
    assert rr.providers() == [
        "ba_fhmzbih",
        "br_ana",
        "ca_eccc",
        "ch_foen",
        "cz_chmi",
        "fr_hubeau",
        "jp_mlit",
        "lt_lhmt",
        "no_nve",
        "pl_imgw",
        "th_thaiwater",
        "usgs_nwis",
    ]


def test_providers_sorted_independent_of_registration_order(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider"))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider"))

    assert rr.providers() == ["a_provider", "z_provider"]


def test_provider_returns_registered_placeholder_object(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    expected = _registry.register("stub_provider", stub_packaged_catalogue_artifact("stub_provider"))

    handle = rr.provider("stub_provider")

    assert isinstance(handle, object)
    assert isinstance(handle, _ProviderHandle)
    assert handle is expected


def test_provider_unknown_raises_unknown_provider_error() -> None:
    with pytest.raises(UnknownProviderError) as exc_info:
        rr.provider("missing")

    assert not isinstance(exc_info.value, IssuePolicyError)
    assert _issue_policy_error_chain(exc_info.value) == []


def test_provider_info_disabled_defaults_empty_registry_returns_schema_conformant_catalog_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_default_provider_registration(monkeypatch)
    expected_provenance = CatalogProvenance(
        source="packaged",
        provider_id=None,
        rivretrieve_version=rr.__version__,
        catalogue_version=None,
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )

    result = rr.provider_info()

    assert isinstance(result, CatalogResult)
    assert result.issues == ()
    assert result.provenance == expected_provenance
    assert result.data.schema == PROVIDER_INFO_CATALOG_SCHEMA.polars_schema
    assert result.data.height == 0


def test_provider_info_aggregates_registered_provider_rows(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider", catalogue_version=None))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider", catalogue_version="2026.02"))
    expected = pl.DataFrame(
        [
            {
                "provider_id": "a_provider",
                "name": "a_provider Provider",
                "live_stations": False,
                "live_products": False,
                "live_station_products": False,
                "bulk_observations": "none",
                "catalogue_version": "2026.02",
                "metadata": '{"homepage":"https://a_provider.example.invalid"}',
            },
            {
                "provider_id": "z_provider",
                "name": "z_provider Provider",
                "live_stations": False,
                "live_products": False,
                "live_station_products": False,
                "bulk_observations": "none",
                "catalogue_version": None,
                "metadata": '{"homepage":"https://z_provider.example.invalid"}',
            },
        ],
        schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema,
    )

    result = rr.provider_info()

    pl_testing.assert_frame_equal(result.data, expected)
    assert result.issues == ()
    assert result.provenance.source == "packaged"


def test_provider_lookup_malformed_id_is_membership_miss() -> None:
    with pytest.raises(UnknownProviderError):
        rr.provider("BAD-Provider")


def test_global_stations_aggregates_registered_packaged_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider"))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider"))

    result = stations()

    assert result.data.select("provider_id", "station_id").rows() == [
        ("a_provider", "station-1"),
        ("z_provider", "station-1"),
    ]
    assert result.data.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert result.issues == ()


def test_global_products_aggregates_registered_packaged_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider"))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider"))

    result = products()

    assert result.data.select("provider_id", "product_id").rows() == [
        ("a_provider", "level"),
        ("z_provider", "level"),
    ]
    assert result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert result.issues == ()


def test_global_product_info_matches_products_contract(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("stub_provider", stub_packaged_catalogue_artifact("stub_provider"))

    products_result = products()
    product_info_result = product_info()

    pl_testing.assert_frame_equal(product_info_result.data, products_result.data)
    assert product_info_result.provenance == products_result.provenance
    assert product_info_result.issues == products_result.issues


def test_global_discovery_disabled_defaults_empty_registry_returns_empty_catalog_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_default_provider_registration(monkeypatch)
    station_result = stations()
    product_result = products()
    product_info_result = product_info()

    assert station_result.data.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert station_result.data.height == 0
    assert product_result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert product_result.data.height == 0
    assert product_info_result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert product_info_result.data.height == 0
    assert station_result.provenance.source == "packaged"
    assert product_result.provenance.source == "packaged"
    assert product_info_result.provenance.source == "packaged"


def test_global_discovery_provenance_is_global_packaged(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("stub_provider", stub_packaged_catalogue_artifact("stub_provider"))
    expected = CatalogProvenance(
        source="packaged",
        provider_id=None,
        rivretrieve_version=rr.__version__,
        catalogue_version=None,
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )

    assert stations().provenance == expected
    assert products().provenance == expected
    assert product_info().provenance == expected


def test_global_discovery_uses_reader_for_table_selection_and_validation(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("stub_provider", stub_packaged_catalogue_artifact("stub_provider"))
    calls = {"stations": 0, "products": 0}

    def read_stations(self: CatalogueReader) -> CatalogResult[pl.DataFrame]:
        calls["stations"] += 1
        return CatalogResult(
            data=self.artifact.stations,
            provenance=CatalogProvenance(source="packaged", provider_id=self.provider_id),
            issues=(),
        )

    def read_products(self: CatalogueReader) -> CatalogResult[pl.DataFrame]:
        calls["products"] += 1
        return CatalogResult(
            data=self.artifact.products,
            provenance=CatalogProvenance(source="packaged", provider_id=self.provider_id),
            issues=(),
        )

    monkeypatch.setattr(CatalogueReader, "read_stations", read_stations)
    monkeypatch.setattr(CatalogueReader, "read_products", read_products)

    stations()
    products()
    product_info()

    assert calls == {"stations": 1, "products": 2}
