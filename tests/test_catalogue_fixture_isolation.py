"""Reusable test inputs remain isolated and cannot hide changed catalogue files."""

import os
from dataclasses import replace
from pathlib import Path
from shutil import copytree

import polars as pl
import polars.testing as plt
import pytest

import rivretrieve as rr
from rivretrieve._internal import provider_manifest
from rivretrieve._internal.catalogues.artifact import (
    CorruptCatalogArtifactError,
    load_packaged_catalogue_artifact,
)
from rivretrieve._internal.catalogues.evidence import EVIDENCE_SCHEMAS
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers import registration
from rivretrieve._internal.providers.ba_fhmzbih import declaration as ba_declaration
from rivretrieve._internal.registry import ProviderRegistry, _registry
from tests._catalogue_inputs import PackagedCatalogueInputs
from tests._provenance import write_evidence_table

_SOURCE = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue"


@pytest.fixture
def inputs(tmp_path):
    path = copytree(_SOURCE, tmp_path / "catalogue")
    calls = []

    def load(path):
        calls.append(path)
        return load_packaged_catalogue_artifact(path, on_issue="raise")

    return path, PackagedCatalogueInputs((path,), load), calls


def _assert_equal(actual, expected):
    assert actual.provider_info == expected.provider_info
    assert actual.source_descriptions == expected.source_descriptions
    for name in ("products", "stations", "station_products", "catalogue_claims"):
        plt.assert_frame_equal(getattr(actual, name), getattr(expected, name))
    left, right = actual.acquisition_provenance, expected.acquisition_provenance
    assert left.header == right.header
    for name in EVIDENCE_SCHEMAS:
        plt.assert_frame_equal(getattr(left, name), getattr(right, name))


def test_each_borrow_detaches_frames_mappings_and_nested_models(inputs):
    path, pool, calls = inputs
    original = pool.load(path)
    changed = pool.load(path)
    changed.provider_info["name"] = "changed"
    for name in ("products", "stations", "station_products", "catalogue_claims"):
        getattr(changed, name).drop_in_place(getattr(changed, name).columns[0])
    evidence = changed.acquisition_provenance
    for name in EVIDENCE_SCHEMAS:
        frame = getattr(evidence, name)
        frame.drop_in_place(frame.columns[0])
    evidence.header.files.clear()
    # Frozen model assignment is normally refused. Even deliberate internal
    # mutation cannot reach another test's copy or the pristine pool template.
    changed.source_descriptions.descriptions[0].identity.__dict__["namespace"] = "changed"
    _assert_equal(pool.load(path), original)
    assert len(calls) == 1


def test_same_size_same_mtime_change_revalidates_actual_bytes(inputs):
    path, pool, calls = inputs
    first = pool.load(path)
    file = path / "provider.json"
    old = file.read_bytes()
    stat = file.stat()
    new = old.replace(b"Agencija", b"agencija")
    assert new != old and len(new) == len(old)
    file.write_bytes(new)
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = pool.load(path)
    assert second.provider_info["name"] != first.provider_info["name"]
    assert second.provider_info["name"].startswith("agencija")
    assert len(calls) == 2
    _assert_equal(pool.load(path), second)
    assert len(calls) == 2


@pytest.mark.parametrize("filename", ["format.json", "source_series.json", "provenance_facts.parquet"])
def test_corruption_after_warming_reaches_real_loader(inputs, filename):
    path, pool, calls = inputs
    pool.load(path)
    (path / filename).write_bytes(b"corrupt")
    for _ in range(2):
        with pytest.raises(CorruptCatalogArtifactError):
            pool.load(path)
    assert len(calls) == 3


def test_semantic_corruption_with_fresh_digest_reaches_real_validator(inputs):
    path, pool, calls = inputs
    original = pool.load(path)
    facts = original.acquisition_provenance.facts
    write_evidence_table(path, "provenance_facts.parquet", facts.with_columns(pl.lit("duplicate").alias("name")))
    with pytest.raises(CorruptCatalogArtifactError, match="unique facts"):
        pool.load(path)
    assert len(calls) == 2


