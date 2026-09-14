"""Corrupt public evidence bytes refuse artifact loading and atomic registration."""

from pathlib import Path
from shutil import copytree

import pytest

from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.registration import CatalogueOnly, ProviderDeclaration, register_manifest
from rivretrieve._internal.registry import ProviderRegistry

ROOT = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers"


def _corrupt_catalogue(tmp_path: Path) -> Path:
    path = copytree(ROOT / "ba_fhmzbih/catalogue", tmp_path / "ba_fhmzbih")
    evidence_file = path / "provenance_facts.parquet"
    evidence_file.write_bytes(evidence_file.read_bytes() + b"corrupt")
    return path


def test_corrupt_evidence_bytes_raise_artifact_contract_error(tmp_path: Path) -> None:
    path = _corrupt_catalogue(tmp_path)
    with pytest.raises(CorruptCatalogArtifactError, match="provenance_facts.parquet"):
        load_packaged_catalogue_artifact(path, on_issue="raise")


def test_corrupt_unrelated_evidence_refuses_complete_manifest_with_context(tmp_path: Path) -> None:
    path = _corrupt_catalogue(tmp_path)
    registry = ProviderRegistry()
    declarations = {
        "usgs_nwis": ProviderDeclaration(catalogue=ROOT / "usgs_nwis/catalogue", observations=CatalogueOnly()),
        "ba_fhmzbih": ProviderDeclaration(catalogue=path, observations=CatalogueOnly()),
    }
    with pytest.raises(FatalContractError, match="Provider ba_fhmzbih catalogue") as error:
        register_manifest(registry, ("usgs_nwis", "ba_fhmzbih"), declaration_loader=declarations.__getitem__)
    assert str(path) in str(error.value)
    assert "provenance_facts.parquet" in str(error.value)
    assert isinstance(error.value.__cause__, CorruptCatalogArtifactError)
    assert registry.iter_records() == ()
