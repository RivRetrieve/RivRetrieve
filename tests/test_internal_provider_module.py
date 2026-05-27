from __future__ import annotations

import importlib
from types import ModuleType

import pytest

from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.registry import ProviderRegistry, _registry
from tests._stubs import stub_provider
from tests.conftest import RegisteredStub


def test_stub_provider_module_has_provider_module_attributes() -> None:
    assert isinstance(stub_provider, ModuleType)
    assert isinstance(stub_provider, ProviderModule)


def test_stub_provider_info_matches_registered_handle_info(registered_stub: RegisteredStub) -> None:
    assert stub_provider.info() == registered_stub.handle.info()


def test_stub_provider_registers_into_fresh_registry_only(registered_stub: RegisteredStub) -> None:
    assert registered_stub.registry.list_provider_ids() == ["stub_provider"]
    assert registered_stub.registry.get("stub_provider") is registered_stub.handle
    assert _registry.list_provider_ids() == []


def test_stub_provider_does_not_register_at_import_time(fresh_registry: ProviderRegistry) -> None:
    importlib.import_module("tests._stubs.stub_provider")

    assert fresh_registry.list_provider_ids() == []
    assert _registry.list_provider_ids() == []


@pytest.mark.parametrize("method_name", ["products", "stations", "station_products"])
def test_stub_catalogue_functions_remain_explicitly_unimplemented(method_name: str) -> None:
    method = getattr(stub_provider, method_name)

    with pytest.raises(NotImplementedError, match="deferred to M2 step 02"):
        method()
