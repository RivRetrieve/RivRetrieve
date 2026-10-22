from datetime import UTC, datetime

import pytest

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SourceStatement,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.providers.ch_foen.origins import build_acquisition_provenance


@pytest.fixture
def source_inputs():
    recording = RecordingReference(
        recording_id="synthetic-official",
        repository_path="synthetic/official.json",
        source_url="https://example.org/official",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="application/json",
        sha256="a" * 64,
    )
    facts = (
        "source.station.native_identity",
        "source.station.native_geometry",
        "source.station.documented_crs",
        "source.station_product.source_associations",
        "source.product.native_physics",
        "source.station.foen_reference_altitude_and_catchment",
        "source.provider.license",
        "source.provider.citation",
    )
    return {
        "native_identity": NativeTableIdentity(
            repository_path="synthetic/native.parquet", revision="b" * 40, sha256="c" * 64, byte_size=1
        ),
        "recordings": (recording,),
        "statements": tuple(
            SourceStatement(
                kind=kind,
                exact_text=f"Synthetic {kind}",
                recording_id=recording.recording_id,
                fact=f"source.provider.{kind}",
            )
            for kind in ("license", "citation")
        ),
        "acquisitions": (
            AcquisitionRecord(
                acquisition_id="synthetic-official",
                method="http_request",
                instant_type="retrieval",
                description="Synthetic source response",
                requested_from=(recording.source_url,),
                retrieved_at_start=recording.retrieved_at,
                recording_ids=(recording.recording_id,),
            ),
        ),
        "source_bindings": (
            FactBinding(fact_group="official", facts=facts, source_id="ch_foen", acquisition_id="synthetic-official"),
        ),
    }


def test_official_provenance_closes_catalogue_without_replacing_selected_identity(source_inputs):
    result = build_acquisition_provenance(**source_inputs)
    assert result.native_table == source_inputs["native_identity"]
    assert set(CATALOGUE_FACT_UNIVERSE) <= set(result.fact_universe)
    assert result.source_records[0].evidence[0].recording == source_inputs["recordings"][0]
    assert result.source_records[0].acquisitions == source_inputs["acquisitions"]
    assert "source.station.foen_reference_altitude_and_catchment" in result.fact_universe
    bindings = {fact: binding for binding in result.fact_bindings for fact in binding.facts}
    assert {ref.fact for ref in bindings["station.latitude"].transformation.external_inputs} == {
        "source.station.native_identity",
        "source.station.native_geometry",
        "source.station.documented_crs",
    }
    assert "source.product.native_physics" in {
        ref.fact for ref in bindings["product.frequency"].transformation.external_inputs
    }
    assert "source.station_product.source_associations" in {
        ref.fact for ref in bindings["station_product.product_id"].transformation.external_inputs
    }


def test_missing_source_associations_cannot_become_catalogue_facts(source_inputs):
    binding = source_inputs["source_bindings"][0]
    source_inputs["source_bindings"] = (
        binding.model_copy(
            update={
                "facts": tuple(fact for fact in binding.facts if fact != "source.station_product.source_associations")
            }
        ),
    )
    with pytest.raises(ValueError, match="source.station_product.source_associations"):
        build_acquisition_provenance(**source_inputs)


def test_missing_terms_are_not_replaced_with_invented_absence(source_inputs):
    source_inputs["statements"] = ()
    with pytest.raises(ValueError, match="selected license evidence"):
        build_acquisition_provenance(**source_inputs)


def test_unknown_acquisition_is_rejected_by_shared_relation_validation(source_inputs):
    binding = source_inputs["source_bindings"][0]
    source_inputs["source_bindings"] = (binding.model_copy(update={"acquisition_id": "unselected"}),)
    with pytest.raises(ValueError, match="unknown acquisitions"):
        build_acquisition_provenance(**source_inputs)


