"""Test provenance inspection : CatalogueEvidence → OrderedLegacyProvenance.

Legacy reconstruction is explicit and test-only. Packaged corruption tests edit
v3 relations directly; they never use a legacy projection to exercise the reader.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence

EVIDENCE_FILES = (
    "provenance_facts.parquet",
    "provenance_acquisitions.parquet",
    "provenance_bindings.parquet",
    "provenance_binding_facts.parquet",
    "provenance_external_inputs.parquet",
)


def legacy_provenance(evidence: CatalogueEvidence) -> AcquisitionProvenance:
    """Reconstruct the complete ordered v2 build value for semantic assertions."""
    from rivretrieve._internal.catalogues.evidence_encoding import reconstruct_provenance

    return reconstruct_provenance(evidence)


def legacy_document(path: Path) -> dict[str, Any]:
    """Read genuine packaged evidence, then explicitly reconstruct its v2 value."""
    evidence = load_packaged_catalogue_artifact(path.parent, on_issue="raise").acquisition_provenance
    assert evidence is not None
    return legacy_provenance(evidence).model_dump(mode="json")


def assert_evidence_equal(actual: CatalogueEvidence, expected: CatalogueEvidence) -> None:
    """Compare header and all ordered relations with Polars value assertions."""
    assert actual.header == expected.header
    for name in ("facts", "acquisitions", "bindings", "binding_facts", "external_inputs"):
        pl_testing.assert_frame_equal(getattr(actual, name), getattr(expected, name), check_exact=True)


def write_evidence_table(directory: Path, filename: str, frame: pl.DataFrame) -> None:
    """Write one deliberately mutated v3 table and refresh its byte identity.

    This permits real-reader semantic-corruption tests to pass the digest gate,
    without reconstructing a legacy model or validating the malformed relations.
    """
    assert filename in EVIDENCE_FILES
    path = directory / filename
    frame.write_parquet(path, compression="zstd")
    body = path.read_bytes()
    header_path = directory / "provenance.json"
    header = json.loads(header_path.read_text())
    assert header["schema_version"] == 3
    identity = header["files"][filename]
    identity.update(sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body), row_count=frame.height)
    header_path.write_text(json.dumps(header))


def remove_binding_fact(directory: Path, name: str) -> None:
    """Remove an exact fact membership, retaining contiguous remaining positions."""
    facts = pl.read_parquet(directory / "provenance_facts.parquet")
    fact_id = facts.filter(pl.col("name") == name)["fact_id"].item()
    memberships = pl.read_parquet(directory / "provenance_binding_facts.parquet")
    memberships = memberships.filter(pl.col("fact_id") != fact_id).with_columns(
        (pl.col("position").rank("ordinal").over("binding_id") - 1).cast(pl.UInt32).alias("position")
    )
    write_evidence_table(directory, "provenance_binding_facts.parquet", memberships)


def remove_external_inputs(directory: Path, groups: tuple[str, ...]) -> None:
    """Remove exact bindings' input edges, leaving other acquisition chains intact."""
    bindings = pl.read_parquet(directory / "provenance_bindings.parquet")
    ids = bindings.filter(pl.col("fact_group").is_in(groups))["binding_id"]
    assert len(ids) == len(groups)
    inputs = pl.read_parquet(directory / "provenance_external_inputs.parquet")
    write_evidence_table(
        directory, "provenance_external_inputs.parquet", inputs.filter(~pl.col("binding_id").is_in(ids.implode()))
    )


