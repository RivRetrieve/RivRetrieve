from pathlib import Path

import pytest

from rivretrieve._internal.acquisition_provenance import ExternalFactReference
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.za_dws import generate_catalogue
from rivretrieve._internal.providers.za_dws.declaration import declaration
from tests._provenance import legacy_provenance


def test_south_africa_provenance_separates_dws_issuer_from_archive_route() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    assert provenance is not None
    source = provenance.source_records[0]
    assert source.issuer == "South African Department of Water and Sanitation"
    assert source.operator == "DWS Verified Hydrology"
    assert "Internet Archive" in source.acquisitions[0].description
    assert source.statements == ()
    assert len(source.evidence) == 3
    assert provenance.native_table.sha256 == "6d122a3ae50e9bdb61599bce488bcf1045649cec2ec4b848177eccc328f56efd"
    assert provenance.native_table.byte_size == 67_655
    assert provenance.withheld_facts == ()


def test_south_africa_provenance_exposes_unsigned_dms_transformation() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    assert provenance is not None
    location = next(binding for binding in provenance.fact_bindings if binding.fact_group == "station_location")
    assert "source.station.dws_unsigned_dms" in location.facts
    assert location.transformation is None
    carrier = next(
        binding for binding in provenance.fact_bindings if binding.fact_group == "canonical_catalogue_carrier"
    )
    assert carrier.transformation is not None
    assert (
        ExternalFactReference(source_id="za_dws", fact="source.station.dws_unsigned_dms")
        in carrier.transformation.external_inputs
    )


def test_south_africa_cli_rejects_native_byte_substitution(retained_evidence_root: Path, tmp_path: Path) -> None:
    native = tmp_path / "native.parquet"
    native.write_bytes(
        (retained_evidence_root / "src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet").read_bytes()
        + b"changed"
    )
    with pytest.raises(FatalContractError, match="native table digest mismatch: expected .* observed"):
        generate_catalogue.main(
            ["--native", str(native), "--out", str(tmp_path / "out")] + ["--evidence-root", str(retained_evidence_root)]
        )


def test_south_africa_cli_invokes_recording_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_provenance: object, evidence_root: Path) -> None:
        assert evidence_root == tmp_path
        raise FatalContractError("recording verification invoked")

    monkeypatch.setattr(generate_catalogue, "verify_provenance_recordings", reject)
    with pytest.raises(FatalContractError, match="recording verification invoked"):
        generate_catalogue.main(
            [
                "--native",
                str(tmp_path / "native.parquet"),
                "--out",
                str(tmp_path),
            ]
            + ["--evidence-root", str(tmp_path)]
        )
