from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import (
    CorruptCatalogArtifactError,
    load_packaged_catalogue_artifact,
)
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.jp_mlit.declaration import declaration


def test_japan_provenance_is_shared_by_catalogue_result_and_selection() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue)
    assert artifact.acquisition_provenance is not None
    result = CatalogueReader(artifact, ProviderId(artifact.acquisition_provenance.provider_id)).read_stations()
    selection = rr.find(
        provider="jp_mlit",
        station="301011281104010",
        product="discharge_daily_mean",
    )

    assert result.provenance.acquisition_provenance == artifact.acquisition_provenance
    assert selection.acquisition_provenance == (artifact.acquisition_provenance,)
    assert rr.as_frame(selection).columns == [
        "provider_id",
        "station_id",
        "product_id",
        "latitude",
        "longitude",
        "crs",
        "observed_property",
        "frequency",
        "statistic",
        "period_type",
        "period_anchor",
        "unit",
        "native_id",
        "availability",
        "availability_reason",
        "published_record_start_date",
        "published_record_end_date",
        "last_catalogue_check",
    ]


def test_japan_source_and_fact_groups_are_externally_observable() -> None:
    selection = rr.find(provider="jp_mlit", station="301011281104010")
    provenance = selection.acquisition_provenance[0]

    source = provenance.source_records[0]
    assert source.source_id == "jp_mlit"
    assert source.issuer == "Ministry of Land, Infrastructure, Transport and Tourism"
    assert source.operator == "MLIT Water Information System"
    assert {statement.kind for statement in source.statements} == {"license", "citation"}
    assert {binding.fact_group for binding in provenance.fact_bindings} == {
        "provider_catalogue",
        "product_catalogue",
        "station_catalogue",
        "station_product_catalogue",
        "observation_acquisition",
    }
    observation = next(
        binding for binding in provenance.fact_bindings if binding.fact_group == "observation_acquisition"
    )
    assert observation.acquisition_id == "observation_request"
    assert "observation.value" in observation.facts
    assert provenance.withheld_facts == ()
    assert provenance.native_table.revision == "ebeee6673f183a2bd182e81ee2b4bff7d56ee009"
    assert provenance.native_table.sha256 == "ec892e4bc5bee3e8d5435190f4163ecddd80d2d244a71c810b9cf666d06b5aad"


def test_packaged_catalogue_rejects_mismatched_provenance_provider(tmp_path: Path) -> None:
    for name in (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
    ):
        shutil.copy2(declaration.catalogue / name, tmp_path / name)
    payload = json.loads((tmp_path / "provenance.json").read_text())
    payload["provider_id"] = "other_provider"
    (tmp_path / "provenance.json").write_text(json.dumps(payload))

    with pytest.raises(
        CorruptCatalogArtifactError,
        match="provenance.json provider_id does not match provider.json provider_id",
    ):
        load_packaged_catalogue_artifact(tmp_path)


def _copy_japan_catalogue(destination: Path, *, include_provenance: bool = True) -> None:
    names = ["provider.json", "products.parquet", "stations.parquet", "station_products.parquet"]
    if include_provenance:
        names.append("provenance.json")
    for name in names:
        shutil.copy2(declaration.catalogue / name, destination / name)


def test_enrolled_japan_catalogue_refuses_missing_provenance(tmp_path: Path) -> None:
    _copy_japan_catalogue(tmp_path, include_provenance=False)

    with pytest.raises(CorruptCatalogArtifactError, match="jp_mlit acquisition provenance is required"):
        load_packaged_catalogue_artifact(tmp_path, on_issue="raise")


def test_withheld_japan_fact_is_removed_from_exposed_catalogue(tmp_path: Path) -> None:
    _copy_japan_catalogue(tmp_path)
    payload = json.loads((tmp_path / "provenance.json").read_text())
    product_binding = next(item for item in payload["fact_bindings"] if item["fact_group"] == "product_catalogue")
    product_binding["facts"].remove("product.native_id")
    payload["withheld_facts"].append({"fact": "product.native_id", "reason": "acquisition_not_established"})
    (tmp_path / "provenance.json").write_text(json.dumps(payload))

    artifact = load_packaged_catalogue_artifact(tmp_path, on_issue="raise")

    assert artifact.products["native_id"].null_count() == artifact.products.height
    assert artifact.acquisition_provenance is not None
    assert {fact.fact for fact in artifact.acquisition_provenance.withheld_facts} == {"product.native_id"}


def test_enrolled_japan_catalogue_refuses_unbound_declared_fact(tmp_path: Path) -> None:
    _copy_japan_catalogue(tmp_path)
    payload = json.loads((tmp_path / "provenance.json").read_text())
    product_binding = next(item for item in payload["fact_bindings"] if item["fact_group"] == "product_catalogue")
    product_binding["facts"].remove("product.unit")
    (tmp_path / "provenance.json").write_text(json.dumps(payload))

    with pytest.raises(
        CorruptCatalogArtifactError,
        match="fact universe contains unaccounted facts.*product.unit",
    ):
        load_packaged_catalogue_artifact(tmp_path, on_issue="raise")


def test_withheld_required_japan_fact_removes_affected_rows_and_edges(tmp_path: Path) -> None:
    _copy_japan_catalogue(tmp_path)
    payload = json.loads((tmp_path / "provenance.json").read_text())
    product_binding = next(item for item in payload["fact_bindings"] if item["fact_group"] == "product_catalogue")
    product_binding["facts"].remove("product.unit")
    payload["withheld_facts"].append({"fact": "product.unit", "reason": "acquisition_not_established"})
    (tmp_path / "provenance.json").write_text(json.dumps(payload))

    artifact = load_packaged_catalogue_artifact(tmp_path, on_issue="raise")

    assert artifact.products.is_empty()
    assert artifact.station_products.is_empty()
    assert artifact.stations.height == 1023