def historical_source_provenance(provenance, metadata):
    """Validate publication-only additions before projecting an immutable old oracle.

    Source acquisitions, native identity, original facts and their ordering remain
    untouched. This test-only projection is not suitable for current publication.
    The function is self-contained so the installed-wheel proof can reuse it.
    """
    from importlib import import_module

    from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, CodeReference, ExternalFactReference
    from rivretrieve._internal.catalogues.station_metadata import validate_metadata_fields
    from rivretrieve._internal.station_metadata import metadata_support_fact, source_metadata_frame

    provenance = AcquisitionProvenance.model_validate(provenance.model_dump(mode="python"))
    build = provenance.build_inputs
    if build is None:
        return provenance
    provider = provenance.provider_id
    origins = import_module(f"rivretrieve._internal.providers.{provider}.origins")
    private_declarations = {
        "maintenance/catalogue/ba_fhmzbih/inventory/baseline_workbook_access.json": "declarations/ba_fhmzbih/baseline_workbook_access.json",
        "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz": "declarations/fr_hubeau/governing_evidence.json.xz",
        "maintenance/catalogue/fr_hubeau/inventory/native_capture.json": "declarations/fr_hubeau/native_capture.json",
        "maintenance/catalogue/station_metadata/review.json": "declarations/station_metadata/review.json",
        "maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv": "declarations/th_thaiwater/governing_station_product_evidence.csv",
    }
    expected_declarations = tuple(
        (
            "https://github.com/RivRetrieve/verification-evidence"
            if path in private_declarations
            else build.build.repository,
            private_declarations.get(path, path),
            symbol,
        )
        for path, symbol in origins.CATALOGUE_BUILD_DECLARATIONS
    )
    assert tuple((item.repository, item.repository_path, item.symbol) for item in build.declarations) == (
        expected_declarations
    )
    for declaration in build.declarations:
        if declaration.repository == "https://github.com/RivRetrieve/verification-evidence":
            assert declaration.symbol is None
            assert {item.reference.archive_revision for item in build.inputs} == {declaration.revision}
    assert build.build.repository_path == f"src/rivretrieve/_internal/providers/{provider}/generate_catalogue.py"
    assert build.build.symbol == "write_catalogue"
    declarations = {(item.repository_path, item.symbol): item for item in build.declarations}
    (catalogue_declaration,) = tuple(
        item for item in build.declarations if item.symbol in {"build_catalogue", "build_modern_catalogue"}
    )
    (origins_declaration,) = tuple(
        item
        for item in build.declarations
        if item.symbol in {"build_acquisition_provenance", "build_modern_acquisition_provenance"}
    )
    (native_use,) = tuple(item for item in build.inputs if item.usage == "native_table")
    assert provenance.native_table is not None
    assert native_use.reference.sha256 == provenance.native_table.sha256
    assert native_use.reference.byte_size == provenance.native_table.byte_size
    direct_sources = {
        fact: binding.source_id
        for binding in provenance.fact_bindings
        if binding.transformation is None
        for fact in binding.facts
    }
    direct_bindings = {
        fact: binding
        for binding in provenance.fact_bindings
        if binding.transformation is None
        for fact in binding.facts
    }
    acquisitions = {
        (source.source_id, acquisition.acquisition_id): acquisition
        for source in provenance.source_records
        for acquisition in source.acquisitions
    }
    adopted = {fact for item in build.inputs for fact in item.facts}

    def inputs_for(field, *, datum=False):
        facts = tuple(
            dict.fromkeys(
                (*(field.source_facts or native_use.facts), *(field.datum_support if datum else field.support_facts))
            )
        )
        for fact in facts:
            assert fact in adopted
            binding = direct_bindings[fact]
            acquisition = acquisitions[(binding.source_id, binding.acquisition_id)]
            assert acquisition.method != "runtime_http_request" and acquisition.instant_type != "runtime"
        return tuple(ExternalFactReference(source_id=direct_sources[fact], fact=fact) for fact in facts)

    source_metadata_frame(metadata.select("provider_id", "station_id").unique(), metadata)
    assert set(metadata["provider_id"]) == {provider}
    fields = origins.STATION_METADATA_FIELDS
    if provider == "fr_hubeau":
        recording_ids = tuple(
            entry.recording.recording_id
            for source in provenance.source_records
            if source.source_id == "fr_hubeau"
            for entry in source.evidence
            if entry.recording.repository_path.startswith(origins.SITE_METADATA_ROOT + "/")
        )
        fields = origins.station_metadata_fields(recording_ids)
    validate_metadata_fields(metadata, fields)
    fields_by_fact = {
        metadata_support_fact(field.attribute_role, field.source_field, field.source_scope): field for field in fields
    }
    value_facts = tuple(metadata["support_fact"].drop_nulls().unique(maintain_order=True))
    datum_facts = tuple(metadata["datum_support_fact"].drop_nulls().unique(maintain_order=True))
    assert set(value_facts) == set(fields_by_fact)
    assert set(datum_facts) == {f"{fact}.datum" for fact, field in fields_by_fact.items() if field.datum_support}
    metadata_facts = (*value_facts, *datum_facts)
    expected_metadata = []
    for binding in provenance.fact_bindings:
        transform = binding.transformation
        if transform is None:
            continue
        if binding.fact_group in metadata_facts:
            assert binding.facts == (binding.fact_group,)
            is_datum = binding.fact_group in datum_facts
            field = fields_by_fact[binding.fact_group.removesuffix(".datum") if is_datum else binding.fact_group]
            assert transform.name == ("associate_elevation_datum" if is_datum else "project_station_metadata")
            assert transform.kind == "derived_value" and transform.marker_value is None
            assert transform.external_inputs == inputs_for(field, datum=is_datum)
            expected_location = (
                (f"src/rivretrieve/_internal/providers/{provider}/station_metadata.py", "project_station_metadata")
                if provider in {"ch_foen", "fr_hubeau", "usgs_nwis"}
                else ("src/rivretrieve/_internal/catalogues/station_metadata.py", "build_station_metadata")
            )
            if provider == "pl_imgw":
                expected_location = (
                    "src/rivretrieve/_internal/providers/pl_imgw/station_metadata.py", "build_station_metadata"
                )
            expected_declaration = declarations[
                (f"src/rivretrieve/_internal/providers/{provider}/origins.py", "STATION_METADATA_FIELDS")
            ]
            expected_metadata.append(binding.fact_group)
        else:
            assert not set(binding.facts) & set(metadata_facts)
            assert not any(reference.fact in metadata_facts for reference in transform.external_inputs)
            expected_location = getattr(origins, "TRANSFORMATION_IMPLEMENTATIONS", {}).get(
                binding.fact_group, (catalogue_declaration.repository_path, catalogue_declaration.symbol)
            )
            expected_declaration = (
                catalogue_declaration if transform.kind == "authored_constant" else origins_declaration
            )
        assert transform.declaration == expected_declaration
        assert transform.executable == (
            None
            if transform.kind == "authored_constant"
            else CodeReference(
                repository=build.build.repository,
                revision=build.build.revision,
                repository_path=expected_location[0],
                symbol=expected_location[1],
            )
        )
    assert tuple(expected_metadata) == metadata_facts
    payload = provenance.model_dump(mode="json")
    if metadata_facts:
        count = len(metadata_facts)
        assert tuple(payload["fact_universe"][-count:]) == metadata_facts
        assert tuple(binding["fact_group"] for binding in payload["fact_bindings"][-count:]) == metadata_facts
        del payload["fact_universe"][-count:]
        del payload["fact_bindings"][-count:]
    assert not any(fact.startswith("metadata.") for fact in payload["fact_universe"])
    payload.pop("build_inputs")
    for binding in payload["fact_bindings"]:
        if transform := binding.get("transformation"):
            transform.pop("executable", None)
            transform.pop("declaration", None)
    projected = AcquisitionProvenance.model_validate(payload)
    assert projected.source_records == provenance.source_records
    assert projected.native_table == provenance.native_table
    assert projected.withheld_facts == provenance.withheld_facts
    return projected


def historical_recording_locations(document, evidence):
    """Restore only the old path presentation for pinned historical graph oracles.

    The current graph keeps historical paths as properties, not download URLs.
    Validate every restored value against its unchanged recording identity.
    """
    paths = {
        f"recording/{source_index}/{recording_index}": entry.recording.repository_path
        for source_index, source in enumerate(evidence.header.source_records)
        for recording_index, entry in enumerate(source.evidence)
    }
    for node in document["@graph"]:
        if not node["@id"].startswith("recording/"):
            continue
        path = paths[node["@id"]]
        assert "contentUrl" not in node
        assert node.pop("additionalProperty") == {
            "@type": "sc:PropertyValue",
            "name": "historical_repository_path",
            "value": path,
        }
        node["contentUrl"] = path
    return document
