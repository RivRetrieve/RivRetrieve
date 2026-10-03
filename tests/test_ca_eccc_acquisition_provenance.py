import json
import shutil
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    ExternalFactReference,
    verify_provenance_recordings,
    verify_recorded_statement,
)
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ca_eccc.generate_catalogue import main
from rivretrieve._internal.providers.ca_eccc.origins import build_acquisition_provenance
from tests._provenance import remove_external_inputs, write_evidence_table


def test_canada_provenance_separates_geomet_from_hydat() -> None:
    provenance = build_acquisition_provenance()
    assert {source.source_id for source in provenance.source_records} == {"ca_eccc_msc", "ca_eccc_wsc"}
    bindings = {item.fact_group: item.source_id for item in provenance.fact_bindings}
    assert {
        "station_registry": "ca_eccc_msc",
        "hydat_observations": "ca_eccc_wsc",
    }.items() <= bindings.items()
    assert {statement.kind for source in provenance.source_records for statement in source.statements} == {
        "license",
        "citation",
    }


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet",
    "tests/test_data/ca_eccc_terms_citation.html",
    "tests/test_data/ca_eccc_terms_licence.html",
)
def test_canada_terms_recordings_and_native_bytes_are_verified(retained_evidence_root: Path, tmp_path: Path) -> None:
    from tests.test_catalogue_build_provenance import _build

    # Synthetic selection reaches only the intended failing verification boundary.
    build_inputs_path = tmp_path / "synthetic-build-inputs.json"
    build_inputs_path.write_text(_build().model_dump_json(), encoding="utf-8")
    verify_provenance_recordings(build_acquisition_provenance(), retained_evidence_root)
    evidence = Path("tests/test_data/ca_eccc_terms_licence.html")
    target = tmp_path / evidence
    target.parent.mkdir(parents=True)
    target.write_bytes((retained_evidence_root / evidence).read_bytes().replace(b"worldwide", b"worldwidX", 1))
    citation = Path("tests/test_data/ca_eccc_terms_citation.html")
    (tmp_path / citation).write_bytes((retained_evidence_root / citation).read_bytes())
    with pytest.raises(FatalContractError, match="ca_eccc_terms_licence digest mismatch"):
        verify_provenance_recordings(build_acquisition_provenance(), tmp_path)
    native = tmp_path / "native.parquet"
    shutil.copy2(
        retained_evidence_root / "src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet", native
    )
    native.write_bytes(native.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="native table digest mismatch"):
        main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--native",
                str(native),
                "--out",
                str(tmp_path / "out"),
                "--evidence-root",
                str(retained_evidence_root),
            ]
        )


def test_canada_canonical_carriers_are_rivretrieve_transformations() -> None:
    provenance = build_acquisition_provenance()
    canonical = [
        binding
        for binding in provenance.fact_bindings
        if any(fact.startswith(("provider.", "product.", "station.", "station_product.")) for fact in binding.facts)
    ]
    assert canonical
    assert all(binding.source_id is None and binding.acquisition_id is None for binding in canonical)
    lineage_sources = {
        reference.source_id
        for binding in canonical
        if binding.transformation is not None
        for reference in binding.transformation.external_inputs
    }
    assert lineage_sources == {"ca_eccc_msc", "ca_eccc_wsc"}
    for kind, source_id in (("license", "ca_eccc_msc"), ("citation", "ca_eccc_wsc")):
        binding = next(binding for binding in canonical if f"provider.{kind}" in binding.facts)
        assert binding.transformation is not None
        assert [(reference.source_id, reference.fact) for reference in binding.transformation.external_inputs] == [
            (source_id, f"source.provider.{kind}_statement")
        ]


def test_external_fact_references_reject_dangling_and_misattributed_lineage() -> None:
    provenance = build_acquisition_provenance()
    assert all(
        isinstance(reference, ExternalFactReference)
        for binding in provenance.fact_bindings
        if binding.transformation is not None
        for reference in binding.transformation.external_inputs
    )
    payload = provenance.model_dump(mode="python")
    transformed = next(binding for binding in payload["fact_bindings"] if binding.get("transformation") is not None)
    transformed["transformation"]["external_inputs"] = ({"source_id": "ca_eccc_wsc", "fact": "station.dangling"},)
    with pytest.raises(ValidationError, match="dangling or misattributed"):
        AcquisitionProvenance.model_validate(payload)


def test_recordings_are_artifact_unique_and_statements_are_issuer_local() -> None:
    provenance = build_acquisition_provenance()
    duplicate = provenance.model_dump(mode="python")
    duplicate["source_records"][1]["evidence"][0]["recording"]["recording_id"] = "ca_eccc_terms_licence"
    duplicate["source_records"][1]["statements"][0]["recording_id"] = "ca_eccc_terms_licence"
    with pytest.raises(ValidationError, match="recording ids must be unique"):
        AcquisitionProvenance.model_validate(duplicate)

    cross_issuer = provenance.model_dump(mode="python")
    cross_issuer["source_records"][0]["statements"][0]["recording_id"] = "ca_eccc_terms_citation"
    with pytest.raises(ValidationError, match="issuer-local"):
        AcquisitionProvenance.model_validate(cross_issuer)

    cross_acquisition = provenance.model_dump(mode="python")
    cross_acquisition["source_records"][0]["acquisitions"][0]["recording_ids"] = ("ca_eccc_terms_citation",)
    with pytest.raises(ValidationError, match="issuer-local"):
        AcquisitionProvenance.model_validate(cross_acquisition)


