from __future__ import annotations

from collections.abc import Callable

import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.registry import UnknownProviderError, _registry
from rivretrieve._internal.results import CatalogResult


def test_m1_exit_criteria_smoke_sweep(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    z_artifact = stub_packaged_catalogue_artifact("z_provider")
    a_artifact = stub_packaged_catalogue_artifact("a_provider")
    _registry.register("z_provider", z_artifact)
    _registry.register("a_provider", a_artifact)

    assert z_artifact.provider_info["provider_id"] == "z_provider"
    assert rr.providers() == ["a_provider", "z_provider"]
    with pytest.raises(UnknownProviderError):
        rr.provider("missing")

    result = rr.provider_info()

    assert isinstance(result, CatalogResult)
    assert result.issues == ()
    assert result.provenance.source == "packaged"
    assert result.data["provider_id"].to_list() == ["a_provider", "z_provider"]
