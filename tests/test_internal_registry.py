from __future__ import annotations

from collections.abc import Callable

import pytest

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.issues import FatalContractError, IssuePolicyError
from rivretrieve._internal.registry import ProviderRegistry, UnknownProviderError, _ProviderHandle


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
