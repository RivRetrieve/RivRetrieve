"""Acquired stations and withheld products remain distinct at the packaged boundary."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest
from pydantic import ValidationError

import rivretrieve as rr
from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, verify_provenance_recordings
from rivretrieve._internal.catalogues.artifact import (
    CorruptCatalogArtifactError,
    load_packaged_catalogue_artifact,
)
from tests._catalogue import catalogue_path, catalogue_reader
from tests._provenance import legacy_provenance


def test_brazil_inventory_and_adopted_candidates_are_certified() -> None:
    from rivretrieve._internal.providers.br_ana.capture import read_capture_record

    capture = read_capture_record(Path(__file__).parent / "test_data/br_ana_inventory/capture.json")
    artifact = load_packaged_catalogue_artifact(catalogue_path("br_ana"), on_issue="raise")
    assert artifact.stations.height == capture.fluviometric_station_count
    assert set(artifact.products["product_id"]) == {
        "discharge_daily_mean_bruto",
        "discharge_daily_mean_consistido",
        "discharge_instantaneous",
        "stage_daily_mean_bruto",
        "stage_daily_mean_consistido",
        "stage_instantaneous",
    }
    assert artifact.station_products.height == 6 * capture.fluviometric_station_count
    assert set(artifact.station_products["station_id"]) == set(artifact.stations["station_id"])
    available = artifact.station_products.filter(pl.col("availability") == "available")
    assert set(available["station_id"]) == {"15400000"} and available.height == 6
    assert set(artifact.station_products["availability"].cast(pl.String)) == {"available", "unknown"}
    evidence = artifact.acquisition_provenance
    assert evidence is not None
    assert evidence.header.native_table == capture.native_table
    withheld = {fact for group in evidence.header.withheld_facts for fact in group.facts}
    assert not any(fact.startswith("station.") for fact in withheld)
    assert not any(fact.startswith(("product.", "station_product.")) for fact in withheld)
    assert "source.ana.adopted_endpoint_availability_unacquired" in withheld
    assert "source.ana.adopted_published_record_unacquired" in withheld
    assert evidence.facts.filter(pl.col("locator_role") == "availability").height == artifact.station_products.height
    assert artifact.provider_info["license"] is not None
    assert artifact.provider_info["citation"] is None


def test_brazil_discovery_exposes_only_documented_adopted_products() -> None:
    assert "br_ana" in rr.providers().get_column("provider_id").to_list()
    assert rr.products(provider="br_ana") == [
        "discharge_daily_mean_bruto",
        "discharge_daily_mean_consistido",
        "discharge_instantaneous",
        "stage_daily_mean_bruto",
        "stage_daily_mean_consistido",
        "stage_instantaneous",
    ]
    reader = catalogue_reader("br_ana")
    assert not reader.read_stations().data.is_empty()
    assert reader.read_products().data.height == 6
    assert reader.read_station_products().data.height == 6 * reader.read_stations().data.height


def test_brazil_unacquired_station_support_is_not_source_silence() -> None:
    brazil = load_packaged_catalogue_artifact(catalogue_path("br_ana"), on_issue="raise")
    evidence = brazil.acquisition_provenance
    assert evidence is not None
    assert {group.reason for group in evidence.header.withheld_facts} == {"no_acquisition_record_established"}
    japan = load_packaged_catalogue_artifact(catalogue_path("jp_mlit"), on_issue="raise")
    assert japan.provider_info["license"] is None
    origins_text = (catalogue_path("jp_mlit").parent / "origins.py").read_text(encoding="utf-8")
    assert "NotPublished" in origins_text


def test_brazil_requires_provenance_at_the_packaged_boundary(tmp_path: Path) -> None:
    copied = tmp_path / "br_ana"
    shutil.copytree(catalogue_path("br_ana"), copied)
    (copied / "provenance.json").unlink()
    with pytest.raises(CorruptCatalogArtifactError, match="br_ana acquisition provenance is required"):
        load_packaged_catalogue_artifact(copied, on_issue="raise")


def test_brazil_selection_retains_unknown_candidate_reason_and_source_evidence() -> None:
    artifact = load_packaged_catalogue_artifact(catalogue_path("br_ana"))
    candidate = artifact.station_products.filter(
        (pl.col("availability") == "unknown") & (pl.col("product_id") == "stage_instantaneous")
    ).row(0, named=True)
    selection = rr.find(provider="br_ana", station=candidate["station_id"], quantity="stage", statistic="instantaneous")
    assert selection.empty_reason is None
    assert len(selection.acquisition_provenance) == 1
    assert selection.acquisition_provenance[0].header.withheld_facts
    unknown = selection.series[0]
    selected = rr.pick(selection, series_id=unknown.series_id)
    assert selected.series == (unknown,)
    assert (
        "inventory membership does not establish adopted-endpoint product availability"
        in candidate["availability_reason"]
    )
    assert candidate["published_record_start_date"] is candidate["published_record_end_date"] is None
    assert all(inventory.completeness.value == "incomplete" for inventory in selected.inventories)


def test_packaged_evidence_rejects_retired_schema(tmp_path: Path) -> None:
    copied = tmp_path / "jp_mlit"
    shutil.copytree(catalogue_path("jp_mlit"), copied)
    payload = json.loads((copied / "provenance.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    payload["schema_version"] = 1
    (copied / "provenance.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorruptCatalogArtifactError, match="schema|version"):
        load_packaged_catalogue_artifact(copied, on_issue="raise")


def test_acquisition_provenance_v2_rejects_legacy_and_mixed_withheld_shapes() -> None:
    provenance = load_packaged_catalogue_artifact(catalogue_path("br_ana"), on_issue="raise").acquisition_provenance
    assert provenance is not None
    provenance = legacy_provenance(provenance)
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


def test_deferred_public_terms_are_traced_without_republishing_catalogue_values() -> None:
    expected = {
        "br_ana": {"license"},
        "no_nve": {"license", "citation"},
    }
    for provider_id, kinds in expected.items():
        artifact = load_packaged_catalogue_artifact(catalogue_path(provider_id), on_issue="raise")
        provenance = artifact.acquisition_provenance
        assert provenance is not None
        assert (
            not artifact.products.is_empty()
            and not artifact.stations.is_empty()
            and not artifact.station_products.is_empty()
        )
        if provider_id == "br_ana":
            assert set(artifact.products["product_id"]) == {
                "discharge_daily_mean_bruto",
                "discharge_daily_mean_consistido",
                "discharge_instantaneous",
                "stage_daily_mean_bruto",
                "stage_daily_mean_consistido",
                "stage_instantaneous",
            }
        statements = [statement for source in provenance.header.source_records for statement in source.statements]
        assert {statement.kind for statement in statements} == kinds
        assert all(statement.verification_status == "verified_public_recording" for statement in statements)
        if provider_id == "no_nve":
            verify_provenance_recordings(legacy_provenance(provenance), Path.cwd())
        else:
            terms_source = next(
                source for source in provenance.header.source_records if source.source_id == "br_ana.terms"
            )
            for item in terms_source.evidence:
                assert (
                    hashlib.sha256((Path.cwd() / item.recording.repository_path).read_bytes()).hexdigest()
                    == item.recording.sha256
                )
        # ANA compressed inventory recordings are verified by its capture materialization tests;
        # verify_provenance_recordings expects direct source bodies, not RecordingEnvelopes.


@pytest.mark.parametrize(
    ("provider_id", "expected_url", "expected_instant", "expected_sha256", "expected_statements"),
    (
        (
            "br_ana",
            "https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos",
            "2026-08-21T09:30:30Z",
            "fdf143188469d23a9e2d4429c2a956d8fc311882a9a7e5d255f27e698ec3334f",
            {
                "source.ana.open_data_license_statement": "Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem restrição de licenças, patentes ou mecanismos de controle."
            },
        ),
        (
            "no_nve",
            "https://hydapi.nve.no/UserDocumentation/",
            "2026-08-21T09:19:38Z",
            "d66c35806f7f62ac5fb95fa4219f80a8c2690c7e8ae4bdc022c770a684fa9f8a",
            {
                "source.nve.license_statement": "The data provided by the API is licensed under the Norwegian License for Open Government Data (NLOD) which is compatible with CC Navngivelse 3.0 Norge (CC BY 3.0).",
                "source.nve.citation_statement": "When using data from this service, if possible, please refer to this service as origin of data.",
            },
        ),
    ),
)
def test_deferred_terms_match_completed_survey_exactly(
    provider_id: str,
    expected_url: str,
    expected_instant: str,
    expected_sha256: str,
    expected_statements: dict[str, str],
) -> None:
    provenance = load_packaged_catalogue_artifact(catalogue_path(provider_id), on_issue="raise").acquisition_provenance
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    source = provenance.source_records[0]
    acquisition = source.acquisitions[0]
    recording = source.evidence[0].recording
    assert acquisition.requested_from == (expected_url,)
    assert acquisition.retrieved_at_start is not None
    assert acquisition.retrieved_at_start.isoformat().replace("+00:00", "Z") == expected_instant
    assert recording.source_url == expected_url
    assert recording.sha256 == expected_sha256
    assert {statement.fact: statement.exact_text for statement in source.statements} == expected_statements


def test_packaged_reader_normalizes_genuine_v2_to_the_same_evidence(tmp_path: Path) -> None:
    """Exercise the deliberate v2 file compatibility boundary, not a runtime facade."""
    copied = tmp_path / "jp_mlit"
    shutil.copytree(catalogue_path("jp_mlit"), copied)
    expected = load_packaged_catalogue_artifact(copied, on_issue="raise").acquisition_provenance
    assert expected is not None
    (copied / "provenance.json").write_text(legacy_provenance(expected).model_dump_json())
    actual = load_packaged_catalogue_artifact(copied, on_issue="raise").acquisition_provenance
    assert actual is not None
    assert actual.header.schema_version == 3
    # Encoded file identities may differ from a freshly normalized v2 value.
    assert legacy_provenance(actual).model_dump(mode="json") == legacy_provenance(expected).model_dump(mode="json")
    for name in ("facts", "acquisitions", "bindings", "binding_facts", "external_inputs"):
        pl_testing.assert_frame_equal(getattr(actual, name), getattr(expected, name), check_exact=True)
