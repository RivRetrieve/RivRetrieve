"""Source-only checks for lockfile CI coverage and public PyPI enforcement."""

from __future__ import annotations

import runpy
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_lockfile_sources.py"


def _copy_project_files(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "pyproject.toml", destination / "pyproject.toml")
    shutil.copy2(ROOT / "uv.lock", destination / "uv.lock")
    return destination


def test_lockfile_workflow_covers_all_prs_and_port_branches() -> None:
    workflow = yaml.load((ROOT / ".github/workflows/check-lockfile.yml").read_text(), Loader=yaml.BaseLoader)
    on_config = workflow["on"]
    assert "pull_request" in on_config
    assert on_config["pull_request"] in (None, "", {})
    assert set(on_config["push"]["branches"]) >= {"main", "port/**"}
    assert "workflow_dispatch" in on_config

    job = workflow["jobs"]["check-lockfile"]
    assert job["name"] == "Verify uv.lock matches pyproject.toml and public PyPI"
    steps = job["steps"]
    python_step = next(step for step in steps if step.get("run") == "uv python install 3.13")
    lock_step = next(
        step for step in steps if step.get("run") == "uv lock --check --default-index https://pypi.org/simple"
    )
    source_step = next(
        step
        for step in steps
        if step.get("run") == "uv run --no-project --python 3.13 python -B scripts/check_lockfile_sources.py"
    )
    assert steps.index(python_step) < steps.index(lock_step) < steps.index(source_step)


def test_check_lockfile_sources_accepts_repository_lockfile() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    namespace["validate_lockfile"](ROOT)


@pytest.mark.parametrize(
    ("case", "target_file", "old", "new"),
    [
        ("added-runtime-dep", "pyproject.toml", '"pyproj>=3.8.0",', '"pyproj>=3.8.0",\n    "httpx>=0.27",'),
        ("changed-dev-specifier", "pyproject.toml", '"pytest>=8.3",', '"pytest>=99",'),
        (
            "mirror-registry",
            "uv.lock",
            'registry = "https://pypi.org/simple"',
            'registry = "https://mirror.example.invalid/simple"',
        ),
        (
            "mirror-wheel-url",
            "uv.lock",
            '    { url = "https://files.pythonhosted.org/',
            '    { url = "https://mirror.example.invalid/',
        ),
        (
            "custom-tool-uv-index",
            "pyproject.toml",
            "[tool.uv.build-backend]",
            '[[tool.uv.index]]\nname = "mirror"\nurl = "https://mirror.example.invalid/simple"\ndefault = true\n\n[tool.uv.build-backend]',
        ),
    ],
)
def test_check_lockfile_sources_rejects_stale_and_mirror_inputs(
    tmp_path: Path, case: str, target_file: str, old: str, new: str
) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    lockfile_error = namespace["LockfileError"]
    checkout = _copy_project_files(tmp_path / case)
    target = checkout / target_file
    text = target.read_text(encoding="utf-8")
    assert old in text
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(lockfile_error):
        namespace["validate_lockfile"](checkout)


def test_check_lockfile_sources_rejects_symlinked_lockfile(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    lockfile_error = namespace["LockfileError"]
    checkout = tmp_path / "symlinked-lock"
    checkout.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", checkout / "pyproject.toml")
    real_lock = tmp_path / "real-uv.lock"
    shutil.copy2(ROOT / "uv.lock", real_lock)
    (checkout / "uv.lock").symlink_to(real_lock)
    with pytest.raises(lockfile_error):
        namespace["validate_lockfile"](checkout)


def test_check_lockfile_sources_rejects_project_uv_toml(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    lockfile_error = namespace["LockfileError"]
    checkout = _copy_project_files(tmp_path / "project-uv-toml")
    (checkout / "uv.toml").write_text('default-index = "https://mirror.example.invalid/simple"\n', encoding="utf-8")
    with pytest.raises(lockfile_error):
        namespace["validate_lockfile"](checkout)

    symlink_checkout = _copy_project_files(tmp_path / "symlinked-uv-toml")
    (symlink_checkout / "uv.toml").symlink_to(checkout / "uv.toml")
    with pytest.raises(lockfile_error):
        namespace["validate_lockfile"](symlink_checkout)
