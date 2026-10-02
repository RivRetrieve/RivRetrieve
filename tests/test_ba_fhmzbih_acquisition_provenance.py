import json
import shutil
from pathlib import Path

import polars as pl
import pytest
from pydantic import TypeAdapter, ValidationError

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, verify_provenance_recordings
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue import main
from rivretrieve._internal.providers.ba_fhmzbih.origins import WorkbookAccessLedger, build_acquisition_provenance
from tests._provenance import legacy_document, write_evidence_table

_LEDGER = Path("maintenance/catalogue/ba_fhmzbih/inventory/baseline_workbook_access.json")


def _provenance():
    return build_acquisition_provenance(TypeAdapter(WorkbookAccessLedger).validate_json(_LEDGER.read_bytes()))


def _withheld_document():
    document = legacy_document(Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/provenance.json"))
    document["withheld_facts"].append(
        {
            "fact_group": "test_withheld_station",
            "facts": ["station:1010.identity_location"],
            "reason": "no_acquisition_record_established",
            "catalogue_rows": [{"carrier": "station", "station_id": "1010", "product_id": None}],
        }
    )
    document["fact_universe"].append("station:1010.identity_location")
    return document


def _withheld_v3_document(directory: Path) -> dict:
    facts = pl.read_parquet(directory / "provenance_facts.parquet")
    added = pl.DataFrame(
        {
            "fact_id": [facts.height],
            "name": ["station:1010.identity_location"],
            "carrier": [None],
            "station_id": [None],
            "product_id": [None],
            "locator_role": [None],
        },
        schema=facts.schema,
    )
    write_evidence_table(directory, "provenance_facts.parquet", pl.concat([facts, added]))
    header = json.loads((directory / "provenance.json").read_text())
    header["withheld_facts"].append(
        {
            "fact_group": "test_withheld_station",
            "facts": ["station:1010.identity_location"],
            "reason": "no_acquisition_record_established",
            "catalogue_rows": [{"carrier": "station", "station_id": "1010", "product_id": None}],
        }
    )
    return header


def test_bosnia_provenance_binds_baseline_to_actual_acquisitions() -> None:
    provenance = _provenance()
    bound = {fact for binding in provenance.fact_bindings for fact in binding.facts}
    assert not provenance.withheld_facts
    assert len([fact for fact in bound if fact.startswith("source.station:")]) == 60
    assert len([fact for fact in bound if fact.startswith("source.observation:")]) == 60
    assert len([fact for fact in bound if fact.startswith("station_product:")]) == 180
    assert set(provenance.fact_universe) == bound
    workbook_acquisitions = {a.acquisition_id: a for a in provenance.source_records[0].acquisitions if a.material}
    assert len(workbook_acquisitions) == 180
    ledger = TypeAdapter(WorkbookAccessLedger).validate_json(_LEDGER.read_bytes())
    for pair in ledger.pairs:
        acquisition = workbook_acquisitions[pair.acquisition_id]
        assert acquisition.recording_ids == ()
        assert acquisition.requested_from == (pair.url,)
        assert acquisition.retrieved_at_start == pair.retrieved_at
        assert acquisition.material.sha256 == pair.response_sha256
        assert acquisition.material.byte_count == pair.byte_size
        binding = next(b for b in provenance.fact_bindings if b.facts == (pair.source_fact,))
        assert binding.acquisition_id == pair.acquisition_id
        availability = next(
            b
            for b in provenance.fact_bindings
            if b.facts == (f"station_product:{pair.station_no}:{pair.product_id}.availability",)
        )
        assert availability.transformation.external_inputs[0].fact == pair.source_fact


def test_bosnia_terms_recording_and_native_bytes_are_verified(tmp_path: Path, retained_evidence_root: Path) -> None:
    verify_provenance_recordings(_provenance(), retained_evidence_root)
    evidence = Path("tests/test_data/ba_fhmzbih_terms_absence.html")
    for source in _provenance().source_records:
        for entry in source.evidence:
            if entry.recording is not None:
                capture = Path(entry.recording.repository_path)
                target_capture = tmp_path / capture
                target_capture.parent.mkdir(parents=True, exist_ok=True)
                target_capture.write_bytes((retained_evidence_root / capture).read_bytes())
    target = tmp_path / evidence
    target.write_bytes((retained_evidence_root / evidence).read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="ba_fhmzbih_terms_absence digest mismatch"):
        verify_provenance_recordings(_provenance(), tmp_path)
    native = tmp_path / "native.parquet"
    shutil.copy2(
        retained_evidence_root / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet", native
    )
    native.write_bytes(native.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="native table digest mismatch"):
        main(
            [
                "--native",
                str(native),
                "--workbook-access-ledger",
                str(_LEDGER),
                "--series-recording",
                str(retained_evidence_root / "tests/test_data/ba_fhmzbih_metadata_index.recording.json"),
                "--evidence-root",
                str(retained_evidence_root),
                "--out",
                str(tmp_path / "out"),
            ]
        )


def test_bosnia_row_scoped_fact_rejects_a_detached_locator_in_real_loader(tmp_path: Path) -> None:
    source = Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue")
    mutated = tmp_path / "catalogue"
    shutil.copytree(source, mutated)
    document = _withheld_v3_document(mutated)
    withheld = next(item for item in document["withheld_facts"] if item["facts"] == ["station:1010.identity_location"])
    withheld["catalogue_rows"][0]["station_id"] = "DOES_NOT_EXIST"
    (mutated / "provenance.json").write_text(json.dumps(document))

    with pytest.raises(CorruptCatalogArtifactError, match="scoped fact identity|catalogue row locator"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")


def test_bosnia_row_scoped_fact_model_rejects_a_detached_locator() -> None:
    document = _withheld_document()
    withheld = next(item for item in document["withheld_facts"] if item["facts"] == ["station:1010.identity_location"])
    withheld["catalogue_rows"][0]["station_id"] = "DOES_NOT_EXIST"

    with pytest.raises(ValidationError, match="scoped fact identity|catalogue row locator"):
        AcquisitionProvenance.model_validate(document)


def test_bosnia_row_scoped_fact_model_requires_its_locator() -> None:
    document = _withheld_document()
    withheld = next(item for item in document["withheld_facts"] if item["facts"] == ["station:1010.identity_location"])
    withheld["catalogue_rows"] = []

    with pytest.raises(ValidationError, match="catalogue row locator|scoped fact identity"):
        AcquisitionProvenance.model_validate(document)


def test_bosnia_real_loader_rejects_exposed_row_when_withheld_locator_is_removed(tmp_path: Path) -> None:
    source = Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue")
    mutated = tmp_path / "catalogue"
    shutil.copytree(source, mutated)
    document = _withheld_v3_document(mutated)
    withheld = next(item for item in document["withheld_facts"] if item["facts"] == ["station:1010.identity_location"])
    withheld["catalogue_rows"] = []
    (mutated / "provenance.json").write_text(json.dumps(document))

    with pytest.raises(CorruptCatalogArtifactError, match="catalogue row locator|scoped fact identity"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")
