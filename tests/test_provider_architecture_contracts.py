"""provider architecture checks : RepositoryTree × ToolConfig → ContractViolations."""

from __future__ import annotations

import ast
import tomllib
from collections import Counter
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
_BASE_RUNTIME_FILE_COUNTS = Counter(
    {
        "__init__.py": 13,
        "metadata.py": 9,
        "origins.py": 5,
        "issue_codes.py": 9,
        "config.py": 3,
        "fetch.py": 1,
        "parse.py": 1,
        "bulk.py": 2,
    }
)
# Providers migrated to declared origins since the base inventory above. Each one adds an
# `origins.py` and removes a `metadata.py`. They are named individually, and one per line, so that
# two branches enrolling DIFFERENT providers merge as a union. An anonymous `+= 1` on both sides is
# byte-identical text, so git deduplicates it and the count silently under-reports by one for every
# enrolment beyond the first -- which is exactly what happened merging Thailand into a main that
# already carried Bosnia and South Africa.
_MIGRATED_SINCE_BASE = (
    "ba_fhmzbih",
    "fr_hubeau",
    "jp_mlit",
    "pl_imgw",
    "th_thaiwater",
    "za_dws",
)
_METADATA_REMOVED_AFTER_SCHEMA_NARROWING = (
    "br_ana",
    "lt_lhmt",
    "no_nve",
)
RUNTIME_FILE_COUNTS = _BASE_RUNTIME_FILE_COUNTS.copy()
RUNTIME_FILE_COUNTS["declaration.py"] = len(BUILTIN_PROVIDER_IDS)
RUNTIME_FILE_COUNTS["origins.py"] += len(_MIGRATED_SINCE_BASE)
RUNTIME_FILE_COUNTS["metadata.py"] -= len(_MIGRATED_SINCE_BASE) + len(_METADATA_REMOVED_AFTER_SCHEMA_NARROWING)


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


def _engine_owned_operations_in_tree(tree: ast.Module, relative_path: Path) -> list[str]:
    violations = []
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
        if isinstance(node, ast.ImportFrom) and (
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


def test_runtime_provider_inventory_has_only_ratified_roles() -> None:
    runtime_files = _runtime_provider_files()
    provider_directories = {path.parent.name for path in runtime_files}

    assert Counter(path.name for path in runtime_files) == RUNTIME_FILE_COUNTS
    assert provider_directories == set(BUILTIN_PROVIDER_IDS)
    assert {path.name for path in runtime_files} <= RATIFIED_RUNTIME_ROLES
    assert {path.parent.name for path in runtime_files if path.name == "parser.py"} == set()
    for provider_id in BUILTIN_PROVIDER_IDS:
        provider_files = {path.name for path in runtime_files if path.parent.name == provider_id}
        assert "declaration.py" in provider_files


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
        if path.is_relative_to(PROVIDERS_ROOT):
            continue
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Compare):
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
