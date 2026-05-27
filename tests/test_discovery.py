from __future__ import annotations

from collections.abc import Callable

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import ProviderInfoCatalog
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


def test_providers_empty_registry_returns_empty_list() -> None:
    assert rr.providers() == []


def test_providers_sorted_independent_of_registration_order(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider"))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider"))

    assert rr.providers() == ["a_provider", "z_provider"]


def test_provider_returns_registered_placeholder_object(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
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


def test_provider_info_empty_registry_returns_schema_conformant_catalog_result() -> None:
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
    assert result.data.schema == ProviderInfoCatalog.polars_schema
    assert result.data.height == 0


def test_provider_info_aggregates_registered_provider_rows(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
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
        schema=ProviderInfoCatalog.polars_schema,
    )

    result = rr.provider_info()

    pl_testing.assert_frame_equal(result.data, expected)
    assert result.issues == ()
    assert result.provenance.source == "packaged"


def test_provider_lookup_malformed_id_is_membership_miss() -> None:
    with pytest.raises(UnknownProviderError):
        rr.provider("BAD-Provider")
