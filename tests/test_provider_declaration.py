"""provider manifest bootstrap : Manifest × Declarations → AtomicRegistryRegistration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers import registration
from rivretrieve._internal.providers.ca_eccc.config import config as bulk_config
from rivretrieve._internal.providers.no_nve import declaration as no_nve_declaration
from rivretrieve._internal.providers.registration import (
    BulkStore,
    CatalogueOnly,
    CredentialHeaderBinding,
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
    declaration = ProviderDeclaration(tmp_path / "catalogue", "live")  # ty: ignore[invalid-argument-type]

    with pytest.raises(FatalContractError, match="Provider xx_test.*unrecognised observation kind.*live"):
        load_manifest(("xx_test",), declaration_loader=lambda _provider_id: declaration)


def test_live_stages_without_stage_contract_refuses_before_catalogue_loading(
    stub_packaged_catalogue_artifact,
    tmp_path: Path,
) -> None:
    declaration = ProviderDeclaration(tmp_path / "catalogue", LiveStages(stages=object()))  # ty: ignore[invalid-argument-type]
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
    operations[operation] = None  # ty: ignore[invalid-assignment]
    declaration = ProviderDeclaration(
        tmp_path / "catalogue",
        BulkStore(config=bulk_config, **operations),
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
    assert rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean")
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
        rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean")

    assert _registry.list_provider_ids() == []


def test_builtin_provider_declarations_state_their_required_credentials() -> None:
    declared = {item.provider_id: item.declaration for item in load_manifest(BUILTIN_PROVIDER_IDS)}

    assert declared["no_nve"].required_credentials == ("NVE_API_KEY",)
    assert declared["br_ana"].required_credentials == ("ANA_IDENTIFICADOR", "ANA_SENHA")
    assert all(
        declaration.required_credentials == ()
        for provider_id, declaration in declared.items()
        if provider_id not in {"no_nve", "br_ana"}
    )


def test_environment_template_matches_declared_credentials() -> None:
    template = Path(__file__).parents[1] / ".env.example"
    assignments = {
        line.partition("=")[0]: line
        for line in template.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    declared = load_manifest(BUILTIN_PROVIDER_IDS)
    expected = {variable: item.provider_id for item in declared for variable in item.declaration.required_credentials}

    assert set(assignments) == set(expected)
    for variable, provider_id in expected.items():
        line = assignments[variable]
        assert provider_id in line
        assert "https://" in line


@pytest.mark.parametrize(
    "credentials",
    [
        ["TOKEN"],
        ("",),
        ("lowercase",),
        ("TOKEN", "TOKEN"),
        (1,),
    ],
)
def test_malformed_required_credentials_refuse_before_catalogue_loading(
    credentials: object,
    tmp_path: Path,
) -> None:
    declaration = ProviderDeclaration(
        tmp_path / "catalogue",
        CatalogueOnly(),
        required_credentials=cast("tuple[str, ...]", credentials),
    )

    with pytest.raises(FatalContractError, match="Provider xx_test has malformed required credentials"):
        load_manifest(("xx_test",), declaration_loader=lambda _provider_id: declaration)


def test_live_credentials_require_exact_header_bindings(tmp_path: Path) -> None:
    declaration = ProviderDeclaration(
        tmp_path / "catalogue",
        LiveStages(stages=cast("LiveStages", no_nve_declaration.declaration.observations).stages),
        required_credentials=("TOKEN",),
    )

    with pytest.raises(FatalContractError, match="live credential bindings do not match"):
        load_manifest(("xx_test",), declaration_loader=lambda _provider_id: declaration)


def test_credential_header_binding_rejects_undeclared_variable(tmp_path: Path) -> None:
    declaration = ProviderDeclaration(
        tmp_path / "catalogue",
        CatalogueOnly(),
        credential_headers=(CredentialHeaderBinding("TOKEN", "X-Token", ("https://example.test",)),),
    )

    with pytest.raises(FatalContractError, match="references undeclared variable 'TOKEN'"):
        load_manifest(("xx_test",), declaration_loader=lambda _provider_id: declaration)


def _exchange_declaration(tmp_path: Path) -> ProviderDeclaration:
    from rivretrieve._internal.authentication import ExchangeSpec

    return ProviderDeclaration(
        tmp_path / "catalogue",
        no_nve_declaration.declaration.observations,
        required_credentials=("IDENTIFIER", "PASSWORD"),
        credential_exchange=registration.CredentialExchangeBinding(
            ExchangeSpec.ana(),
            (
                CredentialHeaderBinding("IDENTIFIER", "identificador", ("https://www.ana.gov.br",)),
                CredentialHeaderBinding("PASSWORD", "senha", ("https://www.ana.gov.br",)),
            ),
        ),
    )


def test_exchange_declaration_propagates_to_registry(tmp_path, stub_packaged_catalogue_artifact):
    declaration = _exchange_declaration(tmp_path)
    registry = ProviderRegistry()
    register_manifest(
        registry,
        ("xx_test",),
        declaration_loader=lambda _: declaration,
        artifact_loader=lambda _: stub_packaged_catalogue_artifact("xx_test"),
    )
    assert registry.get("xx_test").credential_exchange == declaration.credential_exchange
    assert registry.get("xx_test").credential_headers == ()


@pytest.mark.parametrize(
    "defect",
    [
        "mixed",
        "catalogue",
        "spec",
        "missing",
        "extra",
        "duplicate_variable",
        "duplicate_header",
        "origin",
        "extra_origin",
        "bindings",
        "binding",
    ],
)
def test_exchange_declaration_refuses_invalid_contract(tmp_path, defect):
    declaration = _exchange_declaration(tmp_path)
    exchange = declaration.credential_exchange
    assert exchange is not None
    bindings = exchange.credential_headers
    if defect == "mixed":
        declaration = replace(declaration, credential_headers=bindings)
    elif defect == "catalogue":
        declaration = replace(declaration, observations=CatalogueOnly())
    elif defect == "spec":
        exchange = replace(exchange, spec="ana")
    elif defect == "missing":
        exchange = replace(exchange, credential_headers=bindings[:1])
    elif defect == "extra":
        exchange = replace(exchange, credential_headers=(*bindings, replace(bindings[0], variable="OTHER")))
    elif defect == "duplicate_variable":
        exchange = replace(exchange, credential_headers=(bindings[0], bindings[0]))
    elif defect == "duplicate_header":
        exchange = replace(exchange, credential_headers=(bindings[0], replace(bindings[1], header="IDENTIFICADOR")))
    elif defect == "origin":
        exchange = replace(
            exchange, credential_headers=(replace(bindings[0], origins=("https://other.test",)), bindings[1])
        )
    elif defect == "extra_origin":
        exchange = replace(
            exchange,
            credential_headers=(
                replace(bindings[0], origins=("https://www.ana.gov.br", "https://other.test")),
                bindings[1],
            ),
        )
    elif defect == "bindings":
        exchange = replace(exchange, credential_headers=list(bindings))
    elif defect == "binding":
        exchange = replace(exchange, credential_headers=("bad",))
    declaration = replace(declaration, credential_exchange=exchange)
    with pytest.raises(FatalContractError):
        load_manifest(("xx_test",), declaration_loader=lambda _: declaration)
