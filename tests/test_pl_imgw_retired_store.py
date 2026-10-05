"""A valid old store cannot resurrect retired universal-mean definitions."""

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.pl_imgw.config import config
from rivretrieve._internal.providers.pl_imgw.declaration import declaration
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.source_series import known
from rivretrieve._internal.store import StoreRoot, compile_store, validation
from rivretrieve._internal.store.validation import ObservationStoreRefusedError, StoreRefusalKind
from tests.store.certification_support import artifact_and_request, fixture_series, rows


@pytest.mark.parametrize("quantity", ["discharge", "stage", "temperature"])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.derived("tests/test_data/boundary_stores/pl_imgw_retired_mean")
def test_unsealed_retired_store_refused_and_left_intact(
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
    monkeypatch.delenv("RIVRETRIEVE_CACHE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)

    def no_values(*args, **kwargs):
        pytest.fail("unsealed store reached observation values")

    class NoSource:
        def send(self, request):
            pytest.fail("unsealed store reached source transport")

    monkeypatch.setattr(validation, "_open_parquet", no_values)
    monkeypatch.setattr(discovery, "HttpClient", NoSource)
    selection = rr.find(provider="pl_imgw", station="154210010", quantity=quantity)
    with pytest.raises(ObservationStoreRefusedError, match=r"integrity\.seal:") as caught:
        rr.fetch(selection, start="2023-01-01", end="2023-01-01", on_issue=policy)
    assert caught.value.refusal.kind is StoreRefusalKind.MALFORMED
    after = {
        str(p.relative_to(store)): hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob("*") if p.is_file()
    }
    assert after == before


@pytest.mark.parametrize("quantity", ["discharge", "stage", "temperature"])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_retired_compiled_products_refused_before_read_and_left_intact(tmp_path, monkeypatch, quantity, policy):
    product, unit = {
        "discharge": ("discharge_daily_mean", "m3/s"),
        "stage": ("stage_daily_mean", "cm"),
        "temperature": ("water_temperature_daily_mean", "degC"),
    }[quantity]
    definition = fixture_series("154210010", "pl_imgw", product)
    facts = definition.facts[0].model_copy(
        update={
            "facts_id": f"authored-retired-{quantity}",
            "quantity": known(quantity, "authored retired-product control"),
            "source_unit": known(unit, "authored retired-product control"),
            "normalized_unit": unit,
        }
    )
    definition = definition.model_copy(update={"facts": (facts,)})
    _, request = artifact_and_request(tmp_path)
    request = replace(request, provider_id=ProviderId("pl_imgw"), series=(definition,))
    authored = rows(station="154210010").with_columns(
        pl.lit(product).alias("product"),
        pl.lit(definition.series_id).alias("series_id"),
        pl.lit(facts.facts_id).alias("facts_id"),
        pl.lit(unit).alias("source_unit"),
    )
    compile_store(request, authored)
    store = request.destination
    before = {str(p.relative_to(store)): p.read_bytes() for p in store.rglob("*") if p.is_file()}
    registry = ProviderRegistry()
    registry.register(
        "pl_imgw",
        load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise"),
        bulk_config=config,
        observation_store=store,
    )
    monkeypatch.delenv("RIVRETRIEVE_CACHE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)

    def no_values(*args, **kwargs):
        pytest.fail("retired product reached observation values")

    class NoSource:
        def send(self, request):
            pytest.fail("retired product reached source transport")

    monkeypatch.setattr(validation, "_open_parquet", no_values)
    monkeypatch.setattr(discovery, "HttpClient", NoSource)
    selection = rr.find(provider="pl_imgw", station="154210010", quantity=quantity)
    with pytest.raises(
        ObservationStoreRefusedError, match="compiled source products are no longer supported"
    ) as caught:
        rr.fetch(selection, start="2023-01-01", end="2023-01-01", on_issue=policy)
    assert caught.value.refusal.kind is StoreRefusalKind.INCOMPATIBLE
    assert caught.value.refusal.defect == f"compiled source products are no longer supported: {product}"
    assert {str(p.relative_to(store)): p.read_bytes() for p in store.rglob("*") if p.is_file()} == before
