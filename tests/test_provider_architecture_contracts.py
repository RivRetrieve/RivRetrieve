"""provider architecture checks : RepositoryTree × ToolConfig → ContractViolations."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers.registration import BulkStore, CatalogueOnly, LiveStages, load_manifest
from rivretrieve._internal.registry import _registry

ROOT = Path(__file__).parents[1]
PROVIDERS_ROOT = ROOT / "src" / "rivretrieve" / "_internal" / "providers"
CACHE_HTTP_CARVE_OUTS: dict[str, set[str]] = {}


MAINTAINER_ROLES = {
    "generate_catalogue.py",
    "capture.py",
    "inventory.py",
    "catalogue_series.py",  # Build-time source-description evidence; never runtime discovery.
}


def _runtime_provider_files() -> list[Path]:
    return sorted(path for path in PROVIDERS_ROOT.glob("*/*.py") if path.name not in MAINTAINER_ROLES)


def test_runtime_declarations_transitively_do_not_import_maintainer_roles() -> None:
    for provider in BUILTIN_PROVIDER_IDS:
        prefix = f"rivretrieve._internal.providers.{provider}."
        pending = ["declaration"]
        seen: set[str] = set()
        while pending:
            module = pending.pop()
            if module in seen:
                continue
            seen.add(module)
            assert f"{module}.py" not in MAINTAINER_ROLES
            path = PROVIDERS_ROOT / provider / f"{module}.py"
            if not path.is_file():
                continue
            for node in ast.walk(_tree(path)):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                elif isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                assert not set(names) & {
                    "rivretrieve._internal.catalogues.schemas",
                    "rivretrieve._internal.catalogues.native",
                    "rivretrieve._internal.catalogues.publication",
                    "rivretrieve._internal.catalogue_origins",
                }, (provider, module, names)
                pending.extend(name.removeprefix(prefix) for name in names if name.startswith(prefix))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _direct_http_imports(path: Path) -> set[str]:
    imports = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names if alias.name != "urllib.parse")
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.module != "urllib.parse":
            imports.add(node.module.split(".")[0])
    return imports & {"httpx", "requests", "urllib"}


def test_provider_runtime_contains_no_catalogue_build_models() -> None:
    # Response schemas belong at provider boundaries. Catalogue authoring schemas
    # and build operations do not belong in those runtime modules.
    forbidden_modules = {
        "rivretrieve._internal.catalogues.schemas",
        "rivretrieve._internal.catalogues.native",
        "rivretrieve._internal.catalogues.publication",
        "rivretrieve._internal.catalogue_origins",
    }
    violations = []
    for path in _runtime_provider_files():
        if path.name == "origins.py":
            continue  # Maintainer evidence declarations are checked transitively above.
        for node in ast.walk(_tree(path)):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            violations.extend(
                (str(path.relative_to(PROVIDERS_ROOT)), name) for name in names if name in forbidden_modules
            )
    assert violations == []


def test_runtime_direct_http_imports_are_only_declared_cache_carve_outs() -> None:
    actual = {
        str(path.relative_to(PROVIDERS_ROOT)): imports
        for path in _runtime_provider_files()
        if (imports := _direct_http_imports(path))
    }
    assert actual == CACHE_HTTP_CARVE_OUTS


def test_registry_matches_declared_provider_kinds() -> None:
    declared = load_manifest(BUILTIN_PROVIDER_IDS)
    assert set(rr.providers().get_column("provider_id").to_list()) == set(BUILTIN_PROVIDER_IDS)
    records = {str(record.provider_id): record.handle for record in _registry.iter_records()}

    for item in declared:
        handle = records[item.provider_id]
        kind = item.declaration.observations
        assert handle.required_credentials == item.declaration.required_credentials
        assert handle.credential_headers == item.declaration.credential_headers
        if isinstance(kind, LiveStages):
            assert handle._module is None
            assert handle._stages is kind.stages
            assert handle._bulk_operations is None
        elif isinstance(kind, BulkStore):
            assert handle._module is None
            assert handle._stages is None
            assert handle._store_config is kind.config
            assert handle._store_root is not None
            assert handle._bulk_operations is kind
        elif isinstance(kind, CatalogueOnly):
            assert handle._module is None
            assert handle._stages is None
            assert handle._store_config is None
            assert handle._store_root is None
            assert handle._bulk_operations is None
        else:
            raise AssertionError(f"unreachable provider kind for {item.provider_id}")


def test_repository_configuration_enforces_transport_boundary() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    ruff_lint = config["tool"]["ruff"]["lint"]
    selected_rules = {*ruff_lint.get("select", ()), *ruff_lint.get("extend-select", ())}
    assert "TID251" in selected_rules
    assert set(ruff_lint["flake8-tidy-imports"]["banned-api"]) == {"httpx", "requests", "urllib"}
    assert ruff_lint["per-file-ignores"] == {
        "src/rivretrieve/_internal/transport.py": ["TID251"],
        "src/rivretrieve/_internal/providers/*/generate_catalogue.py": ["TID251"],
        "tests/**": ["TID251"],
    }
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]


def test_runtime_engine_has_no_provider_id_switch() -> None:
    """Runtime engine modules must dispatch on declarations, never provider ids."""
    provider_ids = set(BUILTIN_PROVIDER_IDS)
    violations: list[str] = []
    runtime_root = ROOT / "src" / "rivretrieve"
    for path in sorted(runtime_root.rglob("*.py")):
        if any(path.is_relative_to(PROVIDERS_ROOT / provider_id) for provider_id in BUILTIN_PROVIDER_IDS):
            continue
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Compare | ast.Match):
                continue
            literals = {
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            }
            switched = sorted(literals & provider_ids)
            if switched:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{','.join(switched)}")
    assert violations == []


def test_provider_fetch_delegates_transport_failures_to_engine() -> None:
    provider_violations: list[str] = []
    for path in PROVIDERS_ROOT.glob("*/fetch.py"):
        tree = _tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is not None:
                caught_failures = {
                    child.id
                    for child in ast.walk(node.type)
                    if isinstance(child, ast.Name) and child.id in {"TransportFailure", "CredentialExchangeError"}
                }
                if caught_failures:
                    provider_violations.append(f"{path.parent.name}:{node.lineno}:{sorted(caught_failures)}")
            if isinstance(node, ast.Compare) and any(
                isinstance(child, ast.Attribute) and child.attr == "status_code" for child in ast.walk(node)
            ):
                provider_violations.append(f"{path.parent.name}:{node.lineno}:status branch")
    assert provider_violations == []


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("from urllib.parse import urlsplit, parse_qsl", set()),
        ("import urllib.parse", set()),
        ("from urllib.request import urlopen", {"urllib"}),
        ("import urllib.request", {"urllib"}),
        ("import urllib", {"urllib"}),
    ],
)
def test_pure_url_parsing_does_not_grant_provider_network_access(tmp_path, statement, expected):
    module = tmp_path / "provider.py"
    module.write_text(statement)
    assert _direct_http_imports(module) == expected
