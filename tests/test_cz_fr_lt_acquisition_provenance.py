from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.acquisition_provenance import verify_provenance_recordings
from rivretrieve._internal.issues import FatalContractError
from tests._catalogue import catalogue_recording_paths
from tests._provenance import legacy_provenance


@pytest.mark.parametrize(
    ("provider_id", "issuer", "terms_file"),
    [
        pytest.param(
            "cz_chmi",
            "Czech Hydrometeorological Institute",
            "cz_chmi_terms_licence.html",
            marks=pytest.mark.governing(
                "tests/test_data/cz_chmi_terms_licence.html",
                "tests/test_data/cz_meta2.json",
            ),
        ),
        pytest.param(
            "fr_hubeau",
            "Hub’Eau",
            "fr_hubeau_terms_licence.html",
            marks=pytest.mark.governing(
                "tests/test_data/fr_hubeau_hydrometrie.html",
                "tests/test_data/fr_hubeau_temperature_openapi.json",
                "tests/test_data/fr_hubeau_terms_licence.html",
            ),
        ),
        pytest.param(
            "lt_lhmt",
            "Lithuanian Hydrometeorological Service",
            "lt_lhmt_terms_licence.html",
            marks=pytest.mark.governing(
                "tests/test_data/lt_lhmt_terms_licence.html",
            ),
        ),
    ],
)
def test_provider_provenance_is_packaged_and_terms_are_verified(
    retained_evidence_root: Path,
    provider_id: str,
    issuer: str,
    terms_file: str,
) -> None:
    selection = rr.find(provider=provider_id)
    provenance = selection.acquisition_provenance[0]
    assert provenance is not None
    provenance = legacy_provenance(provenance)

    assert provenance.provider_id == provider_id
    assert provenance.source_records[0].issuer == issuer
    assert {statement.kind for statement in provenance.source_records[0].statements} == {"license", "citation"}
    assert provenance.native_table.byte_size > 0
    assert set(provenance.fact_universe) == {fact for binding in provenance.fact_bindings for fact in binding.facts} | {
        fact for item in provenance.withheld_facts for fact in item.facts
    }

    verify_provenance_recordings(provenance, retained_evidence_root)
    assert ((retained_evidence_root / "tests/test_data") / terms_file).is_file()


@pytest.mark.parametrize(
    ("provider_id", "terms_file"),
    [
        pytest.param(
            "cz_chmi",
            "cz_chmi_terms_licence.html",
            marks=pytest.mark.governing(
                "tests/test_data/cz_chmi_terms_licence.html",
            ),
        ),
        pytest.param(
            "fr_hubeau",
            "fr_hubeau_terms_licence.html",
            marks=pytest.mark.governing(
                "tests/test_data/fr_hubeau_terms_licence.html",
                full_verification=("fr_hubeau",),
            ),
        ),
        pytest.param(
            "lt_lhmt",
            "lt_lhmt_terms_licence.html",
            marks=pytest.mark.governing(
                "tests/test_data/lt_lhmt_terms_licence.html",
            ),
        ),
    ],
)
def test_production_provenance_rejects_changed_recording(
    retained_evidence_root: Path,
    tmp_path: Path,
    provider_id: str,
    terms_file: str,
) -> None:
    evidence_dir = tmp_path / "tests/test_data"
    evidence_dir.mkdir(parents=True)
    shutil.copy2((retained_evidence_root / "tests/test_data") / terms_file, evidence_dir / terms_file)
    (evidence_dir / terms_file).write_bytes((evidence_dir / terms_file).read_bytes() + b"changed")
    provenance = rr.find(provider=provider_id).acquisition_provenance[0]
    assert provenance is not None
    provenance = legacy_provenance(provenance)

    with pytest.raises(FatalContractError, match="source recording .* digest mismatch"):
        verify_provenance_recordings(provenance, tmp_path)


@pytest.mark.parametrize(
    "provider_id",
    [
        pytest.param(
            "cz_chmi",
            marks=pytest.mark.derived(
                "src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet",
                *catalogue_recording_paths("cz_chmi"),
            ),
        ),
        pytest.param(
            "fr_hubeau",
            marks=pytest.mark.derived(
                "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
                *catalogue_recording_paths("fr_hubeau"),
            ),
        ),
        pytest.param(
            "lt_lhmt",
            marks=pytest.mark.derived(
                "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
                *catalogue_recording_paths("lt_lhmt"),
            ),
        ),
    ],
)
def test_native_cli_invokes_shared_recording_verifier(
    retained_evidence_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    catalogue_build_inputs_path,
) -> None:
    from importlib import import_module

    generator = import_module(f"rivretrieve._internal.providers.{provider_id}.generate_catalogue")
    native = retained_evidence_root / f"src/rivretrieve/_internal/providers/{provider_id}/catalogue/native.parquet"
    origins = import_module(f"rivretrieve._internal.providers.{provider_id}.origins")
    if provider_id == "fr_hubeau":
        import lzma

        from rivretrieve._internal.catalogues.native import read_native_table

        capture = generator.NativeInventoryCapture.model_validate_json(
            Path("maintenance/catalogue/fr_hubeau/inventory/native_capture.json").read_bytes()
        )
        availability = generator.decode_availability(
            lzma.decompress(Path("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz").read_bytes())
        )
        generated = generator.build_catalogue(
            read_native_table(native), origins.FRANCE_ORIGIN_DECLARATIONS, availability, native_capture=capture
        )
        provenance = generated.acquisition_provenance
    else:
        provenance = origins.build_acquisition_provenance()
    build_inputs_path = catalogue_build_inputs_path(provenance)
    calls: list[str] = []

    def record_call(provenance: object, repository_root: Path) -> None:
        del provenance
        assert repository_root == retained_evidence_root
        calls.append(provider_id)

    monkeypatch.setattr(generator, "verify_provenance_recordings", record_call)
    args = [
        "--build-inputs",
        str(build_inputs_path),
        "--native",
        str(native),
        "--out",
        str(tmp_path),
        "--evidence-root",
        str(retained_evidence_root),
    ]
    if provider_id == "fr_hubeau":
        args += [
            "--availability-ledger",
            "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz",
            "--native-capture",
            "maintenance/catalogue/fr_hubeau/inventory/native_capture.json",
        ]
    assert generator.main(args) == 0
    assert calls == [provider_id]