def test_removed_input_and_symlink_do_not_reuse_warm_template(inputs):
    path, pool, calls = inputs
    pool.load(path)
    file = path / "provenance_facts.parquet"
    moved = file.rename(path / "saved.parquet")
    with pytest.raises(CorruptCatalogArtifactError):
        pool.load(path)
    file.symlink_to(moved)
    with pytest.raises(CorruptCatalogArtifactError, match="symlinks"):
        pool.load(path)
    assert len(calls) == 3


def test_unlisted_copied_directory_always_uses_real_loader(inputs, tmp_path):
    path, pool, calls = inputs
    pool.load(path)
    copied = copytree(path, tmp_path / "other")
    first = pool.load(copied)
    _assert_equal(pool.load(copied), first)
    assert calls == [path, copied, copied]
    (copied / "format.json").write_bytes(b"corrupt")
    with pytest.raises(CorruptCatalogArtifactError):
        pool.load(copied)
    assert calls[-1] == copied


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_reused_inputs_register_fresh_handles_and_honor_changed_declarations(monkeypatch, tmp_path):
    monkeypatch.setattr(provider_manifest, "BUILTIN_PROVIDER_IDS", ("ba_fhmzbih",))
    rr.providers()
    first = _registry.get("ba_fhmzbih")
    first._artifact.provider_info["name"] = "changed by an earlier test"
    _registry.clear()
    rr.providers()
    second = _registry.get("ba_fhmzbih")
    assert second is not first
    assert second._artifact.provider_info["name"] != first._artifact.provider_info["name"]

    corrupt = copytree(_SOURCE, tmp_path / "corrupt")
    (corrupt / "source_series.json").write_bytes(b"corrupt")
    monkeypatch.setattr(ba_declaration, "declaration", replace(ba_declaration.declaration, catalogue=corrupt))
    _registry.clear()
    with pytest.raises(FatalContractError, match="Provider ba_fhmzbih catalogue"):
        rr.providers()
    assert _registry.iter_records() == ()


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_explicit_artifact_loader_is_not_replaced(stub_packaged_catalogue_artifact):
    calls = []
    artifact = stub_packaged_catalogue_artifact("xx_test")
    path = Path("explicit-unread-path")
    registry = ProviderRegistry()
    declaration = registration.ProviderDeclaration(path, registration.CatalogueOnly())
    registration.register_manifest(
        registry,
        ("xx_test",),
        declaration_loader=lambda _: declaration,
        artifact_loader=lambda path: calls.append(path) or artifact,
    )
    assert calls == [path]
    assert registry.get("xx_test")._artifact is artifact


def test_every_loader_input_change_invalidates_a_warm_template(inputs, monkeypatch):
    path, pool, calls = inputs
    pool.load(path)
    reloaded = []

    class ReloadRequiredError(Exception):
        pass

    def probe(current):
        reloaded.append(current)
        raise ReloadRequiredError

    monkeypatch.setattr(pool, "_loader", probe)
    # Deliberately independent of the pool's input list: adding a loader input
    # requires an explicit freshness decision in this test and the fixture.
    filenames = (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
        "provenance.json",
        "provenance_facts.parquet",
        "provenance_acquisitions.parquet",
        "provenance_bindings.parquet",
        "provenance_binding_facts.parquet",
        "provenance_external_inputs.parquet",
    )
    for filename in filenames:
        file = path / filename
        before = file.read_bytes()
        file.write_bytes(before + b"changed")
        try:
            with pytest.raises(ReloadRequiredError):
                pool.load(path)
        finally:
            file.write_bytes(before)
    assert reloaded == [path] * len(filenames)
    assert len(calls) == 1
    # Restoring the exact validated bytes can safely borrow the original again.
    pool.load(path)
    assert len(reloaded) == len(filenames)
