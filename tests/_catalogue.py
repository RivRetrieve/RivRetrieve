"""test catalogue access : ProviderDeclaration → CatalogueReader."""

from functools import lru_cache
from importlib import import_module
from pathlib import Path

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.providers.registration import ProviderDeclaration


def declaration(provider_id: str) -> ProviderDeclaration:
    """Return one built-in provider declaration."""
    value = import_module(f"rivretrieve._internal.providers.{provider_id}.declaration").declaration
    assert isinstance(value, ProviderDeclaration)
    return value


def catalogue_path(provider_id: str) -> Path:
    """Return one built-in provider's declared catalogue path."""
    return declaration(provider_id).catalogue


@lru_cache
def catalogue_reader(provider_id: str) -> CatalogueReader:
    """Load one built-in provider's declared catalogue through the shared reader."""
    artifact = load_packaged_catalogue_artifact(catalogue_path(provider_id), on_issue="raise")
    return CatalogueReader(artifact, ProviderId(provider_id))


def provider_info(provider_id: str) -> ProviderInfo:
    """Parse one built-in provider's packaged provider information."""
    return ProviderInfo.from_row(catalogue_reader(provider_id).artifact.provider_info)
