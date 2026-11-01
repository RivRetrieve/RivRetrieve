from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rivretrieve._internal.acquisition_provenance import verify_provenance_recordings
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis import generate_catalogue
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.providers.usgs_nwis.origins import build_acquisition_provenance
from tests.test_catalogue_origin_certification import _catalogue_recording_paths


def test_usgs_provenance_names_nwis_and_verified_source_words() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    source = provenance.header.source_records[0]
    assert source.issuer == "U.S. Geological Survey"
    assert {statement.kind for statement in source.statements} == {"license", "citation"}
    assert provenance.header.native_table.sha256 == "90fede218826b640963e98515a6e3c4c106bf310a2e5bcf1606f805b55d5e701"
    assert provenance.header.native_table.byte_size == 14_093_302
    assert provenance.header.withheld_facts == ()


@pytest.mark.governing(*_catalogue_recording_paths("usgs_nwis"))
def test_usgs_build_rejects_changed_terms_recording(retained_evidence_root, tmp_path: Path) -> None:
    provenance = build_acquisition_provenance()
    for source in provenance.source_records:
        for item in source.evidence:
            path = Path(item.recording.repository_path)
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(retained_evidence_root / path, target)
    verify_provenance_recordings(provenance, tmp_path)
    target = tmp_path / "tests/test_data/usgs_nwis_terms_licence-1.html"
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(FatalContractError, match="usgs_nwis_terms_licence.*digest mismatch"):
        verify_provenance_recordings(provenance, tmp_path)


@pytest.mark.governing(
    "research/usgs-modern-coverage",
    "research/usgs-modern-coverage/metadata-00060-0000.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0001.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0002.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0003.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0004.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0005.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0006.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0007.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0000.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0001.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0002.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0003.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0004.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0005.json.gz",
    "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet",
    "tests/test_data/usgs_nwis_instantaneous_values_definition.html",
    "tests/test_data/usgs_nwis_terms_citation-1.html",
    "tests/test_data/usgs_nwis_terms_licence-1.html",
)
def test_usgs_cli_rejects_native_byte_substitution(retained_evidence_root, tmp_path: Path) -> None:
    from tests.test_catalogue_build_provenance import _build

    # Synthetic selection reaches only the intended failing verification boundary.
    build_inputs_path = tmp_path / "synthetic-build-inputs.json"
    build_inputs_path.write_text(_build().model_dump_json(), encoding="utf-8")
    selected_provenance = tmp_path / "historical-provenance.json"
    selected_provenance.write_text(build_acquisition_provenance().model_dump_json())
    native = tmp_path / "native.parquet"
    native.write_bytes(
        (retained_evidence_root / "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet").read_bytes()
        + b"changed"
    )
    with pytest.raises(FatalContractError, match="native table digest mismatch: expected .* observed"):
        generate_catalogue.main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--acquisition-provenance",
                str(selected_provenance),
                "--native",
                str(native),
                "--evidence-root",
                str(retained_evidence_root),
                "--modern-metadata",
                str(retained_evidence_root / "research/usgs-modern-coverage"),
                "--out",
                str(tmp_path / "out"),
            ]
        )


@pytest.mark.governing(
    "research/usgs-modern-coverage",
    "research/usgs-modern-coverage/metadata-00060-0000.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0001.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0002.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0003.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0004.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0005.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0006.json.gz",
    "research/usgs-modern-coverage/metadata-00060-0007.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0000.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0001.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0002.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0003.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0004.json.gz",
    "research/usgs-modern-coverage/metadata-00065-0005.json.gz",
    "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet",
    "tests/test_data/usgs_nwis_instantaneous_values_definition.html",
    "tests/test_data/usgs_nwis_terms_citation-1.html",
    "tests/test_data/usgs_nwis_terms_licence-1.html",
)
def test_usgs_cli_invokes_recording_verification(
    retained_evidence_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_catalogue_build_provenance import _build

    # Synthetic selection reaches only the intended failing verification boundary.
    build_inputs_path = tmp_path / "synthetic-build-inputs.json"
    build_inputs_path.write_text(_build().model_dump_json(), encoding="utf-8")
    selected_provenance = tmp_path / "historical-provenance.json"
    selected_provenance.write_text(build_acquisition_provenance().model_dump_json())

    def reject(*_args: object) -> None:
        raise FatalContractError("recording verification invoked")

    monkeypatch.setattr(generate_catalogue, "verify_provenance_recordings", reject)
    with pytest.raises(FatalContractError, match="recording verification invoked"):
        generate_catalogue.main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--acquisition-provenance",
                str(selected_provenance),
                "--native",
                str(retained_evidence_root / "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet"),
                "--evidence-root",
                str(retained_evidence_root),
                "--modern-metadata",
                str(retained_evidence_root / "research/usgs-modern-coverage"),
                "--out",
                str(tmp_path),
            ]
        )


