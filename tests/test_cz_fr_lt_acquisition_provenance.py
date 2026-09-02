from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.acquisition_provenance import verify_provenance_recordings
from rivretrieve._internal.issues import FatalContractError


@pytest.mark.parametrize(
    ("provider_id", "issuer", "terms_file"),
    [
        ("cz_chmi", "Czech Hydrometeorological Institute", "cz_chmi_terms_licence.html"),
        ("fr_hubeau", "Hub’Eau / SCHAPI", "fr_hubeau_terms_licence.html"),
        ("lt_lhmt", "Lithuanian Hydrometeorological Service", "lt_lhmt_terms_licence.html"),
    ],
)
def test_provider_provenance_is_packaged_and_terms_are_verified(
    provider_id: str,
    issuer: str,
    terms_file: str,
) -> None:
    selection = rr.find(provider=provider_id)
    provenance = selection.acquisition_provenance[0]

    assert provenance.provider_id == provider_id
    assert provenance.source_records[0].issuer == issuer
    assert {statement.kind for statement in provenance.source_records[0].statements} == {"license", "citation"}
    assert provenance.native_table.byte_size > 0
    assert set(provenance.fact_universe) == {fact for binding in provenance.fact_bindings for fact in binding.facts} | {
        fact for item in provenance.withheld_facts for fact in item.facts
    }

    verify_provenance_recordings(provenance, Path.cwd())
    assert (Path("tests/test_data") / terms_file).is_file()


@pytest.mark.parametrize(
    ("provider_id", "terms_file"),
    [
        ("cz_chmi", "cz_chmi_terms_licence.html"),
        ("fr_hubeau", "fr_hubeau_terms_licence.html"),
        ("lt_lhmt", "lt_lhmt_terms_licence.html"),
    ],
)
def test_production_provenance_rejects_changed_recording(
    tmp_path: Path,
    provider_id: str,
    terms_file: str,
) -> None:
    evidence_dir = tmp_path / "tests/test_data"
    evidence_dir.mkdir(parents=True)
    shutil.copy2(Path("tests/test_data") / terms_file, evidence_dir / terms_file)
    (evidence_dir / terms_file).write_bytes((evidence_dir / terms_file).read_bytes() + b"changed")
    provenance = rr.find(provider=provider_id).acquisition_provenance[0]

    with pytest.raises(FatalContractError, match="source recording .* digest mismatch"):
        verify_provenance_recordings(provenance, tmp_path)


@pytest.mark.parametrize("provider_id", ["cz_chmi", "fr_hubeau", "lt_lhmt"])
def test_native_cli_invokes_shared_recording_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    from importlib import import_module

    generator = import_module(f"rivretrieve._internal.providers.{provider_id}.generate_catalogue")
    native = Path(f"src/rivretrieve/_internal/providers/{provider_id}/catalogue/native.parquet")
    calls: list[str] = []

    def record_call(provenance: object, repository_root: Path) -> None:
        del provenance, repository_root
        calls.append(provider_id)

    monkeypatch.setattr(generator, "verify_provenance_recordings", record_call)
    assert generator.main(["--native", str(native), "--out", str(tmp_path)]) == 0
    assert calls == [provider_id]


@pytest.mark.parametrize("provider_id", ["cz_chmi", "fr_hubeau", "lt_lhmt"])
def test_native_cli_rejects_raw_byte_substitution(tmp_path: Path, provider_id: str) -> None:
    from importlib import import_module

    generator = import_module(f"rivretrieve._internal.providers.{provider_id}.generate_catalogue")
    source = Path(f"src/rivretrieve/_internal/providers/{provider_id}/catalogue/native.parquet")
    changed = tmp_path / "native.parquet"
    changed.write_bytes(source.read_bytes() + b"changed")

    with pytest.raises(FatalContractError, match="native table digest mismatch"):
        generator.main(["--native", str(changed), "--out", str(tmp_path / "out")])


def test_france_withholds_facts_whose_sie_issuer_is_not_established() -> None:
    provenance = rr.find(provider="fr_hubeau").acquisition_provenance[0]

    facts = {fact for item in provenance.withheld_facts for fact in item.facts}
    assert sum(fact.startswith("source.station.") for fact in facts) == 7_323
    assert sum(fact.startswith("source.observation.") for fact in facts) == 7_323
    assert sum(fact.startswith("source.station_product.") for fact in facts) == 33_139
    assert len(facts) == 47_785
    assert {item.reason for item in provenance.withheld_facts} == {"no_acquisition_record_established"}
    assert all(
        not fact.startswith(("source.station.", "source.station_product."))
        for binding in provenance.fact_bindings
        for fact in binding.facts
    )
