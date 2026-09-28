"""provider architecture checks : RepositoryTree × ToolConfig → ContractViolations."""

from __future__ import annotations

import ast
import tomllib
from importlib import import_module
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers.registration import BulkStore, CatalogueOnly, LiveStages, load_manifest
from rivretrieve._internal.registry import _registry

ROOT = Path(__file__).parents[1]
PROVIDERS_ROOT = ROOT / "src" / "rivretrieve" / "_internal" / "providers"
RATIFIED_RUNTIME_ROLES = {
    "__init__.py",
    "bulk.py",
    "config.py",
    "declaration.py",
    "fetch.py",
    "issue_codes.py",
    "metadata.py",
    "module.py",
    "origins.py",
    "parse.py",
    "series.py",  # Source identity and independently established physical facts.
}
CACHE_HTTP_CARVE_OUTS: dict[str, set[str]] = {}
OBSERVATION_ADAPTER_ROLES = {
    "bulk.py",
    "config.py",
    "fetch.py",
    "parse.py",
    "transform.py",
    "convert.py",
    "assemble.py",
}
CONTRIBUTORS = {
    provider_id: ("Nicolas Lazaro" if provider_id == "ch_foen" else "Thiago von Däniken")
    for provider_id in BUILTIN_PROVIDER_IDS
}


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


def _is_provider_owned_data_operation(name: str) -> bool:
    tokens = name.lstrip("_").split("_")
    operation_targets = {
        "transform": {"data", "observation", "observations", "result", "results", "row", "rows", "value", "values"},
        "convert": {
            "data",
            "observation",
            "observations",
            "result",
            "results",
            "row",
            "rows",
            "time",
            "timestamp",
            "timezone",
            "unit",
            "units",
            "value",
            "values",
            "zone",
        },
        "assemble": {"data", "observation", "observations", "result", "results", "row", "rows"},
    }
    return bool(tokens and tokens[0] in operation_targets and set(tokens[1:]) & operation_targets[tokens[0]])