@pytest.mark.parametrize(
    "provider_id",
    [
        pytest.param(
            "cz_chmi",
            marks=pytest.mark.governing(
                "src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet",
                "tests/test_data/cz_chmi_terms_licence.html",
                "tests/test_data/cz_meta2.json",
            ),
        ),
        pytest.param(
            "fr_hubeau",
            marks=pytest.mark.governing(
                "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
                full_verification=("fr_hubeau",),
            ),
        ),
        pytest.param(
            "lt_lhmt",
            marks=pytest.mark.governing(
                "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
                "tests/test_data/lt_lhmt_terms_licence.html",
            ),
        ),
    ],
)
def test_native_cli_rejects_raw_byte_substitution(
    tmp_path: Path, provider_id: str, retained_evidence_root: Path
) -> None:
    from tests.test_catalogue_build_provenance import _build

    # Synthetic selection reaches only the intended failing verification boundary.
    build_inputs_path = tmp_path / "synthetic-build-inputs.json"
    build_inputs_path.write_text(_build().model_dump_json(), encoding="utf-8")
    from importlib import import_module

    generator = import_module(f"rivretrieve._internal.providers.{provider_id}.generate_catalogue")
    source = retained_evidence_root / f"src/rivretrieve/_internal/providers/{provider_id}/catalogue/native.parquet"
    changed = tmp_path / "native.parquet"
    changed.write_bytes(source.read_bytes() + b"changed")

    with pytest.raises(FatalContractError, match="native table digest mismatch"):
        args = [
            "--build-inputs",
            str(build_inputs_path),
            "--native",
            str(changed),
            "--out",
            str(tmp_path / "out"),
            "--evidence-root",
            str(retained_evidence_root),
        ]
        if provider_id == "fr_hubeau":
            args += [
                "--native-capture",
                "maintenance/catalogue/fr_hubeau/inventory/native_capture.json",
                "--availability-ledger",
                "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz",
            ]
        generator.main(args)


def test_france_binds_official_publication_without_original_producer_overclaims() -> None:
    provenance = rr.find(provider="fr_hubeau").acquisition_provenance[0]
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    assert not provenance.withheld_facts
    bound_station_facts = {
        fact for binding in provenance.fact_bindings for fact in binding.facts if fact.startswith("source.station.")
    }
    assert len(bound_station_facts) == 7347
    assert {source.source_id for source in provenance.source_records} == {"fr_hubeau"}
    acquisitions = {
        (source.source_id, acquisition.acquisition_id): acquisition
        for source in provenance.source_records
        for acquisition in source.acquisitions
    }
    values = [
        binding
        for binding in provenance.fact_bindings
        if any(fact.startswith("source.observation.") and fact.endswith(".values_quality") for fact in binding.facts)
    ]
    assert sum(len(binding.facts) for binding in values) == 20297
    for binding in values:
        assert binding.source_id is not None
        assert binding.acquisition_id is not None
        assert acquisitions[binding.source_id, binding.acquisition_id].method == "runtime_http_request"


def test_lithuania_runtime_provenance_names_the_exact_monthly_route() -> None:
    provenance = rr.find(provider="lt_lhmt").acquisition_provenance[0]
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    runtime = next(
        acquisition
        for source in provenance.source_records
        for acquisition in source.acquisitions
        if acquisition.acquisition_id == "observation_request"
    )

    assert runtime.requested_from == (
        "https://api.meteo.lt/v1/hydro-stations/{station}/observations/historical/{YYYY-MM}",
    )


@pytest.mark.recorded("tests/test_data/fr_hubeau_temperature_openapi.json")
def test_france_temperature_openapi_is_bound_without_instantaneous_inference(retained_evidence_root: Path) -> None:
    provenance = rr.find(provider="fr_hubeau").acquisition_provenance[0]
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    source = next(record for record in provenance.source_records if record.source_id == "fr_hubeau")
    evidence = next(item for item in source.evidence if item.evidence_id == "fr_hubeau_temperature_openapi")
    binding = next(item for item in provenance.fact_bindings if item.fact_group == "temperature_product_external")

    document = evidence.recording.repository_path
    assert binding.facts == ("source.product.temperature_api_semantics",)
    assert binding.acquisition_id == "temperature_semantics_openapi_2026_09_02"
    assert document == "tests/test_data/fr_hubeau_temperature_openapi.json"
    text = (retained_evidence_root / document).read_text(encoding="utf-8")
    assert "API Hub'Eau - Température des cours d'eau en continu" in text
    assert (
        '"date_mesure_temp":{"type":"string","format":"date-time","example":"2016-12-01","description":"Date de la mesure"'
        in text
    )
    assert '"heure_mesure_temp":{"type":"string","example":"16:12:36","description":"Heure de la mesure"' in text
    assert '"resultat":{"type":"number","format":"double","description":"Résultat"' in text
    assert "instant" not in text.lower()
