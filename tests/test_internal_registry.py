from __future__ import annotations

from collections.abc import Callable

import pytest

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.issues import FatalContractError, IssuePolicyError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.provider_info import ProviderInfo, ProviderInfoValidationError
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
        provider_info={**artifact.provider_info, "metadata": "[]"},
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
