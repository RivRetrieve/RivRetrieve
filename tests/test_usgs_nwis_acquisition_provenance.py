from __future__ import annotations

from pathlib import Path

import pytest

from rivretrieve._internal.acquisition_provenance import verify_provenance_recordings
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis import generate_catalogue
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.providers.usgs_nwis.origins import build_acquisition_provenance


def test_usgs_provenance_names_nwis_and_verified_source_words() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    source = provenance.header.source_records[0]
    assert source.issuer == "U.S. Geological Survey"
    assert {statement.kind for statement in source.statements} == {"license", "citation"}
    assert provenance.header.native_table.sha256 == "90fede218826b640963e98515a6e3c4c106bf310a2e5bcf1606f805b55d5e701"
    assert provenance.header.native_table.byte_size == 14_093_302
    assert provenance.header.withheld_facts == ()


def test_usgs_build_rejects_changed_terms_recording(tmp_path: Path) -> None:
    source = Path("tests/test_data")
    target = tmp_path / "tests/test_data"
    target.mkdir(parents=True)
    (target / "usgs_nwis_terms_licence-1.html").write_bytes(
        (source / "usgs_nwis_terms_licence-1.html").read_bytes() + b"changed"
    )
    (target / "usgs_nwis_terms_citation-1.html").write_bytes((source / "usgs_nwis_terms_citation-1.html").read_bytes())
    (target / "usgs_nwis_instantaneous_values_definition.html").write_bytes(
        (source / "usgs_nwis_instantaneous_values_definition.html").read_bytes()
    )
    with pytest.raises(FatalContractError, match="usgs_nwis_terms_licence.*digest mismatch"):
        verify_provenance_recordings(build_acquisition_provenance(), tmp_path)


def test_usgs_cli_rejects_native_byte_substitution(tmp_path: Path) -> None:
    native = tmp_path / "native.parquet"
    native.write_bytes((declaration.catalogue / "native.parquet").read_bytes() + b"changed")
    with pytest.raises(FatalContractError, match="native table digest mismatch: expected .* observed"):
        generate_catalogue.main(
            [
                "--native",
                str(native),
                "--modern-metadata",
                "research/usgs-modern-coverage",
                "--out",
                str(tmp_path / "out"),
            ]
        )


def test_usgs_cli_invokes_recording_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*_args: object) -> None:
        raise FatalContractError("recording verification invoked")

    monkeypatch.setattr(generate_catalogue, "verify_provenance_recordings", reject)
    with pytest.raises(FatalContractError, match="recording verification invoked"):
        generate_catalogue.main(
            [
                "--native",
                str(declaration.catalogue / "native.parquet"),
                "--modern-metadata",
                "research/usgs-modern-coverage",
                "--out",
                str(tmp_path),
            ]
        )
