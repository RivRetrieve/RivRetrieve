"""A valid old store cannot resurrect retired universal-mean definitions."""

import hashlib
import shutil
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.providers.pl_imgw.config import config
from rivretrieve._internal.providers.pl_imgw.declaration import declaration
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.store.validation import ObservationStoreRefusedError, StoreRefusalKind


@pytest.mark.parametrize("quantity", ["discharge", "stage", "temperature"])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.derived("tests/test_data/boundary_stores/pl_imgw_retired_mean")
def test_retired_compiled_products_refused_before_read_and_left_intact(
    retained_evidence_root: Path, tmp_path, monkeypatch, quantity, policy
):
    store = tmp_path / "store"
    shutil.copytree(retained_evidence_root / "tests/test_data/boundary_stores/pl_imgw_retired_mean", store)
    before = {
        str(p.relative_to(store)): hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob("*") if p.is_file()
    }
    registry = ProviderRegistry()
    registry.register(
        "pl_imgw",
        load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise"),
        bulk_config=config,
        observation_store=StoreRoot(store),
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)
    selection = rr.find(provider="pl_imgw", station="154210010", quantity=quantity)
    with pytest.raises(ObservationStoreRefusedError, match="download") as caught:
        rr.fetch(selection, start="2023-01-01", end="2023-01-01", on_issue=policy)
    assert caught.value.refusal.kind is StoreRefusalKind.INCOMPATIBLE
    after = {
        str(p.relative_to(store)): hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob("*") if p.is_file()
    }
    assert after == before
