"""fourteenth provider proof : ProviderDirectory × ManifestLine → DiscoverableCatalogue."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path

import polars as pl

from rivretrieve._internal.catalogue_origins import Authored, AuthoredValue
from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES, load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
from rivretrieve._internal.catalogues.source_descriptions import generic_source_descriptions
from rivretrieve._internal.providers.ca_eccc.origins import STATION_CATALOGUE_ORIGINS

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

    template = load_packaged_catalogue_artifact(source)
    evidence = template.acquisition_provenance
    assert evidence is not None
    # The plugin reuses the same acquired source data under an authored registration ID.
    evidence = evidence.model_copy(update={"header": evidence.header.model_copy(update={"provider_id": provider_id})})
    origins = {**STATION_CATALOGUE_ORIGINS, "provider_id": Authored(AuthoredValue(provider_id))}
    metadata = build_catalogue_metadata(
        evidence,
        (origins,),
        {name: (destination / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        source_describer=partial(generic_source_descriptions, config=None),
    )
    for name, content in metadata.items():
        (destination / name).write_bytes(content)


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
    template_catalogue = providers_root / "ca_eccc" / "catalogue"
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
                f"assert {provider_id!r} in rr.providers().get_column('provider_id').to_list(); "
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
            # The generated project must not inherit an ancestor checkout's
            # pytest pythonpath when test temporary files live below .worktrees.
            "-c",
            os.devnull,
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
