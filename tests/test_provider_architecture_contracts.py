"""provider architecture checks : RepositoryTree × ToolConfig → ContractViolations."""

from __future__ import annotations

import ast
import tomllib
from importlib import import_module
from pathlib import Path

import rivretrieve as rr
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers.registration import BulkStore, CatalogueOnly, LiveStages, load_manifest
from rivretrieve._internal.registry import _registry

ROOT = Path(__file__).parents[1]
PROVIDERS_ROOT = ROOT / "src" / "rivretrieve" / "_internal" / "providers"
REFERENCE_ROOT = ROOT / "reference" / "legacy_observations"
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


def _runtime_provider_files() -> list[Path]:
    return sorted(path for path in PROVIDERS_ROOT.glob("*/*.py") if path.name != "generate_catalogue.py")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _direct_http_imports(path: Path) -> set[str]:
    imports = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
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


def test_provider_runtime_contains_no_pydantic_catalogue_models() -> None:
    model_names = {
        node.name
        for path in PROVIDERS_ROOT.glob("*/*.py")
        for node in _tree(path).body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "BaseModel" for base in node.bases)
    }
    assert model_names == set()


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
    assert set(rr.providers()) == set(BUILTIN_PROVIDER_IDS)
    records = {str(record.provider_id): record.handle for record in _registry.iter_records()}

    for item in declared:
        handle = records[item.provider_id]
        kind = item.declaration.observations
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


def test_legacy_reference_tree_is_inert_by_repository_configuration() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    reference_path = "reference/legacy_observations/"
    ruff_lint = config["tool"]["ruff"]["lint"]
    assert REFERENCE_ROOT.is_dir()
    assert config["tool"]["ruff"]["extend-exclude"] == [reference_path]
    assert "TID251" in ruff_lint["extend-select"]
    assert set(ruff_lint["flake8-tidy-imports"]["banned-api"]) == {"httpx", "requests", "urllib"}
    assert ruff_lint["per-file-ignores"] == {
        "src/rivretrieve/_internal/transport.py": ["TID251"],
        "src/rivretrieve/_internal/providers/*/generate_catalogue.py": ["TID251"],
        "tests/**": ["TID251"],
    }
    assert config["tool"]["ty"]["src"]["exclude"] == [reference_path]
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]


def test_provider_tests_have_no_literal_builtin_provider_census() -> None:
    violations: list[str] = []
    for test_path in sorted((ROOT / "tests").rglob("*.py")):
        for node in ast.walk(_tree(test_path)):
            if not isinstance(node, ast.Compare):
                continue
            expressions = (node.left, *node.comparators)
            has_literal = any(
                isinstance(expression, ast.Constant) and isinstance(expression.value, int) for expression in expressions
            )
            has_provider_count = any(
                isinstance(expression, ast.Call)
                and isinstance(expression.func, ast.Name)
                and expression.func.id == "len"
                and len(expression.args) == 1
                and isinstance(expression.args[0], ast.Call)
                and isinstance(expression.args[0].func, ast.Attribute)
                and isinstance(expression.args[0].func.value, ast.Name)
                and expression.args[0].func.value.id == "rr"
                and expression.args[0].func.attr == "providers"
                for expression in expressions
            )
            if has_literal and has_provider_count:
                violations.append(f"{test_path.relative_to(ROOT)}:{node.lineno}")

    assert violations == []


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
