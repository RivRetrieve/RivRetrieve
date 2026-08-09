from __future__ import annotations

from collections.abc import Callable

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.registry import UnknownProviderError, _registry


def test_m1_exit_criteria_smoke_sweep(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    _registry.clear()
    z_artifact = stub_packaged_catalogue_artifact("z_provider")
    a_artifact = stub_packaged_catalogue_artifact("a_provider")
    _registry.register("z_provider", z_artifact)
    _registry.register("a_provider", a_artifact)

    assert z_artifact.provider_info["provider_id"] == "z_provider"
    assert rr.providers() == ["a_provider", "z_provider"]
    with pytest.raises(UnknownProviderError):
        rr.products(provider="missing")
    assert rr.products() == ["level"]
