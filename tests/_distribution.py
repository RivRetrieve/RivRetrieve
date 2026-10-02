"""Session-owned built distributions for installed, offline packaging checks."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from tarfile import open as open_tar
from tempfile import TemporaryDirectory

import pytest


@dataclass(frozen=True)
class InstalledDistribution:
    wheel: Path
    sdist: Path | None
    python: Path
    execution: Path

    def verify(self, source: str) -> None:
        # Each verifier gets a new process, working directory and HOME, while the
        # installed distribution remains a read-only input shared by the session.
        with TemporaryDirectory(prefix="verify-", dir=self.execution) as temporary:
            run(
                [str(self.python), "-I", "-B", "-c", source],
                cwd=Path(temporary),
                env={"PATH": os.environ["PATH"], "HOME": temporary},
            )


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="session")
def distribution_workspace() -> Iterator[Path]:
    repository = Path(__file__).resolve().parents[1]
    checks = repository / ".worktrees" / "distribution-checks"
    checks.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="installed-", dir=checks) as temporary:
        yield Path(temporary)


def _build_and_install(workspace: Path, *, from_sdist: bool) -> InstalledDistribution:
    repository = Path(__file__).resolve().parents[1]
    workspace.mkdir()
    dist = workspace / "dist"
    source = repository
    sdist = None
    # Use the backend installed from the lock. Isolated build dependency resolution
    # needs registry metadata that a fresh locked sync need not cache. The built
    # package is still installed and verified in a separate offline environment.
    build = ["uv", "build", "--offline", "--force-pep517", "--no-build-isolation", "--python", sys.executable]
    if from_sdist:
        run([*build, "--sdist", "--out-dir", str(dist)], cwd=source)
        archives = tuple(dist.glob("rivretrieve-*.tar.gz"))
        assert len(archives) == 1
        sdist = archives[0]
        extracted = workspace / "extracted"
        with open_tar(sdist, "r:gz") as archive:
            archive.extractall(extracted, filter="data")
        sources = tuple(extracted.iterdir())
        assert len(sources) == 1
        source = sources[0]
    run([*build, "--wheel", "--out-dir", str(dist)], cwd=source)
    wheels = tuple(dist.glob("rivretrieve-*.whl"))
    assert len(wheels) == 1

    environment = workspace / "environment"
    execution = workspace / "execution"
    execution.mkdir()
    run(["uv", "venv", "--offline", "--python", sys.executable, str(environment)], cwd=execution)
    python = environment / "bin" / "python"
    run(["uv", "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheels[0])], cwd=execution)
    sites = tuple((environment / "lib").glob("python*/site-packages"))
    assert len(sites) == 1
    # Reuse dependency directories without executing the project's editable .pth files.
    dependencies = list(
        dict.fromkeys(
            str(Path(path).resolve())
            for path in sys.path
            if Path(path).is_absolute() and Path(path).name == "site-packages" and Path(path).is_dir()
        )
    )
    assert dependencies
    assert all(not Path(path).is_relative_to(repository / "src") for path in dependencies)
    (sites[0] / "dependencies.pth").write_text("\n".join(dependencies) + "\n")
    return InstalledDistribution(wheels[0], sdist, python, execution)


@pytest.fixture(scope="session")
def direct_distribution(distribution_workspace: Path) -> InstalledDistribution:
    return _build_and_install(distribution_workspace / "wheel", from_sdist=False)


@pytest.fixture(scope="session")
def sdist_distribution(distribution_workspace: Path) -> InstalledDistribution:
    return _build_and_install(distribution_workspace / "sdist-wheel", from_sdist=True)


@pytest.fixture
def installed_distribution(request: pytest.FixtureRequest) -> InstalledDistribution:
    fixture = {"wheel": "direct_distribution", "sdist-wheel": "sdist_distribution"}[request.param]
    return request.getfixturevalue(fixture)