def test_canada_real_loader_rejects_empty_acquisition_and_carrier_lineage(tmp_path: Path) -> None:
    source = Path("src/rivretrieve/_internal/providers/ca_eccc/catalogue")
    for mutation in ("acquisition", "carrier"):
        copied = tmp_path / mutation
        shutil.copytree(source, copied)
        if mutation == "acquisition":
            acquisitions = pl.read_parquet(copied / "provenance_acquisitions.parquet")
            changed = acquisitions.with_columns(
                pl.when(pl.col("acquisition_key") == 0)
                .then(pl.lit([], dtype=pl.List(pl.String)))
                .otherwise(pl.col("requested_from"))
                .alias("requested_from")
            )
            write_evidence_table(copied, "provenance_acquisitions.parquet", changed)
            document = json.loads((copied / "provenance.json").read_text())
            document["descriptions"][0] = ""
            (copied / "provenance.json").write_text(json.dumps(document))
        else:
            remove_external_inputs(copied, ("canonical_msc_catalogue_carrier",))
        with pytest.raises(CorruptCatalogArtifactError, match="description|requested_from|external inputs"):
            load_packaged_catalogue_artifact(copied, on_issue="raise")


def test_canada_real_loader_rejects_runtime_lineage_for_a_packaged_product(tmp_path: Path) -> None:
    source = Path("src/rivretrieve/_internal/providers/ca_eccc/catalogue")
    mutated = tmp_path / "catalogue"
    shutil.copytree(source, mutated)
    bindings = pl.read_parquet(mutated / "provenance_bindings.parquet")
    binding_id = bindings.filter(pl.col("fact_group") == "canonical_wsc_product_carrier")["binding_id"].item()
    facts = pl.read_parquet(mutated / "provenance_facts.parquet")
    fact_id = facts.filter(pl.col("name") == "source.observation.value")["fact_id"].item()
    header = json.loads((mutated / "provenance.json").read_text())
    transformation_id = bindings.filter(pl.col("binding_id") == binding_id)["transformation_id"].item()
    assert bindings.filter(pl.col("transformation_id") == transformation_id).height == 1
    header["transformations"][transformation_id] = {
        "name": "invalid runtime-derived product",
        "kind": "derived_value",
        "marker_value": None,
    }
    (mutated / "provenance.json").write_text(json.dumps(header))
    source_ordinal = next(
        i for i, source in enumerate(header["source_records"]) if source["source_id"] == "ca_eccc_wsc"
    )
    inputs = pl.read_parquet(mutated / "provenance_external_inputs.parquet")
    changed = pl.concat(
        [
            inputs.filter(pl.col("binding_id") != binding_id),
            pl.DataFrame(
                {"binding_id": [binding_id], "position": [0], "source_ordinal": [source_ordinal], "fact_id": [fact_id]},
                schema=inputs.schema,
            ),
        ]
    ).sort("binding_id", "position")
    write_evidence_table(mutated, "provenance_external_inputs.parquet", changed)

    with pytest.raises(CorruptCatalogArtifactError, match="runtime acquisition ancestor"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet",
    "tests/test_data/ca_eccc_terms_citation.html",
    "tests/test_data/ca_eccc_terms_licence.html",
)
def test_canada_real_recording_rejects_an_empty_quotation(retained_evidence_root: Path, tmp_path: Path) -> None:
    del tmp_path
    provenance = build_acquisition_provenance()
    document = provenance.model_dump(mode="python")
    document["source_records"][0]["statements"][0]["exact_text"] = "   "
    with pytest.raises(ValidationError, match="exact_text.*non-empty|source statement exact text"):
        AcquisitionProvenance.model_validate(document)

    recording = provenance.source_records[0].evidence[0].recording
    body = (retained_evidence_root / recording.repository_path).read_bytes()
    with pytest.raises(FatalContractError, match="quotation must be non-empty"):
        verify_recorded_statement(
            recording_name="ca_eccc.empty",
            body=body,
            expected_sha256=recording.sha256,
            media_type=recording.media_type,
            exact_text="   ",
        )


def test_canada_rejects_transitive_runtime_lineage_for_a_packaged_product() -> None:
    document = build_acquisition_provenance().model_dump(mode="python")
    product = next(item for item in document["fact_bindings"] if item["fact_group"] == "canonical_wsc_product_carrier")
    product["transformation"] = {
        "name": "invalid transitively runtime-derived product",
        "external_inputs": [
            {"source_id": None, "fact": "observation.identity_bearing_shape"},
        ],
    }

    with pytest.raises(ValidationError, match="runtime acquisition ancestor"):
        AcquisitionProvenance.model_validate(document)


def test_canada_real_loader_rejects_malformed_acquisition_locations(tmp_path: Path) -> None:
    location = "https://example.com:bad/path"
    source = Path("src/rivretrieve/_internal/providers/ca_eccc/catalogue")
    mutated = tmp_path / "catalogue"
    shutil.copytree(source, mutated)
    acquisitions = pl.read_parquet(mutated / "provenance_acquisitions.parquet")
    changed = acquisitions.with_columns(
        pl.when(pl.col("acquisition_key") == 0)
        .then(pl.lit([location], dtype=pl.List(pl.String)))
        .otherwise(pl.col("requested_from"))
        .alias("requested_from")
    )
    write_evidence_table(mutated, "provenance_acquisitions.parquet", changed)

    with pytest.raises(CorruptCatalogArtifactError, match="requested_from|location"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")
