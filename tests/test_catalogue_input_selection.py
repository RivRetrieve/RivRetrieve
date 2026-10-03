"""Synthetic checks of explicit catalogue adoption, separate from archive acceptance."""

from hashlib import sha256

import pytest

from rivretrieve._internal.acquisition_provenance import RetainedInputReceipt
from rivretrieve._internal.catalogues.inputs import select_catalogue_build_inputs, verify_retained_input_files
from rivretrieve._internal.issues import FatalContractError
from tests.test_catalogue_build_provenance import _provenance, _reference


def _receipt(*references, declaration_revision="d" * 40):
    return RetainedInputReceipt(
        schema_version=2, code_revision="d" * 40, declaration_revision=declaration_revision, inputs=references
    )


def test_selection_adopts_declared_members_not_whole_composed_receipt():
    native = _reference(consumer_path="historical/native.parquet")
    unrelated = _reference(consumer_path="retained/unrelated.bin", artifact_id="unrelated")
    result = select_catalogue_build_inputs(
        _provenance(),
        _receipt(native, unrelated),
        ("historical-acquisition",),
        (("src/synthetic/origins.py", "build_acquisition_provenance"),),
    )
    assert len(result.inputs) == 1
    assert result.inputs[0].reference.model_dump() == native.model_dump(exclude={"consumer_path"})
    assert "consumer_path" not in result.model_dump_json()
    assert result.inputs[0].usage == "native_table"
    assert result.inputs[0].reference.role == "derived_input"
    assert result.inputs[0].facts == ("native.latitude",)
    assert result.build.revision == "d" * 40
    assert {reference.revision for reference in result.declarations} == {"d" * 40}


@pytest.mark.parametrize("defect", ["missing_native", "wrong_hash", "wrong_acquisition", "different_declarations"])
def test_adoption_cannot_replace_required_selected_identity(defect):
    reference = _reference(
        consumer_path="historical/native.parquet", sha256=("a" if defect == "wrong_hash" else "c") * 64
    )
    receipt = _receipt(
        *(() if defect == "missing_native" else (reference,)),
        declaration_revision=("e" if defect == "different_declarations" else "d") * 40,
    )
    acquisitions = ("absent",) if defect == "wrong_acquisition" else ("historical-acquisition",)
    with pytest.raises(FatalContractError):
        select_catalogue_build_inputs(
            _provenance(), receipt, acquisitions, (("src/synthetic/origins.py", "build_acquisition_provenance"),)
        )


def test_input_verification_checks_bytes_and_rejects_root_escape(tmp_path):
    root = tmp_path / "inputs"
    root.mkdir()
    body = b"synthetic retained scalar input"
    (root / "native.bin").write_bytes(body)
    reference = _reference(consumer_path="native.bin", sha256=sha256(body).hexdigest(), byte_size=len(body))
    receipt = _receipt(reference)
    verify_retained_input_files(receipt, root)
    (root / "native.bin").write_bytes(b"different")
    with pytest.raises(FatalContractError):
        verify_retained_input_files(receipt, root)
    (root / "native.bin").unlink()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(body)
    (root / "native.bin").symlink_to(outside)
    with pytest.raises(FatalContractError, match="escapes"):
        verify_retained_input_files(receipt, root)


def _support(path="body.bin", family="ba_fhmzbih", **changes):
    from rivretrieve._internal.acquisition_provenance import RetainedSupportReference

    return RetainedSupportReference(
        **_reference().model_dump(exclude={"consumer_path"}),
        provider_id=family,
        verifier_path=path,
        verification_kind="full_positive",
        **changes,
    )


def test_support_joins_exact_ledger_location_and_omits_unused_collection_entries():
    from rivretrieve._internal.catalogues.inputs import select_catalogue_support

    first = _support()
    unrelated = _support("unused.bin")
    other_family = _support(family="th_thaiwater")
    receipt = _receipt().model_copy(update={"support_inputs": (first, unrelated, other_family)})
    result = select_catalogue_support(
        _provenance(),
        receipt,
        family="ba_fhmzbih",
        locations={"historical-acquisition": ("body.bin",)},
        verifier_location=("maintenance/synthetic/verify.py", "main"),
    )
    assert len(result) == 1
    assert result[0].facts == ("native.latitude",)
    assert result[0].verification_kind == "full_positive"
    assert result[0].verifier.revision == receipt.code_revision
    assert "verifier_path" not in result[0].model_dump_json()
    assert "unused.bin" not in result[0].model_dump_json()