def _engine_owned_operations_in_tree(tree: ast.Module, relative_path: Path) -> list[str]:
    violations = []
    forbidden_function_names = {
        "transform",
        "convert",
        "assemble",
        "_filter_date_range",
        "filter_date_range",
    }
    environment_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "os"
        for alias in node.names
        if alias.name in {"environ", "getenv"}
    }
    os_module_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "os"
    }
    fetch_window_factory_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (
            node.module == "rivretrieve._internal.engine"
            or (node.level > 0 and node.module is not None and node.module.split(".")[-1] == "engine")
        )
        for alias in node.names
        if alias.name == "_make_fetch_window"
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name in forbidden_function_names or _is_provider_owned_data_operation(node.name)
        ):
            violations.append(f"{relative_path}:{node.lineno}:provider-owned {node.name}")
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                node.module in {"rivretrieve._internal.assembly", "rivretrieve._internal.conversion"}
                or (node.level > 0 and node.module.split(".")[-1] in {"assembly", "conversion"})
            )
        ) or (
            isinstance(node, ast.Import)
            and any(
                alias.name in {"rivretrieve._internal.assembly", "rivretrieve._internal.conversion"}
                for alias in node.names
            )
        ):
            violations.append(f"{relative_path}:{node.lineno}:engine-owned module import")
        elif (
            isinstance(node, ast.Import)
            and any(alias.name.split(".")[0] in {"dotenv", "backoff", "tenacity"} for alias in node.names)
            or isinstance(node, ast.ImportFrom)
            and node.module in {"dotenv", "backoff", "tenacity"}
        ):
            violations.append(f"{relative_path}:{node.lineno}:hidden configuration or retry import")
        elif isinstance(node, ast.Subscript | ast.Call) and (
            any(
                isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and child.value.id in os_module_names
                and child.attr in {"getenv", "environ"}
                for child in ast.walk(node)
            )
            or any(isinstance(child, ast.Name) and child.id in environment_names for child in ast.walk(node))
        ):
            violations.append(f"{relative_path}:{node.lineno}:hidden environment read")
        elif isinstance(node, ast.ImportFrom) and (
            node.module == "rivretrieve._internal.engine"
            or (node.level > 0 and node.module is not None and node.module.split(".")[-1] == "engine")
        ):
            for alias in node.names:
                if alias.name == "_make_fetch_window":
                    violations.append(f"{relative_path}:{node.lineno}:_make_fetch_window import")
        elif isinstance(node, ast.Call):
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            if name in {
                "ZoneInfo",
                "astimezone",
                "convert_time_zone",
                "replace_time_zone",
                "tz_convert",
                "tz_localize",
                "localize",
                "clip",
                "sleep",
                "backoff",
                "retry",
                "_make_fetch_window",
                *fetch_window_factory_names,
            }:
                operation = "_make_fetch_window" if name in fetch_window_factory_names else name
                violations.append(f"{relative_path}:{node.lineno}:{operation}")
            if name == "replace" and any(keyword.arg == "tzinfo" for keyword in node.keywords):
                violations.append(f"{relative_path}:{node.lineno}:replace(tzinfo=...)")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            numeric_literals = {
                value
                for operand in (node.left, node.right)
                if isinstance(operand, ast.Constant) and isinstance((value := operand.value), (int, float))
            }
            if numeric_literals & {1000, 0.001}:
                violations.append(f"{relative_path}:{node.lineno}:unit arithmetic")
        elif isinstance(node, ast.Compare):
            window_boundaries = {
                child.attr
                for child in ast.walk(node)
                if isinstance(child, ast.Attribute)
                and child.attr in {"start", "end"}
                and isinstance(child.value, ast.Name)
                and any(marker in child.value.id.lower() for marker in ("request", "window"))
            }
            if window_boundaries:
                violations.append(f"{relative_path}:{node.lineno}:requested-window comparison")
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            target_names = {child.id.lower() for child in ast.walk(node.target) if isinstance(child, ast.Name)}
            if target_names & {"attempt", "attempts", "retry", "retries"}:
                violations.append(f"{relative_path}:{node.lineno}:retry loop")
    return violations


def _engine_owned_operations(path: Path) -> list[str]:
    return _engine_owned_operations_in_tree(_tree(path), path.relative_to(PROVIDERS_ROOT))


def test_engine_owned_operations_rejects_fetch_window_factory_imports_and_calls() -> None:
    source = """from rivretrieve._internal.engine import _make_fetch_window
from rivretrieve._internal import engine

_make_fetch_window(start, end)
engine._make_fetch_window(start, end)
"""

    assert _engine_owned_operations_in_tree(ast.parse(source), Path("adversarial/fetch.py")) == [
        "adversarial/fetch.py:1:_make_fetch_window import",
        "adversarial/fetch.py:4:_make_fetch_window",
        "adversarial/fetch.py:5:_make_fetch_window",
    ]


def test_engine_owned_operations_reject_provider_transforms_and_hidden_environment_reads() -> None:
    source = """import os as operating_system
from rivretrieve._internal.conversion import convert

def transform(rows):
    return convert(rows)

secret = operating_system.environ["TOKEN"]
"""

    assert _engine_owned_operations_in_tree(ast.parse(source), Path("adversarial/parse.py")) == [
        "adversarial/parse.py:2:engine-owned module import",
        "adversarial/parse.py:4:provider-owned transform",
        "adversarial/parse.py:7:hidden environment read",
    ]


def test_engine_owned_operations_allow_provider_request_builders() -> None:
    source = """def assemble_request(station, window):
    return {"station": station, "start": window.start}
"""

    assert _engine_owned_operations_in_tree(ast.parse(source), Path("adversarial/fetch.py")) == []
    assert _is_provider_owned_data_operation("assemble_rows") is True
    assert _is_provider_owned_data_operation("convert_units") is True
    assert _is_provider_owned_data_operation("transform_observations") is True


