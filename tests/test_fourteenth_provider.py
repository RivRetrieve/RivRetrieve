"""fourteenth provider proof : ProviderDirectory × ManifestLine → DiscoverableCatalogue."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
import pytest

from rivretrieve._internal.acquisition_provenance import (
    ArchiveMemberReference,
    CatalogueBuildInputs,
    CodeReference,
    RetainedInputUse,
)
from rivretrieve._internal.catalogue_origins import Authored, AuthoredValue, Field
from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES, load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import NativeTable
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

    # Synthetic build identities exercise dependency wiring only. This fixture
    # does not certify archived bytes or add a provider source claim.
    def code(path: str, symbol: str) -> CodeReference:
        return CodeReference(
            repository="https://github.com/RivRetrieve/RivRetrieve",
            revision="0" * 40,
            repository_path=path,
            symbol=symbol,
        )

    source_fact = evidence.facts.join(evidence.binding_facts, on="fact_id").join(
        evidence.bindings.filter(pl.col("transformation_id").is_null()), on="binding_id"
    )["name"][0]
    module = f"src/rivretrieve/_internal/providers/{provider_id}"
    historical_native = evidence.header.native_table
    assert historical_native is not None and historical_native.byte_size is not None
    build_inputs = CatalogueBuildInputs(
        build=code(f"{module}/generate_catalogue.py", "write_catalogue"),
        declarations=(
            code(f"{module}/generate_catalogue.py", "build_catalogue"),
            code(f"{module}/origins.py", "build_acquisition_provenance"),
            code("src/rivretrieve/_internal/assembly.py", "assemble"),
        ),
        inputs=(
            RetainedInputUse(
                reference=ArchiveMemberReference(
                    archive_repository="https://github.com/RivRetrieve/verification-evidence",
                    archive_revision="0" * 40,
                    collection_id="synthetic",
                    manifest_sha256="0" * 64,
                    artifact_id="synthetic-native",
                    sha256=historical_native.sha256,
                    byte_size=historical_native.byte_size,
                    role="derived_input",
                ),
                usage="native_table",
                facts=(source_fact,),
            ),
        ),
    )
    station_origin = origins["station_id"]
    assert isinstance(station_origin, Field)
    native = NativeTable(
        pl.read_parquet(destination / "stations.parquet").select(
            pl.col("station_id").alias(str(station_origin.native_column)),
            pl.lit(datetime(2000, 1, 1, tzinfo=UTC)).alias("retrieved_at"),
        )
    )
    metadata = build_catalogue_metadata(
        evidence,
        (origins,),
        {name: (destination / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        build_inputs=build_inputs,
        native_table=native,
        metadata_fields=(),
        source_describer=partial(generic_source_descriptions, config=None),
    )
    for name, content in metadata.items():
        (destination / name).write_bytes(content)


def _append_manifest_line(manifest: Path, provider_id: str) -> None:
    source = manifest.read_text()
    closing = "\n)\n"
    assert source.endswith(closing)
    manifest.write_text(f"{source[: -len(closing)]}\n    {provider_id!r},{closing}")


@pytest.fixture
def provider_contract_workspace(record_property) -> Iterator[Path]:
    checks = ROOT / ".worktrees" / "provider-contract-checks"
    checks.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="provider-", dir=checks) as temporary:
        record_property("source_copy", temporary)
        yield Path(temporary)


def test_new_catalogue_only_provider_requires_only_its_directory_and_manifest_line(
    provider_contract_workspace: Path,
) -> None:
    provider_id = "test_" + "fourteenth"
    project = provider_contract_workspace
    package = project / "src" / "rivretrieve"
    shutil.copytree(PACKAGE_ROOT, package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
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
