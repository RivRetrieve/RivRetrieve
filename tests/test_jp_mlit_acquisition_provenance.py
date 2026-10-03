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
from rivretrieve._internal.providers.jp_mlit.origins import build_acquisition_provenance
from tests._provenance import assert_evidence_equal, legacy_provenance, remove_binding_fact


def test_japan_provenance_is_shared_by_catalogue_result_and_selection() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue)
    assert artifact.acquisition_provenance is not None
    result = CatalogueReader(artifact, ProviderId(artifact.acquisition_provenance.header.provider_id)).read_stations()
    selection = rr.find(
        provider="jp_mlit",
        station="301011281104010",
        quantity="discharge",
        frequency="daily",
    )

    assert result.provenance.acquisition_provenance is artifact.acquisition_provenance
    assert len(selection.acquisition_provenance) == 1
    assert_evidence_equal(selection.acquisition_provenance[0], artifact.acquisition_provenance)
    frame = rr.as_frame(selection)
    assert frame["series_id"].to_list() == [selection.series[0].series_id]
    assert frame["source_unit"].to_list() == ["m3/s"]
    assert frame["frequency"].to_list() == ["daily"]
    assert frame["statistic"].to_list() == [None]
    assert frame["inventory_status"].to_list() == [["incomplete"]]


def test_japan_source_and_fact_groups_are_externally_observable() -> None:
    selection = rr.find(provider="jp_mlit", station="301011281104010")
    provenance = legacy_provenance(selection.acquisition_provenance[0])

    source = provenance.source_records[0]
    assert source.source_id == "jp_mlit"
    assert source.issuer == "Ministry of Land, Infrastructure, Transport and Tourism"
    assert source.operator == "MLIT Water Information System"
    assert {statement.kind for statement in source.statements} == {"license", "citation"}
    assert {binding.fact_group for binding in provenance.fact_bindings} == {
        "mlit_service_identity",
        "mlit_license_terms",
        "mlit_citation_instruction",
        "mlit_product_kind_semantics",
        "mlit_station_catalogue_inputs",
        "provider_identity",
        "provider_rivretrieve_carrier",
        "provider_license",
        "provider_citation",
        "product_catalogue",
        "station_catalogue",
        "station_product_catalogue",
        "observation_acquisition",
        "metadata.drainage_area.流域面積",
        "metadata.river_name.河川名",
        "metadata.station_name.観測所名",
    }
    observation = next(
        binding for binding in provenance.fact_bindings if binding.fact_group == "observation_acquisition"
    )
    assert observation.acquisition_id == "observation_request"
    assert "source.observation.value" in observation.facts
    assert provenance.withheld_facts == ()
    assert provenance.native_table is not None
    assert provenance.native_table.revision == "ebeee6673f183a2bd182e81ee2b4bff7d56ee009"
    assert provenance.native_table.sha256 == "ec892e4bc5bee3e8d5435190f4163ecddd80d2d244a71c810b9cf666d06b5aad"