def test_selected_native_provenance_credits_each_actual_event_not_historical_campaign():
    from datetime import UTC, datetime

    from rivretrieve._internal.acquisition_provenance import AcquisitionRecord, NativeTableIdentity
    from rivretrieve._internal.providers.usgs_nwis.origins import selected_native_provenance

    events = tuple(
        AcquisitionRecord(
            acquisition_id=name,
            method="http_request",
            instant_type="retrieval",
            description="Synthetic selected station source",
            requested_from=("https://example.org/" + name,),
            retrieved_at_start=datetime(2026, 10, 31, tzinfo=UTC),
        )
        for name in ("original-first", "original-second", "supplement")
    )
    native = NativeTableIdentity(
        repository_path="selected/native.parquet",
        revision="a" * 40,
        sha256="b" * 64,
        byte_size=123,
        location_kind="retained",
    )
    result = selected_native_provenance(native, events, ())
    assert result.native_table == native
    bindings = {fact: item for item in result.fact_bindings for fact in item.facts}
    station = bindings["station.latitude"]
    dependencies = {item.fact for item in station.transformation.external_inputs}
    selected = [bindings[fact] for fact in dependencies if fact.startswith("source.station.selected_input_")]
    assert {item.acquisition_id for item in selected} == {"original-first", "original-second", "supplement"}
    assert "source.station.nwis_identity_location_datum" not in dependencies
    assert bindings["source.station.nwis_identity_location_datum"].acquisition_id == "national_site_campaign_2026_08_02"


@pytest.mark.parametrize("metadata_event", ["selected-metadata", "selected-native"])
def test_selected_modern_campaign_keeps_native_events_and_new_recording_root(tmp_path, metadata_event):
    from datetime import UTC, datetime

    from rivretrieve._internal.acquisition_provenance import AcquisitionRecord, NativeTableIdentity, RecordingReference
    from rivretrieve._internal.providers.usgs_nwis.origins import (
        build_modern_acquisition_provenance,
        selected_native_provenance,
    )

    event = AcquisitionRecord(
        acquisition_id="selected-native",
        method="http_request",
        instant_type="retrieval",
        description="Synthetic selected source",
        requested_from=("https://example.org/native",),
        retrieved_at_start=datetime(2026, 10, 31, tzinfo=UTC),
    )
    native = NativeTableIdentity(
        repository_path="selected/native.parquet", revision="a" * 40, sha256="b" * 64, byte_size=123
    )
    record = RecordingReference(
        recording_id="native-body",
        repository_path="research/selected/native.gz",
        source_url="https://example.org/native",
        retrieved_at=datetime(2026, 10, 31, tzinfo=UTC),
        media_type="application/gzip",
        sha256="c" * 64,
    )
    event = event.model_copy(update={"recording_ids": (record.recording_id,)})
    base = selected_native_provenance(native, (event,), (record,))
    (tmp_path / "page.json.gz").write_bytes(b"synthetic retained gzip member")
    receipts = [{"file": "page.json.gz", "url": "https://example.org/metadata", "retrieved_at": "2026-10-31T12:00:00Z"}]
    result = build_modern_acquisition_provenance(
        receipts,
        tmp_path,
        native_provenance=base,
        metadata_acquisition_id=metadata_event,
        metadata_recording_root="research/selected",
    )
    bindings = {fact: binding for binding in result.fact_bindings for fact in binding.facts}
    assert bindings["source.station_product.modern_series_availability"].acquisition_id == metadata_event
    for fact in ("station.latitude", "station.longitude", "station_product.availability"):
        dependencies = {item.fact for item in bindings[fact].transformation.external_inputs}
        assert "source.station.selected_input_0" in dependencies
        assert "source.station.nwis_identity_location_datum" not in dependencies
    recording = next(
        item.recording for item in result.source_records[0].evidence if item.evidence_id == "modern_metadata_0"
    )
    assert recording.repository_path == "research/selected/page.json.gz"
    assert result.native_table == native
    if metadata_event == "selected-native":
        merged = next(item for item in result.source_records[0].acquisitions if item.acquisition_id == metadata_event)
        assert set(merged.recording_ids) == {"native-body", "modern_metadata_0"}
        assert merged.retrieved_at_start == datetime(2026, 10, 31, tzinfo=UTC)
        assert merged.retrieved_at_end == datetime(2026, 10, 31, 12, tzinfo=UTC)


def test_selected_native_can_credit_explicit_retained_historical_event_once():
    from rivretrieve._internal.providers.usgs_nwis.origins import selected_native_provenance

    original = build_acquisition_provenance()
    result = selected_native_provenance(
        original.native_table, (), (), retained_acquisition_ids=("national_site_campaign_2026_08_02",)
    )
    events = [item.acquisition_id for item in result.source_records[0].acquisitions]
    assert events.count("national_site_campaign_2026_08_02") == 1
    bindings = {fact: binding for binding in result.fact_bindings for fact in binding.facts}
    assert bindings["source.station.selected_input_0"].acquisition_id == "national_site_campaign_2026_08_02"
    assert "source.station.selected_input_0" in {
        item.fact for item in bindings["station.latitude"].transformation.external_inputs
    }
    with pytest.raises(ValueError, match="Unknown retained acquisition"):
        selected_native_provenance(original.native_table, (), (), retained_acquisition_ids=("invented",))
