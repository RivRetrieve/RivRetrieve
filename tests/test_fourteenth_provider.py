"""fourteenth provider proof : ProviderDirectory × ManifestLine → DiscoverableCatalogue."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import polars as pl

from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = ROOT / "src" / "rivretrieve"
PROVIDERS_ROOT = PACKAGE_ROOT / "_internal" / "providers"


def _copy_catalogue_with_provider_id(source: Path, destination: Path, provider_id: str) -> None:
    """Materialise one valid generated catalogue under a new provider identity."""
    destination.mkdir(parents=True)
    provider_info = json.loads((source / "provider.json").read_text())
    provider_info["provider_id"] = provider_id
    (destination / "provider.json").write_text(json.dumps(provider_info))

    for filename in ("products.parquet", "stations.parquet", "station_products.parquet"):
        frame = pl.read_parquet(source / filename).with_columns(pl.lit(provider_id).alias("provider_id"))
        frame.write_parquet(destination / filename)


def _append_manifest_line(manifest: Path, provider_id: str) -> None:
    source = manifest.read_text()
    closing = "\n)\n"
    assert source.endswith(closing)
    manifest.write_text(f"{source[: -len(closing)]}\n    {provider_id!r},{closing}")


def test_new_catalogue_only_provider_requires_only_its_directory_and_manifest_line(tmp_path: Path) -> None:
    provider_id = "test_" + "fourteenth"
    project = tmp_path / "project"
    package = project / "src" / "rivretrieve"
    shutil.copytree(PACKAGE_ROOT, package)
    (project / "tests").mkdir()
    shutil.copy2(ROOT / "tests" / "test_provider_architecture_contracts.py", project / "tests")

    providers_root = package / "_internal" / "providers"
    provider_root = providers_root / provider_id
    provider_root.mkdir()
    (provider_root / "declaration.py").write_text(
        '"""provider declaration : PackagedCatalogue × CatalogueOnly → DeclaredProvider."""\n\n'
        "from pathlib import Path\n\n"
        "from rivretrieve._internal.providers.registration import CatalogueOnly, ProviderDeclaration\n\n"
        "declaration = ProviderDeclaration(\n"
        '    catalogue=Path(__file__).parent / "catalogue",\n'
        "    observations=CatalogueOnly(),\n"
        ")\n"
    )
    template_catalogue = providers_root / BUILTIN_PROVIDER_IDS[0] / "catalogue"
    _copy_catalogue_with_provider_id(template_catalogue, provider_root / "catalogue", provider_id)
    _append_manifest_line(package / "_internal" / "provider_manifest.py", provider_id)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import rivretrieve as rr; "
                f"assert {provider_id!r} in rr.providers(); "
                f"frame = rr.as_frame(rr.find(provider={provider_id!r})); "
                "assert frame.height > 0; "
                f"assert set(frame['provider_id']) == {{{provider_id!r}}}"
            ),
        ],
        cwd=project,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert probe.returncode == 0, probe.stderr

    architecture = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_provider_architecture_contracts.py::test_runtime_provider_inventory_has_only_ratified_roles",
            "tests/test_provider_architecture_contracts.py::test_registry_matches_declared_provider_kinds",
        ],
        cwd=project,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert architecture.returncode == 0, architecture.stdout + architecture.stderr