def test_packaged_catalogue_rejects_mismatched_provenance_provider(tmp_path: Path) -> None:
    for name in (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
        "provenance_facts.parquet",
        "provenance_acquisitions.parquet",
        "provenance_bindings.parquet",
        "provenance_binding_facts.parquet",
        "provenance_external_inputs.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
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
    names = [
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
    ]
    if include_provenance:
        names.extend(
            (
                "provenance.json",
                "provenance_facts.parquet",
                "provenance_acquisitions.parquet",
                "provenance_bindings.parquet",
                "provenance_binding_facts.parquet",
                "provenance_external_inputs.parquet",
                "format.json",
                "source_series.json",
                "series_claims.parquet",
            )
        )
    for name in names:
        shutil.copy2(declaration.catalogue / name, destination / name)


def test_enrolled_japan_catalogue_refuses_missing_provenance(tmp_path: Path) -> None:
    _copy_japan_catalogue(tmp_path, include_provenance=False)

    with pytest.raises(CorruptCatalogArtifactError, match="jp_mlit acquisition provenance is required"):
        load_packaged_catalogue_artifact(tmp_path, on_issue="raise")


def test_withheld_japan_fact_is_removed_from_exposed_catalogue(tmp_path: Path) -> None:
    _copy_japan_catalogue(tmp_path)
    payload = json.loads((tmp_path / "provenance.json").read_text())
    remove_binding_fact(tmp_path, "product.native_id")
    payload = json.loads((tmp_path / "provenance.json").read_text())
    payload["withheld_facts"].append(
        {
            "fact_group": "withheld_product_native_id",
            "facts": ["product.native_id"],
            "reason": "no_acquisition_record_established",
        }
    )
    (tmp_path / "provenance.json").write_text(json.dumps(payload))

    artifact = load_packaged_catalogue_artifact(tmp_path, on_issue="raise")

    assert artifact.products["native_id"].null_count() == artifact.products.height
    assert artifact.acquisition_provenance is not None
    assert {fact for group in artifact.acquisition_provenance.header.withheld_facts for fact in group.facts} == {
        "product.native_id"
    }


def test_enrolled_japan_catalogue_refuses_unbound_declared_fact(tmp_path: Path) -> None:
    _copy_japan_catalogue(tmp_path)
    payload = json.loads((tmp_path / "provenance.json").read_text())
    remove_binding_fact(tmp_path, "product.unit")
    payload = json.loads((tmp_path / "provenance.json").read_text())
    (tmp_path / "provenance.json").write_text(json.dumps(payload))

    with pytest.raises(
        CorruptCatalogArtifactError,
        match="fact universe contains unaccounted facts.*product.unit",
    ):
        load_packaged_catalogue_artifact(tmp_path, on_issue="raise")


def test_withheld_required_japan_fact_removes_affected_rows_and_edges(tmp_path: Path) -> None:
    _copy_japan_catalogue(tmp_path)
    payload = json.loads((tmp_path / "provenance.json").read_text())
    remove_binding_fact(tmp_path, "product.unit")
    payload = json.loads((tmp_path / "provenance.json").read_text())
    payload["withheld_facts"].append(
        {
            "fact_group": "withheld_product_unit",
            "facts": ["product.unit"],
            "reason": "no_acquisition_record_established",
        }
    )
    (tmp_path / "provenance.json").write_text(json.dumps(payload))

    with pytest.raises(CorruptCatalogArtifactError, match="absent catalogue coordinates"):
        load_packaged_catalogue_artifact(tmp_path, on_issue="raise")
    # A coherent rebuild must also withdraw source descriptions for removed products.
    (tmp_path / "source_series.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider_id": "jp_mlit",
                "descriptions": [],
            }
        )
    )
    artifact = load_packaged_catalogue_artifact(tmp_path, on_issue="raise")

    assert artifact.products.is_empty()
    assert artifact.station_products.is_empty()
    assert artifact.stations.height == 1023


def test_japan_terms_facts_follow_their_exact_recorded_acquisitions() -> None:
    provenance = build_acquisition_provenance()
    source = provenance.source_records[0]
    acquisitions = {item.acquisition_id: item for item in source.acquisitions}

    licence = acquisitions["license_terms_capture_2026_08_21"]
    assert licence.method == "http_request"
    assert licence.instant_type == "retrieval"
    assert licence.requested_from == ("http://www1.river.go.jp/caution.html",)
    assert licence.retrieved_at_start.isoformat() == "2026-08-21T09:46:54+00:00"
    assert licence.recording_ids == ("jp_mlit_terms_licence_euc_jp",)

    citation = acquisitions["citation_terms_capture_2026_08_21"]
    assert citation.method == "http_request"
    assert citation.instant_type == "retrieval"
    assert citation.requested_from == ("http://www1.river.go.jp/WDBrules_20251210.pdf",)
    assert citation.retrieved_at_start.isoformat() == "2026-08-21T09:47:00+00:00"
    assert citation.recording_ids == ("jp_mlit_terms_citation",)

    statements = {item.kind: item for item in source.statements}
    assert statements["license"].recording_id == licence.recording_ids[0]
    assert statements["citation"].recording_id == citation.recording_ids[0]

    bindings = {item.fact_group: item for item in provenance.fact_bindings}
    assert bindings["mlit_service_identity"].facts == ("source.provider.service_identity",)
    assert bindings["mlit_service_identity"].acquisition_id == "station_register_capture_2026_08_02"
    assert bindings["mlit_license_terms"].facts == ("source.provider.license_terms",)
    assert bindings["mlit_license_terms"].acquisition_id == licence.acquisition_id
    assert bindings["mlit_citation_instruction"].facts == ("source.provider.citation_instruction",)
    assert bindings["mlit_citation_instruction"].acquisition_id == citation.acquisition_id

    provider_license = bindings["provider_license"]
    assert provider_license.facts == ("provider.license",)
    assert provider_license.transformation is not None
    assert tuple(item.model_dump() for item in provider_license.transformation.external_inputs) == (
        {"source_id": "jp_mlit", "fact": "source.provider.license_terms"},
    )
    provider_citation = bindings["provider_citation"]
    assert provider_citation.facts == ("provider.citation",)
    assert provider_citation.transformation is not None
    assert tuple(item.model_dump() for item in provider_citation.transformation.external_inputs) == (
        {"source_id": "jp_mlit", "fact": "source.provider.citation_instruction"},
    )

    authored = bindings["provider_rivretrieve_carrier"]
    assert authored.transformation is not None
    assert authored.transformation.kind == "authored_constant"
    assert authored.transformation.external_inputs == ()
