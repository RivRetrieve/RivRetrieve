"""Deferred provider packaged facts : Artifacts → Withheld catalogue carriers."""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

import rivretrieve as rr
from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogues.artifact import (
    CATALOGUE_FACT_UNIVERSE,
    CorruptCatalogArtifactError,
    load_packaged_catalogue_artifact,
)
from rivretrieve._internal.discovery import EmptySelectionError
from tests._catalogue import catalogue_path, catalogue_reader

DEFERRED_PROVIDERS = {
    "br_ana": (10_429, 52_145),
    "no_nve": (4_889, 44_001),
}


@pytest.mark.parametrize("provider_id,legacy_counts", DEFERRED_PROVIDERS.items())
def test_deferred_provider_packaged_source_facts_are_hard_withheld(
    provider_id: str,
    legacy_counts: tuple[int, int],
) -> None:
    """Prove legacy station facts do not survive the real packaged load path."""
    artifact_path = catalogue_path(provider_id)
    artifact = load_packaged_catalogue_artifact(artifact_path, on_issue="raise")

    assert legacy_counts in {(10_429, 52_145), (4_889, 44_001)}
    assert artifact.products.is_empty()
    assert artifact.stations.is_empty()
    assert artifact.station_products.is_empty()
    assert pl.read_parquet(artifact_path / "products.parquet").is_empty()
    assert pl.read_parquet(artifact_path / "stations.parquet").is_empty()
    assert pl.read_parquet(artifact_path / "station_products.parquet").is_empty()

    provenance = artifact.acquisition_provenance
    assert provenance is not None
    assert provenance.native_table is None
    assert provenance.source_records == ()
    assert len(provenance.fact_bindings) == 1
    authored = provenance.fact_bindings[0]
    assert authored.transformation is not None
    assert authored.transformation.kind == "authored_constant"
    assert set(provenance.fact_universe) == set(CATALOGUE_FACT_UNIVERSE)
    assert {group.fact_group for group in provenance.withheld_facts} == {
        "provider_external_catalogue_facts_without_acquisition",
        "product_definitions_without_acquisition",
        "station_identity_and_location_without_acquisition",
        "station_product_relationships_without_acquisition",
    }
    withheld = {fact for group in provenance.withheld_facts for fact in group.facts}
    assert withheld == set(CATALOGUE_FACT_UNIVERSE) - set(authored.facts)
    assert withheld & {"provider.provider_id", "provider.name"} == set()
    assert {group.reason for group in provenance.withheld_facts} == {"no_acquisition_record_established"}


@pytest.mark.parametrize("provider_id", DEFERRED_PROVIDERS)
def test_deferred_provider_public_discovery_exposes_no_packaged_catalogue_values(provider_id: str) -> None:
    """Prove installed discovery traverses the same hard-gated empty carriers."""
    assert provider_id in rr.providers()
    assert rr.products(provider=provider_id) == []
    reader = catalogue_reader(provider_id)
    results = (reader.read_products(), reader.read_stations(), reader.read_station_products())
    assert all(result.data.is_empty() for result in results)
    assert all(result.provenance.acquisition_provenance is not None for result in results)


def test_deferred_provenance_distinguishes_withheld_from_null_and_not_published() -> None:
    """Prove three absence states keep different structured representations."""
    deferred = load_packaged_catalogue_artifact(catalogue_path("br_ana"), on_issue="raise")
    withheld = deferred.acquisition_provenance
    assert withheld is not None
    assert any(group.reason == "no_acquisition_record_established" for group in withheld.withheld_facts)

    japan = load_packaged_catalogue_artifact(catalogue_path("jp_mlit"), on_issue="raise")
    assert japan.provider_info["license"] is None
    origins_text = (catalogue_path("jp_mlit").parent / "origins.py").read_text(encoding="utf-8")
    assert "NotPublished" in origins_text

    raw = json.loads((catalogue_path("br_ana") / "provider.json").read_text(encoding="utf-8"))
    assert raw["license"] is None
    assert withheld.withheld_facts


