"""Active tests may inspect archived code, but cannot execute it as an oracle."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
TESTS_ROOT = ROOT / "tests"
_RETIRED_TREE_NAME = "legacy_observations"
_DYNAMIC_EXECUTION_CALLS = {
    "exec",
    "eval",
    "run_module",
    "run_path",
    "spec_from_file_location",
}


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _imports_retired_implementation(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(_RETIRED_TREE_NAME in alias.name for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module is not None and _RETIRED_TREE_NAME in node.module:
            return True
    return False


def _executes_retired_implementation(tree: ast.Module) -> list[int]:
    """Find dynamic execution inside a scope that names the retired tree."""
    violations = []
    for scope in (node for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.FunctionDef))):
        if _RETIRED_TREE_NAME not in ast.unparse(scope):
            continue
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call):
                continue
            if _qualified_name(node.func).rsplit(".", maxsplit=1)[-1] in _DYNAMIC_EXECUTION_CALLS:
                violations.append(node.lineno)
    return violations


def test_no_retired_implementation_baseline() -> None:
    violations = []
    for path in sorted(TESTS_ROOT.glob("test_*.py")):
        if path == Path(__file__):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        if _imports_retired_implementation(tree):
            violations.append(f"{path.relative_to(ROOT)}: imports retired implementation")
        violations.extend(
            f"{path.relative_to(ROOT)}:{line}: executes retired implementation"
            for line in _executes_retired_implementation(tree)
        )

    assert violations == []


def test_nested_pytest_module_cannot_escape_policy(tmp_path: Path) -> None:
    nested_test = tmp_path / "tests" / "provider" / "retired_oracle_test.py"
    nested_test.parent.mkdir(parents=True)
    nested_test.write_text("import reference.legacy_observations.cz_chmi.source.module\n")

    assert _retired_implementation_violations(nested_test.parents[1], tmp_path) == [
        "tests/provider/retired_oracle_test.py: imports retired implementation"
    ]