def test_shared_publication_preserves_witnessed_and_unknown_inventories(source_inputs, tmp_path):
    import hashlib
    from datetime import date

    import polars as pl

    from rivretrieve._internal.acquisition_provenance import (
        ArchiveMemberReference,
        CatalogueBuildInputs,
        CodeReference,
        RetainedInputUse,
    )
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table, write_native_table
    from rivretrieve._internal.catalogues.source_series import materialize_series
    from rivretrieve._internal.providers.ch_foen import generate_catalogue
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS
    from rivretrieve._internal.source_series import InventoryCompleteness

    native = stamp_native_table(
        pl.DataFrame({"no": ["001", "002"], "latitude": [46.0, 47.0], "longitude": [7.0, 8.0]}),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    native_path = tmp_path / "native.parquet"
    write_native_table(native, native_path)
    native_bytes = native_path.read_bytes()
    source_inputs["native_identity"] = NativeTableIdentity(
        repository_path="synthetic/native.parquet",
        revision="b" * 40,
        sha256=hashlib.sha256(native_bytes).hexdigest(),
        byte_size=len(native_bytes),
    )
    provenance = build_acquisition_provenance(**source_inputs)
    associations = pl.DataFrame(
        [
            {
                "station_no": "001",
                "station_id": "embedded-1",
                "route": "data_1day_mean",
                "parameterName": "Q",
                "tsName": "Q.synthetic",
                "unitName": "cubic metres per second",
                "unitSymbol": "m³/s",
            }
        ],
        schema=generate_catalogue.ASSOCIATION_SCHEMA,
    )
    catalogue = generate_catalogue.build_catalogue(
        native,
        STATION_CATALOGUE_ORIGINS,
        associations=associations,
        checked_on=date(2026, 1, 2),
        provenance=provenance,
    )
    prefix = "src/rivretrieve/_internal/providers/ch_foen/"
    code_identity = {"repository": "https://github.com/RivRetrieve/RivRetrieve", "revision": "d" * 40}
    archive_identity = {
        "archive_repository": "https://github.com/RivRetrieve/verification-evidence",
        "archive_revision": "e" * 40,
        "collection_id": "synthetic",
        "manifest_sha256": "f" * 64,
    }
    build_inputs = CatalogueBuildInputs(
        build=CodeReference(
            **code_identity, repository_path=prefix + "generate_catalogue.py", symbol="write_catalogue"
        ),
        declarations=(
            CodeReference(**code_identity, repository_path=prefix + "generate_catalogue.py", symbol="build_catalogue"),
            CodeReference(
                **code_identity, repository_path=prefix + "origins.py", symbol="build_acquisition_provenance"
            ),
        ),
        inputs=(
            RetainedInputUse(
                reference=ArchiveMemberReference(
                    **archive_identity,
                    artifact_id="native",
                    role="derived_input",
                    sha256=provenance.native_table.sha256,
                    byte_size=len(native_bytes),
                ),
                usage="native_table",
                facts=("source.station.native_identity", "source.station.native_geometry"),
            ),
            RetainedInputUse(
                reference=ArchiveMemberReference(
                    **archive_identity,
                    artifact_id="original",
                    role="publisher_original",
                    sha256=source_inputs["recordings"][0].sha256,
                    byte_size=1,
                ),
                usage="original",
                facts=source_inputs["source_bindings"][0].facts,
            ),
        ),
    )
    output = tmp_path / "catalogue"
    generate_catalogue.write_catalogue(
        catalogue, output, build_inputs=build_inputs, native_table=native, metadata_fields=()
    )
    artifact = load_packaged_catalogue_artifact(output, on_issue="raise")
    series, inventories = materialize_series(artifact)
    assert [(item.station_id, item.product_id, item.variant) for item in series] == [
        ("001", "discharge_1day_mean", "Q.synthetic")
    ]
    paired = {(item.scope.station_ids[0], item.scope.product_ids[0]): item for item in inventories}
    assert paired[("001", "discharge_1day_mean")].members == (series[0].series_id,)
    assert paired[("002", "discharge_1day_mean")].members == ()
    assert all(item.completeness == InventoryCompleteness.INCOMPLETE for item in inventories)
    assert artifact.stations["station_id"].to_list() == ["001", "002"]


def test_selected_license_does_not_invent_recommended_citation(source_inputs):
    source_inputs["statements"] = source_inputs["statements"][:1]
    result = build_acquisition_provenance(**source_inputs)
    bindings = {fact: binding for binding in result.fact_bindings for fact in binding.facts}
    citation = bindings["provider.citation"].transformation
    assert citation.kind == "derived_value"
    assert citation.marker_value is None
    assert {reference.fact for reference in citation.external_inputs} == {"source.provider.license"}
    assert bindings["provider.license"].transformation.kind == "derived_value"
    assert all("not_established" not in fact for fact in result.fact_universe)


def test_only_adopted_original_receipts_become_build_support(source_inputs):
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import selected_supporting_inputs

    provenance = build_acquisition_provenance(**source_inputs)
    path = source_inputs["recordings"][0].repository_path
    selected = {
        "captures": [
            {"body": path, "receipt": "selected.receipt"},
            {"body": "redirect.body", "receipt": "redirect.receipt"},
        ],
        "prior_live": {"body": "other.body", "receipt": "other.receipt"},
        "prior_support": [],
    }
    support = selected_supporting_inputs(provenance, selected)
    assert set(support) == {"selected.receipt"}
    assert set(support["selected.receipt"]) == set(source_inputs["source_bindings"][0].facts)