def test_runtime_provider_inventory_has_only_ratified_roles() -> None:
    runtime_files = _runtime_provider_files()
    provider_directories = {path.parent.name for path in runtime_files}

    assert provider_directories == set(BUILTIN_PROVIDER_IDS)
    assert {path.name for path in runtime_files} <= RATIFIED_RUNTIME_ROLES
    assert {path.parent.name for path in runtime_files if path.name == "parser.py"} == set()

    for item in load_manifest(BUILTIN_PROVIDER_IDS):
        provider_files = {path.name for path in runtime_files if path.parent.name == item.provider_id}
        adapter_files = provider_files & OBSERVATION_ADAPTER_ROLES
        kind = item.declaration.observations
        if isinstance(kind, LiveStages):
            assert adapter_files == {"config.py", "fetch.py", "parse.py"}
        elif isinstance(kind, BulkStore):
            assert adapter_files == {"bulk.py", "config.py"}
        else:
            assert isinstance(kind, CatalogueOnly)
            assert adapter_files == set()
        assert "declaration.py" in provider_files


def test_observation_adapter_module_docstrings_preserve_contributor_attribution() -> None:
    for item in load_manifest(BUILTIN_PROVIDER_IDS):
        kind = item.declaration.observations
        if isinstance(kind, LiveStages):
            filenames = ("config.py", "fetch.py", "parse.py")
        elif isinstance(kind, BulkStore):
            filenames = ("bulk.py", "config.py")
        else:
            continue
        for filename in filenames:
            docstring = ast.get_docstring(_tree(PROVIDERS_ROOT / item.provider_id / filename), clean=False)
            assert docstring is not None
            assert f"Contributed by: {CONTRIBUTORS[item.provider_id]}" in docstring


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


def test_runtime_response_models_are_validated_at_the_provider_boundary() -> None:
    for path in _runtime_provider_files():
        tree = _tree(path)
        models = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and any(isinstance(base, ast.Name) and base.id == "BaseModel" for base in node.bases)
        }
        validated = {
            node.func.value.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"model_validate", "model_validate_json"}
            and isinstance(node.func.value, ast.Name)
        }
        pending = list(validated & models.keys())
        reached = set()
        while pending:
            name = pending.pop()
            if name in reached:
                continue
            reached.add(name)
            pending.extend(
                node.id for node in ast.walk(models[name]) if isinstance(node, ast.Name) and node.id in models
            )
        assert set(models) <= reached, path.relative_to(PROVIDERS_ROOT)


def test_no_provider_module() -> None:
    """Catalogue access belongs to the shared reader, not provider facades."""
    assert list(PROVIDERS_ROOT.glob("*/module.py")) == []


def test_runtime_provider_code_has_no_engine_owned_operations() -> None:
    violations = [violation for path in _runtime_provider_files() for violation in _engine_owned_operations(path)]
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


def test_bulk_modules_do_not_expose_legacy_cache_operations() -> None:
    bulk_provider_ids = (
        item.provider_id
        for item in load_manifest(BUILTIN_PROVIDER_IDS)
        if isinstance(item.declaration.observations, BulkStore)
    )
    for provider_id in bulk_provider_ids:
        module = import_module(f"rivretrieve._internal.providers.{provider_id}.bulk")
        assert not hasattr(module, "cache_status")
        assert not hasattr(module, "refresh_cache")


def test_repository_configuration_enforces_transport_boundary() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    ruff_lint = config["tool"]["ruff"]["lint"]
    assert "TID251" in ruff_lint["extend-select"]
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


def test_source_failure_isolation_exists_once_in_the_engine() -> None:
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

    driver = _tree(ROOT / "src" / "rivretrieve" / "_internal" / "driver.py")
    isolation_points = [
        node
        for node in ast.walk(driver)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and any(
            isinstance(child, ast.Name) and child.id in {"TransportFailure", "CredentialExchangeError"}
            for child in ast.walk(node.type)
        )
    ]
    assert len(isolation_points) == 1
    caught = isolation_points[0].type
    assert isinstance(caught, ast.Tuple)
    assert tuple(child.id for child in caught.elts if isinstance(child, ast.Name)) == (
        "TransportFailure",
        "CredentialExchangeError",
    )


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
