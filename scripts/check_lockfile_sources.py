"""Validate lockfile consistency and public PyPI source policy."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

PYPI_REGISTRY = "https://pypi.org/simple"
PYPI_FILES_PREFIX = "https://files.pythonhosted.org/"
SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\s*\[\s*([^\]]+)\s*\])?\s*(.*)$")
DISALLOWED_LOCK_SOURCES = frozenset({"url", "git", "path", "directory", "editable"})


class LockfileError(ValueError):
    """Project dependency declarations or lockfile failed validation."""


def _read_toml_file(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise LockfileError("Project dependency metadata must be a regular file without symlinks")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise LockfileError("Project dependency metadata is unavailable or malformed") from None
    if not isinstance(data, dict):
        raise LockfileError("Project dependency metadata must be a TOML table")
    return data


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _strip_outer_parens(text: str) -> str:
    value = text.strip()
    while len(value) >= 2 and value.startswith("(") and value.endswith(")"):
        depth = 0
        enclosed = True
        for index, char in enumerate(value):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index < len(value) - 1:
                    enclosed = False
                    break
        if not enclosed or depth != 0:
            break
        value = value[1:-1].strip()
    return value


def _normalize_specifier(specifier: str) -> str:
    stripped = _strip_outer_parens(specifier)
    clauses = sorted(re.sub(r"\s+", "", part) for part in stripped.split(",") if part.strip())
    return ",".join(clauses)


def _normalize_marker(marker: str | None) -> str | None:
    if marker is None:
        return None
    cleaned = re.sub(r"\s+", " ", marker.replace('"', "'").strip())
    return cleaned or None


def _parse_requirement(raw: object, *, extra: str | None = None) -> tuple[str, tuple[str, ...], str, str | None]:
    if not isinstance(raw, str):
        raise LockfileError("Dependency declaration must be a string")
    head, _, marker_raw = raw.partition(";")
    if "@" in head:
        raise LockfileError("Direct URL dependencies are not permitted under public PyPI lockfile policy")
    match = REQUIREMENT_RE.fullmatch(head.strip())
    if match is None:
        raise LockfileError("Malformed dependency declaration in pyproject.toml")
    name = _normalize_name(match.group(1))
    extras_raw = match.group(2)
    extras = (
        tuple(sorted(_normalize_name(part.strip()) for part in extras_raw.split(",") if part.strip()))
        if extras_raw
        else ()
    )
    specifier = _normalize_specifier(match.group(3))
    marker = _normalize_marker(marker_raw if marker_raw else None)
    if extra is not None:
        extra_clause = f"extra == '{_normalize_name(extra)}'"
        marker = f"({marker}) and {extra_clause}" if marker else extra_clause
    return (name, extras, specifier, marker)


def _parse_lock_requirement(entry: object) -> tuple[str, tuple[str, ...], str, str | None]:
    if not isinstance(entry, dict):
        raise LockfileError("Malformed dependency entry in uv.lock")
    if DISALLOWED_LOCK_SOURCES.intersection(entry):
        raise LockfileError("Direct or path dependencies are not permitted in uv.lock")
    name = entry.get("name")
    extras_raw = entry.get("extras", [])
    specifier = entry.get("specifier", "")
    marker = entry.get("marker")
    if (
        not isinstance(name, str)
        or not isinstance(extras_raw, list)
        or not all(isinstance(item, str) for item in extras_raw)
        or not isinstance(specifier, str)
        or (marker is not None and not isinstance(marker, str))
    ):
        raise LockfileError("Malformed dependency entry in uv.lock")
    extras = tuple(sorted(_normalize_name(item) for item in extras_raw))
    return (_normalize_name(name), extras, _normalize_specifier(specifier), _normalize_marker(marker))


def _validate_uv_tool_config(pyproject: dict) -> None:
    tool = pyproject.get("tool", {})
    if not isinstance(tool, dict):
        raise LockfileError("Malformed [tool] configuration in pyproject.toml")
    tool_uv = tool.get("uv", {})
    if not isinstance(tool_uv, dict):
        raise LockfileError("Malformed [tool.uv] configuration in pyproject.toml")
    for key in ("default-index", "index-url"):
        if key in tool_uv:
            value = tool_uv[key]
            if not isinstance(value, str) or value.rstrip("/") != PYPI_REGISTRY:
                raise LockfileError("pyproject.toml configures a non-PyPI package index")
    if "index" in tool_uv:
        indexes = tool_uv["index"]
        if not isinstance(indexes, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("url"), str)
            or item["url"].rstrip("/") != PYPI_REGISTRY
            for item in indexes
        ):
            raise LockfileError("pyproject.toml configures a non-PyPI package index")
    for key in ("extra-index-url", "find-links", "sources"):
        if tool_uv.get(key):
            raise LockfileError("pyproject.toml configures a non-PyPI package index or source")


def _validate_package_artifacts(package: dict) -> None:
    if package.get("source") != {"registry": PYPI_REGISTRY}:
        raise LockfileError("Lockfile contains a non-PyPI package source")
    wheels = package.get("wheels", [])
    if not isinstance(wheels, list):
        raise LockfileError("Lockfile package wheels entry is malformed")
    artifacts = ([package["sdist"]] if "sdist" in package else []) + wheels
    if not artifacts:
        raise LockfileError("Lockfile package lacks distribution artifacts")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise LockfileError("Lockfile package artifact is malformed")
        url = artifact.get("url")
        digest = artifact.get("hash")
        if (
            not isinstance(url, str)
            or not url.startswith(PYPI_FILES_PREFIX)
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
        ):
            raise LockfileError("Lockfile contains a non-PyPI or unhashed package artifact")


def _validate_root_metadata(pyproject: dict, project: dict, lock: dict, root: dict) -> None:
    root_name = root.get("name")
    if not isinstance(root_name, str) or _normalize_name(root_name) != _normalize_name(project["name"]):
        raise LockfileError("Lockfile root package name does not match pyproject.toml")
    if root.get("version") != project["version"]:
        raise LockfileError("Lockfile root package version does not match pyproject.toml")
    lock_python = lock.get("requires-python")
    if not isinstance(lock_python, str) or _normalize_specifier(lock_python) != _normalize_specifier(
        project["requires-python"]
    ):
        raise LockfileError("Lockfile requires-python does not match pyproject.toml")

    metadata = root.get("metadata", {})
    if not isinstance(metadata, dict):
        raise LockfileError("Lockfile root metadata is malformed")
    optional_deps = project.get("optional-dependencies", {})
    if not isinstance(optional_deps, dict):
        raise LockfileError("Malformed [project.optional-dependencies] in pyproject.toml")
    provides_extras = metadata.get("provides-extras", [])
    if not isinstance(provides_extras, list) or not all(isinstance(item, str) for item in provides_extras):
        raise LockfileError("Lockfile provides-extras metadata is malformed")
    if sorted(_normalize_name(name) for name in optional_deps) != sorted(
        _normalize_name(name) for name in provides_extras
    ):
        raise LockfileError("Lockfile optional extras do not match pyproject.toml")

    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise LockfileError("Malformed [project.dependencies] in pyproject.toml")
    expected_dist = {_parse_requirement(raw) for raw in dependencies}
    for extra, entries in optional_deps.items():
        if not isinstance(extra, str) or not isinstance(entries, list):
            raise LockfileError("Malformed [project.optional-dependencies] in pyproject.toml")
        expected_dist.update(_parse_requirement(raw, extra=extra) for raw in entries)

    requires_dist = metadata.get("requires-dist", [])
    if not isinstance(requires_dist, list):
        raise LockfileError("Lockfile requires-dist metadata is malformed")
    actual_dist = {_parse_lock_requirement(entry) for entry in requires_dist}
    if expected_dist != actual_dist:
        raise LockfileError("Lockfile dependency declarations do not match pyproject.toml")

    dep_groups = pyproject.get("dependency-groups", {})
    if not isinstance(dep_groups, dict):
        raise LockfileError("Malformed [dependency-groups] in pyproject.toml")
    expected_dev: dict[str, set[tuple[str, tuple[str, ...], str, str | None]]] = {}
    for group, entries in dep_groups.items():
        if (
            not isinstance(group, str)
            or not isinstance(entries, list)
            or not all(isinstance(item, str) for item in entries)
        ):
            raise LockfileError("Unsupported non-string entry in dependency-groups")
        expected_dev[_normalize_name(group)] = {_parse_requirement(raw) for raw in entries}

    requires_dev = metadata.get("requires-dev", {})
    if not isinstance(requires_dev, dict):
        raise LockfileError("Lockfile requires-dev metadata is malformed")
    actual_dev: dict[str, set[tuple[str, tuple[str, ...], str, str | None]]] = {}
    for group, entries in requires_dev.items():
        if not isinstance(group, str) or not isinstance(entries, list):
            raise LockfileError("Lockfile requires-dev metadata is malformed")
        actual_dev[_normalize_name(group)] = {_parse_lock_requirement(entry) for entry in entries}
    if expected_dev != actual_dev:
        raise LockfileError("Lockfile dependency-group declarations do not match pyproject.toml")


def validate_lockfile(checkout: Path) -> None:
    """Verify declared dependencies and public PyPI sources in ``uv.lock``."""
    project_uv_toml = checkout / "uv.toml"
    if project_uv_toml.exists() or project_uv_toml.is_symlink():
        raise LockfileError("Project-level uv.toml is not permitted under public PyPI lockfile policy")
    pyproject = _read_toml_file(checkout / "pyproject.toml")
    lock = _read_toml_file(checkout / "uv.lock")
    _validate_uv_tool_config(pyproject)

    project = pyproject.get("project")
    if not isinstance(project, dict) or not all(
        isinstance(project.get(field), str) for field in ("name", "version", "requires-python")
    ):
        raise LockfileError("Missing required [project] fields in pyproject.toml")

    packages = lock.get("package")
    if not isinstance(packages, list) or not packages or not all(isinstance(pkg, dict) for pkg in packages):
        raise LockfileError("Lockfile does not contain package entries")

    roots = [pkg for pkg in packages if pkg.get("source") in ({"editable": "."}, {"virtual": "."})]
    if len(roots) != 1:
        raise LockfileError("Lockfile must declare exactly one project root package")
    root = roots[0]

    _validate_root_metadata(pyproject, project, lock, root)
    for package in packages:
        if package is not root:
            _validate_package_artifacts(package)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("Usage: python -B scripts/check_lockfile_sources.py [CHECKOUT]", file=sys.stderr)
        return 2
    target = Path(args[0]) if args else Path(".")
    try:
        validate_lockfile(target)
    except LockfileError as error:
        print(f"Lockfile validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
