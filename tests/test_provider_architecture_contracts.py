"""provider architecture checks : RepositoryTree × ToolConfig → ContractViolations."""

from __future__ import annotations

import ast
import tomllib
from collections import Counter
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import rivretrieve as rr
from rivretrieve._internal.registry import _registry

ROOT = Path(__file__).parents[1]
PROVIDERS_ROOT = ROOT / "src" / "rivretrieve" / "_internal" / "providers"
REFERENCE_ROOT = ROOT / "reference" / "legacy_observations"
PROOF_PROVIDERS = {"ca_eccc", "usgs_nwis"}
CATALOGUE_ONLY_PROVIDERS = {
    "ba_fhmzbih",
    "br_ana",
    "ch_foen",
    "cz_chmi",
    "fr_hubeau",
    "jp_mlit",
    "lt_lhmt",
    "no_nve",
    "pl_imgw",
    "th_thaiwater",
    "za_dws",
}
CACHE_HTTP_CARVE_OUTS = {
    "ca_eccc/observation_client.py": {"requests"},
    "pl_imgw/observation_client.py": {"requests"},
}
RUNTIME_FILE_COUNTS = Counter(
    {
        "__init__.py": 13,
        "module.py": 13,
        "metadata.py": 8,
        "origins.py": 6,
        "issue_codes.py": 11,
        "config.py": 2,
        "fetch.py": 2,
        "parse.py": 2,
        "observation_client.py": 2,
        "parser.py": 1,
    }
)


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


def _engine_owned_operations(path: Path) -> list[str]:
    violations = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call):
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
            }:
                violations.append(f"{path.relative_to(PROVIDERS_ROOT)}:{node.lineno}:{name}")
            if name == "replace" and any(keyword.arg == "tzinfo" for keyword in node.keywords):
                violations.append(f"{path.relative_to(PROVIDERS_ROOT)}:{node.lineno}:replace(tzinfo=...)")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            numeric_literals = {
                value
                for operand in (node.left, node.right)
                if isinstance(operand, ast.Constant) and isinstance((value := operand.value), (int, float))
            }
            if numeric_literals & {1000, 0.001}:
                violations.append(f"{path.relative_to(PROVIDERS_ROOT)}:{node.lineno}:unit arithmetic")
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
                violations.append(f"{path.relative_to(PROVIDERS_ROOT)}:{node.lineno}:requested-window comparison")
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            target_names = {child.id.lower() for child in ast.walk(node.target) if isinstance(child, ast.Name)}
            if target_names & {"attempt", "attempts", "retry", "retries"}:
                violations.append(f"{path.relative_to(PROVIDERS_ROOT)}:{node.lineno}:retry loop")
    return violations


def test_runtime_provider_inventory_has_only_ratified_roles() -> None:
    assert Counter(path.name for path in _runtime_provider_files()) == RUNTIME_FILE_COUNTS
    assert {path.parent.name for path in _runtime_provider_files() if path.name == "parser.py"} == {"pl_imgw"}


def test_provider_modules_do_not_expose_observations() -> None:
    for module_path in sorted(PROVIDERS_ROOT.glob("*/module.py")):
        module = import_module(f"rivretrieve._internal.providers.{module_path.parent.name}.module")
        definitions = {
            node.name for node in _tree(module_path).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "observations" not in definitions, module_path.relative_to(ROOT)
        assert not hasattr(module, "observations"), module_path.relative_to(ROOT)


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


def test_registry_uses_engine_stages_or_catalogue_only_registration() -> None:
    assert set(rr.providers()) == PROOF_PROVIDERS | CATALOGUE_ONLY_PROVIDERS
    records = {str(record.provider_id): record.handle for record in _registry.iter_records()}
    for provider_id in PROOF_PROVIDERS:
        assert records[provider_id]._module is not None
        assert records[provider_id]._stages is records[provider_id]._module
    for provider_id in CATALOGUE_ONLY_PROVIDERS:
        assert records[provider_id]._module is None
        assert records[provider_id]._stages is None


def test_cache_carve_out_handle_contracts_are_explicit() -> None:
    ca_eccc = rr.provider("ca_eccc")
    pl_imgw = rr.provider("pl_imgw")
    assert callable(cast(Any, ca_eccc).cache_status)
    assert callable(cast(Any, ca_eccc).refresh_cache)
    assert not hasattr(pl_imgw, "cache_status")
    assert not hasattr(pl_imgw, "refresh_cache")


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
        "src/rivretrieve/_internal/providers/ca_eccc/observation_client.py": ["TID251"],
        "src/rivretrieve/_internal/providers/pl_imgw/observation_client.py": ["TID251"],
        "tests/**": ["TID251"],
    }
    assert config["tool"]["ty"]["src"]["exclude"] == [reference_path]
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
