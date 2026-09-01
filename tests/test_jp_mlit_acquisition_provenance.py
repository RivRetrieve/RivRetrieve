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
        "station_identity_and_location",
        "product_identity",
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