@pytest.mark.parametrize("defect", ["absent", "other_family", "wrong_path", "unknown_acquisition"])
def test_support_never_substitutes_missing_or_mismatched_ledger_member(defect):
    from rivretrieve._internal.catalogues.inputs import select_catalogue_support

    supports = (
        () if defect == "absent" else (_support(family="th_thaiwater" if defect == "other_family" else "ba_fhmzbih"),)
    )
    receipt = _receipt().model_copy(update={"support_inputs": supports})
    locations = {
        "absent-acquisition" if defect == "unknown_acquisition" else "historical-acquisition": (
            "wrong.bin" if defect == "wrong_path" else "body.bin",
        )
    }
    with pytest.raises(FatalContractError):
        select_catalogue_support(
            _provenance(),
            receipt,
            family="ba_fhmzbih",
            locations=locations,
            verifier_location=("maintenance/synthetic/verify.py", "main"),
        )


def test_nested_support_keeps_outer_archive_and_inner_material_identities_separate():
    from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
    from rivretrieve._internal.catalogues.inputs import select_catalogue_support

    document = _provenance().model_dump(mode="python")
    document["source_records"][0]["acquisitions"][0]["material"] = {
        "filename": "bundle.tar.xz!bodies/source.body",
        "byte_count": 12,
        "sha256": "e" * 64,
    }
    provenance = AcquisitionProvenance.model_validate(document)
    receipt = _receipt().model_copy(update={"support_inputs": (_support("bundle.tar.xz"),)})
    result = select_catalogue_support(
        provenance,
        receipt,
        family="ba_fhmzbih",
        locations={"historical-acquisition": ("bundle.tar.xz!bodies/source.body",)},
        verifier_location=("maintenance/synthetic/verify.py", "main"),
    )
    assert result[0].reference.sha256 == "c" * 64
    assert result[0].member_selector == "bodies/source.body"
    assert provenance.source_records[0].acquisitions[0].material.sha256 == "e" * 64
    with pytest.raises(FatalContractError, match="inner material"):
        select_catalogue_support(
            provenance,
            receipt,
            family="ba_fhmzbih",
            locations={"historical-acquisition": ("bundle.tar.xz!bodies/other.body",)},
            verifier_location=("maintenance/synthetic/verify.py", "main"),
        )


def test_recording_wrapper_and_source_body_keep_distinct_hashes_and_acquisition(tmp_path):
    from dataclasses import replace
    from datetime import UTC, datetime

    from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
    from rivretrieve._internal.catalogues.inputs import verify_recording_envelopes
    from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, write_recording
    from rivretrieve._internal.transport import HttpMethod

    envelope = RecordingEnvelope(
        RecordedRequest(HttpMethod.GET, "https://example.org/source"),
        b'{"synthetic":1}',
        200,
        datetime(2020, 1, 1, tzinfo=UTC),
        "application/json",
    )
    path = tmp_path / "source.recording.json"
    write_recording(envelope, path)
    document = _provenance().model_dump(mode="python")
    source = document["source_records"][0]
    source["acquisitions"][0]["recording_ids"] = ("source",)
    source["evidence"] = (
        {
            "evidence_id": "source",
            "description": "Synthetic recording wrapper",
            "recording": {
                "recording_id": "source",
                "repository_path": path.name,
                "source_url": envelope.request.url,
                "retrieved_at": envelope.retrieved_at,
                "media_type": envelope.content_type,
                "sha256": envelope.sha256,
            },
        },
    )
    provenance = AcquisitionProvenance.model_validate(document)

    def receipt():
        body = path.read_bytes()
        return _receipt(_reference(consumer_path=path.name, sha256=sha256(body).hexdigest(), byte_size=len(body)))

    selected = receipt()
    assert selected.inputs[0].sha256 != envelope.sha256
    assert verify_recording_envelopes(provenance, selected, tmp_path) == {path.name: selected.inputs[0].sha256}
    write_recording(replace(envelope, retrieved_at=datetime(2021, 1, 1, tzinfo=UTC)), path)
    with pytest.raises(FatalContractError, match="acquisition"):
        verify_recording_envelopes(provenance, receipt(), tmp_path)
