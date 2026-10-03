from __future__ import annotations

from types import ModuleType
from typing import get_protocol_members

from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.registry import _registry
from tests._stubs import stub_provider
from tests.conftest import RegisteredStub


def test_stub_provider_module_has_provider_module_attributes() -> None:
    assert isinstance(stub_provider, ModuleType)
    assert isinstance(stub_provider, ProviderModule)


def test_stub_provider_module_satisfies_expanded_provider_module_protocol() -> None:
    expected_members = {
        "info",
        "products",
        "stations",
        "station_products",
    }

    assert expected_members <= set(vars(stub_provider))
    assert isinstance(stub_provider, ProviderModule)


def test_provider_module_protocol_does_not_own_observation_dispatch() -> None:
    assert "observations" not in get_protocol_members(ProviderModule)
    assert get_protocol_members(ProviderModule) == frozenset(
        {
            "info",
            "products",
            "stations",
            "station_products",
        }
    )


def test_stub_provider_info_matches_registered_handle_info(registered_stub: RegisteredStub) -> None:
    assert stub_provider.info() == registered_stub.handle.info()


def test_stub_provider_registers_into_fresh_registry_only(registered_stub: RegisteredStub) -> None:
    assert registered_stub.registry.list_provider_ids() == ["stub_provider"]
    assert registered_stub.registry.get("stub_provider") is registered_stub.handle
    assert _registry.list_provider_ids() == []