@pytest.mark.parametrize("provider_id", DEFERRED_PROVIDERS)
def test_deferred_provider_requires_provenance_at_the_packaged_boundary(
    provider_id: str,
    tmp_path: Path,
) -> None:
    copied = tmp_path / provider_id
    shutil.copytree(catalogue_path(provider_id), copied)
    (copied / "provenance.json").unlink()

    with pytest.raises(CorruptCatalogArtifactError, match=f"{provider_id} acquisition provenance is required"):
        load_packaged_catalogue_artifact(copied, on_issue="raise")


@pytest.mark.parametrize("provider_id", DEFERRED_PROVIDERS)
def test_deferred_provider_selection_retains_reason_and_fails_truthfully(provider_id: str) -> None:
    selection = rr.find(provider=provider_id)

    assert selection.series == ()
    assert len(selection.acquisition_provenance) == 1
    provenance = selection.acquisition_provenance[0]
    assert provenance.provider_id == provider_id
    assert provenance.withheld_facts
    assert selection.empty_reason is not None
    assert selection.empty_reason.code == "no_catalogue_edge"
    with pytest.raises(EmptySelectionError, match=r"fetch\(\) cannot retrieve an empty selection"):
        rr.fetch(selection, start="2024-01-01", end="2024-01-02")


@pytest.mark.parametrize(
    "provider_id,catalogue_date",
    (("br_ana", "2026-06-11"), ("no_nve", "2026-06-03")),
)
def test_maintainer_withholding_operation_is_network_free_and_deterministic(
    provider_id: str,
    catalogue_date: str,
    tmp_path: Path,
) -> None:
    module = importlib.import_module(f"rivretrieve._internal.providers.{provider_id}.generate_catalogue")
    result = module.main(
        [
            "--withhold-uncertified",
            "--out",
            str(tmp_path),
            "--catalogue-date",
            catalogue_date,
        ]
    )

    assert result == 0
    generated = load_packaged_catalogue_artifact(tmp_path, on_issue="raise")
    assert generated.products.is_empty()
    assert generated.stations.is_empty()
    assert generated.station_products.is_empty()
    assert generated.acquisition_provenance is not None
    assert generated.acquisition_provenance.native_table is None
    for artifact_name in (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
    ):
        assert (tmp_path / artifact_name).read_bytes() == (catalogue_path(provider_id) / artifact_name).read_bytes()


def test_acquisition_provenance_v2_is_the_only_accepted_packaged_schema(tmp_path: Path) -> None:
    copied = tmp_path / "jp_mlit"
    shutil.copytree(catalogue_path("jp_mlit"), copied)
    payload = json.loads((copied / "provenance.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    payload["schema_version"] = 1
    (copied / "provenance.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorruptCatalogArtifactError, match="Input should be 2"):
        load_packaged_catalogue_artifact(copied, on_issue="raise")


def test_acquisition_provenance_v2_rejects_legacy_and_mixed_withheld_shapes() -> None:
    provenance = load_packaged_catalogue_artifact(catalogue_path("br_ana"), on_issue="raise").acquisition_provenance
    assert provenance is not None
    payload = provenance.model_dump(mode="json")
    assert payload["schema_version"] == 2
    assert payload["withheld_facts"]
    assert all("fact" not in item for item in payload["withheld_facts"])
    assert all(item["reason"] == "no_acquisition_record_established" for item in payload["withheld_facts"])
    assert AcquisitionProvenance.model_validate(payload) == provenance

    legacy = dict(payload)
    legacy["withheld_facts"] = [{"fact": "station.station_id", "reason": "acquisition_not_established"}]
    with pytest.raises(ValidationError, match="fact_group"):
        AcquisitionProvenance.model_validate(legacy)

    mixed = dict(payload)
    mixed["withheld_facts"] = [
        {
            "fact_group": "station_identity",
            "facts": ["station.station_id"],
            "reason": "acquisition_not_established",
        }
    ]
    with pytest.raises(ValidationError, match="no_acquisition_record_established"):
        AcquisitionProvenance.model_validate(mixed)
