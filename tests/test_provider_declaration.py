"""provider manifest bootstrap : Manifest × Declarations → AtomicRegistryRegistration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers import registration
from rivretrieve._internal.providers.ca_eccc.config import config as bulk_config
from rivretrieve._internal.providers.registration import (
    BulkStore,
    CatalogueOnly,
    LiveStages,
    ProviderDeclaration,
    load_manifest,
    register_manifest,
)
from rivretrieve._internal.providers.za_dws import declaration as za_dws_declaration
from rivretrieve._internal.registry import ProviderRegistry, _registry


def test_duplicate_id_refuses_before_loading_a_declaration() -> None:
    calls: list[str] = []

    with pytest.raises(FatalContractError, match="duplicate provider id: xx_test"):
        load_manifest(("xx_test", "xx_test"), declaration_loader=lambda provider_id: calls.append(provider_id))

    assert calls == []


def test_mismatched_identity_names_directory_and_catalogue(
    stub_packaged_catalogue_artifact,
    tmp_path: Path,
) -> None:
    declaration = ProviderDeclaration(tmp_path / "catalogue", CatalogueOnly())
    artifact = stub_packaged_catalogue_artifact("xx_other")

    with pytest.raises(FatalContractError, match="directory id xx_test.*provider_id xx_other"):
        register_manifest(
            ProviderRegistry(),
            ("xx_test",),
            declaration_loader=lambda _provider_id: declaration,
            artifact_loader=lambda _path: artifact,
        )


def test_malformed_kind_names_provider_and_unrecognised_value(tmp_path: Path) -> None:
    declaration = ProviderDeclaration(tmp_path / "catalogue", "live")  # type: ignore[arg-type]

    with pytest.raises(FatalContractError, match="Provider xx_test.*unrecognised observation kind.*live"):
        load_manifest(("xx_test",), declaration_loader=lambda _provider_id: declaration)


def test_live_stages_without_stage_contract_refuses_before_catalogue_loading(
    stub_packaged_catalogue_artifact,
    tmp_path: Path,
) -> None:
    declaration = ProviderDeclaration(tmp_path / "catalogue", LiveStages(stages=object()))  # type: ignore[arg-type]
    registry = ProviderRegistry()
    catalogue_loads: list[Path] = []

    with pytest.raises(FatalContractError, match="Provider xx_test.*malformed LiveStages.*stages"):
        register_manifest(
            registry,
            ("xx_test",),
            declaration_loader=lambda _provider_id: declaration,
            artifact_loader=lambda path: catalogue_loads.append(path) or stub_packaged_catalogue_artifact("xx_test"),
        )

    assert catalogue_loads == []
    assert registry.list_provider_ids() == []


@pytest.mark.parametrize("operation", ["download", "compile"])
def test_bulk_store_requires_callable_operations_before_catalogue_loading(
    operation: str,
    stub_packaged_catalogue_artifact,
    tmp_path: Path,
) -> None:
    operations = {
        "download": lambda request: request,
        "compile": lambda request: request,
    }
    operations[operation] = None  # type: ignore[assignment]
    declaration = ProviderDeclaration(
        tmp_path / "catalogue",
        BulkStore(config=bulk_config, **operations),  # type: ignore[arg-type]
    )
    registry = ProviderRegistry()
    catalogue_loads: list[Path] = []

    with pytest.raises(
        FatalContractError,
        match=rf"Provider xx_test.*malformed BulkStore.*{operation}",
    ):
        register_manifest(
            registry,
            ("xx_test",),
            declaration_loader=lambda _provider_id: declaration,
            artifact_loader=lambda path: catalogue_loads.append(path) or stub_packaged_catalogue_artifact("xx_test"),
        )

    assert catalogue_loads == []
    assert registry.list_provider_ids() == []


def test_default_registration_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original = registration.register_manifest

    def counted_register_manifest(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(registration, "register_manifest", counted_register_manifest)

    assert len(rr.providers()) == len(BUILTIN_PROVIDER_IDS)
    assert rr.find(product="discharge_daily_mean")
    assert rr.products()
    assert calls == 1


def test_missing_catalogue_refuses_manifest_without_partial_registration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-catalogue"
    monkeypatch.setattr(
        za_dws_declaration,
        "declaration",
        replace(za_dws_declaration.declaration, catalogue=missing),
    )

    with pytest.raises(FatalContractError, match=rf"Provider za_dws catalogue {missing}.*does not exist"):
        rr.find(product="discharge_daily_mean")

    assert _registry.list_provider_ids() == []
