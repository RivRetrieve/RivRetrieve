"""Synthetic controls for explicit archive membership and code lineage.

These do not certify retained bytes or source claims. Existing catalogue tests
cover historical graph validation; this small graph isolates the additive fields.
"""

import json
from datetime import UTC

import polars as pl
import pytest
from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    ArchiveMemberReference,
    CatalogueBuildInputs,
    CodeReference,
    RetainedInputReceipt,
    RetainedInputReference,
    RetainedInputUse,
    serialize_acquisition_provenance,
)
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence, EvidenceHeader, normalize_provenance
from rivretrieve._internal.catalogues.evidence_encoding import (
    encode_catalogue_evidence,
    parse_catalogue_evidence,
    reconstruct_provenance,
)


def _reference(**changes):
    return RetainedInputReference.model_validate(
        {
            "consumer_path": "retained/native.parquet",
            "archive_repository": "https://github.com/RivRetrieve/verification-evidence",
            "archive_revision": "a" * 40,
            "collection_id": "synthetic-collection",
            "manifest_sha256": "b" * 64,
            "artifact_id": "native-table",
            "sha256": "c" * 64,
            "byte_size": 0,
            "role": "derived_input",
            **changes,
        }
    )


def _member(reference=None):
    reference = _reference() if reference is None else reference
    return ArchiveMemberReference.model_validate(reference.model_dump(exclude={"consumer_path"}))


def _code(path="src/catalogue.py", symbol="build", revision="d" * 40):
    return CodeReference(
        repository="https://github.com/RivRetrieve/RivRetrieve",
        revision=revision,
        repository_path=path,
        symbol=symbol,
    )


def _build():
    return CatalogueBuildInputs(
        build=_code(),
        declarations=(_code("maintenance/origins.py", "ORIGINS", "e" * 40),),
        inputs=(RetainedInputUse(reference=_member(), usage="native_table", facts=("native.latitude",)),),
    )


def _provenance():
    build = _build()
    return AcquisitionProvenance.model_validate(
        {
            "schema_version": 2,
            "provider_id": "synthetic",
            "native_table": {
                "repository_path": "historical/native.parquet",
                "revision": "f" * 40,
                "sha256": "c" * 64,
            },
            "build_inputs": build,
            "fact_universe": ["native.latitude", "station.latitude"],
            "source_records": [
                {
                    "source_id": "issuer",
                    "issuer": "Synthetic source",
                    "acquisitions": [
                        {
                            "acquisition_id": "historical-acquisition",
                            "method": "repository_recovery",
                            "instant_type": "provenance_lower_bound",
                            "description": "Recovered synthetic native input",
                            "requested_from": ["https://example.org/source"],
                            "retrieved_at_start": "2020-01-01T00:00:00Z",
                        }
                    ],
                }
            ],
            "fact_bindings": [
                {
                    "fact_group": "source-location",
                    "facts": ["native.latitude"],
                    "source_id": "issuer",
                    "acquisition_id": "historical-acquisition",
                },
                {
                    "fact_group": "canonical-location",
                    "facts": ["station.latitude"],
                    "source_id": None,
                    "acquisition_id": None,
                    "transformation": {
                        "name": "copy_coordinate",
                        "external_inputs": [{"source_id": "issuer", "fact": "native.latitude"}],
                        "executable": _code(symbol="copy_coordinate"),
                        "declaration": build.declarations[0],
                    },
                },
            ],
        }
    )


def _normalize(provenance):
    return normalize_provenance(
        provenance,
        stations=pl.DataFrame(schema={"provider_id": pl.String, "station_id": pl.String}),
        station_products=pl.DataFrame(
            schema={"provider_id": pl.String, "station_id": pl.String, "product_id": pl.String}
        ),
    )


def test_archive_and_separate_authored_executable_references_roundtrip():
    original = _provenance()
    assert AcquisitionProvenance.model_validate_json(serialize_acquisition_provenance(original)) == original
    evidence = _normalize(original)
    files = encode_catalogue_evidence(evidence)
    header = EvidenceHeader.model_validate_json(files.pop("provenance.json"))
    parsed = parse_catalogue_evidence(header, files)
    assert reconstruct_provenance(parsed) == original
    assert parsed.header.build_inputs == original.build_inputs
    assert "consumer_path" not in parsed.header.model_dump_json()
    assert "verifier_path" not in parsed.header.model_dump_json()
    transformation = parsed.header.transformations[0]
    assert transformation.executable.revision != transformation.declaration.revision
    assert parsed.header.native_table == original.native_table
    assert reconstruct_provenance(parsed).source_records == original.source_records


def test_historical_documents_need_no_build_fields():
    payload = _provenance().model_dump(mode="json")
    payload.pop("build_inputs")
    transformation = payload["fact_bindings"][1]["transformation"]
    transformation.pop("executable")
    transformation.pop("declaration")
    historic = AcquisitionProvenance.model_validate(payload)
    normalized = _normalize(historic)
    assert "build_inputs" not in normalized.header.model_dump(mode="json")
    assert "executable" not in normalized.header.transformations[0].model_dump(mode="json")
    assert reconstruct_provenance(normalized) == historic


@pytest.mark.parametrize(
    "field,value",
    [
        ("consumer_path", "../native.parquet"),
        ("consumer_path", "/native.parquet"),
        ("consumer_path", "retained//native.parquet"),
        ("consumer_path", "./native.parquet"),
        ("consumer_path", "retained/"),
        ("consumer_path", "retained\\native.parquet"),
        ("archive_repository", "https://example.org/archive"),
        ("archive_revision", "A" * 40),
        ("archive_revision", "a" * 39),
        ("collection_id", "collection."),
        ("collection_id", "../collection"),
        ("artifact_id", "name with spaces"),
        ("manifest_sha256", "b" * 63),
        ("sha256", "C" * 64),
        ("byte_size", -1),
        ("byte_size", True),
        ("byte_size", "0"),
        ("byte_size", 1.0),
        ("role", "native_table"),
    ],
)
def test_retained_reference_rejects_invalid_identity(field, value):
    with pytest.raises(ValidationError):
        _reference(**{field: value})


def test_receipt_preserves_equal_bytes_at_distinct_archive_identities():
    first = _reference()
    second = _reference(
        consumer_path="retained/other.parquet", collection_id="other-collection", archive_revision="f" * 40
    )
    receipt = RetainedInputReceipt(
        schema_version=2, code_revision="d" * 40, declaration_revision="e" * 40, inputs=(first, second)
    )
    assert RetainedInputReceipt.model_validate_json(receipt.model_dump_json()) == receipt
    uses = tuple(
        RetainedInputUse(reference=_member(ref), usage="reviewed_support", facts=("native.latitude",))
        for ref in receipt.inputs
    )
    build = CatalogueBuildInputs(build=_code(), declarations=_build().declarations, inputs=uses)
    assert len(build.inputs) == 2
    assert build.inputs[0].reference.sha256 == build.inputs[1].reference.sha256
    assert build.inputs[0].reference.collection_id != build.inputs[1].reference.collection_id


@pytest.mark.parametrize("ambiguous", [False, True])
def test_duplicate_consumer_paths_rejected(ambiguous):
    first = _reference()
    second = _reference(collection_id="other" if ambiguous else first.collection_id)
    with pytest.raises(ValidationError, match="consumer_path"):
        RetainedInputReceipt(
            schema_version=2, code_revision="d" * 40, declaration_revision="e" * 40, inputs=(first, second)
        )


def test_duplicate_public_archive_member_and_usage_rejected():
    use = _build().inputs[0]
    with pytest.raises(ValidationError, match="archive member and usage"):
        CatalogueBuildInputs(build=_code(), declarations=_build().declarations, inputs=(use, use))


def test_missing_receipt_identity_rejected():
    payload = _reference().model_dump(mode="json")
    payload.pop("manifest_sha256")
    with pytest.raises(ValidationError):
        RetainedInputReference.model_validate(payload)


def test_dangling_adopted_fact_rejected_in_both_representations():
    provenance = _provenance()
    payload = provenance.model_dump(mode="json")
    payload["build_inputs"]["inputs"][0]["facts"] = ["native.absent"]
    with pytest.raises(ValidationError, match="dangling"):
        AcquisitionProvenance.model_validate(payload)
    payload = json.loads(_normalize(provenance).model_dump_json())
    payload["header"]["build_inputs"]["inputs"][0]["facts"] = ["native.absent"]
    with pytest.raises(ValidationError, match="dangling"):
        CatalogueEvidence.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("mutation", ["missing_header", "executable_revision", "declaration"])
def test_code_reference_closure_in_both_representations(mutation):
    provenance = _provenance()
    payload = provenance.model_dump(mode="json")
    header = _normalize(provenance).header.model_dump(mode="json")
    for root, transformation in (
        (payload, payload["fact_bindings"][1]["transformation"]),
        (header, header["transformations"][0]),
    ):
        if mutation == "missing_header":
            root.pop("build_inputs")
        elif mutation == "executable_revision":
            transformation["executable"]["revision"] = "0" * 40
        else:
            transformation["declaration"]["symbol"] = "unlisted"
    with pytest.raises(ValidationError):
        AcquisitionProvenance.model_validate(payload)
    with pytest.raises(ValidationError):
        EvidenceHeader.model_validate(header)


def _publication_build():
    payload = _build().model_dump(mode="python")
    payload["inputs"][0]["reference"]["byte_size"] = 1
    payload["declarations"] = (
        _code("maintenance/origins.py", "build_acquisition_provenance", "e" * 40),
        _code("src/rivretrieve/_internal/providers/synthetic/origins.py", "STATION_METADATA_FIELDS", "e" * 40),
        _code("src/rivretrieve/_internal/providers/synthetic/generate_catalogue.py", "build_catalogue", "e" * 40),
        _code("src/rivretrieve/_internal/assembly.py", "assemble", "e" * 40),
    )
    return CatalogueBuildInputs.model_validate(payload)


def _projected_metadata():
    return pl.DataFrame(
        {
            "attribute_role": ["drainage_area"],
            "source_field": ["area"],
            "support_fact": ["metadata.drainage_area.area"],
        }
    )


def test_publication_requires_explicit_build_and_native_inputs():
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.issues import FatalContractError

    with pytest.raises(FatalContractError, match="build_inputs and native_table"):
        build_catalogue_metadata(_provenance(), (), {})
    with pytest.raises(FatalContractError, match="build_inputs and native_table"):
        build_catalogue_metadata(_provenance(), (), {}, build_inputs=_publication_build())


def test_metadata_support_uses_existing_native_edges_without_new_acquisitions():
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs

    original = _provenance()
    build = _publication_build()
    result = _bind_catalogue_build_inputs(_normalize(original), build, _projected_metadata())
    assert result.source_records == original.source_records
    assert result.native_table == original.native_table
    assert result.build_inputs == build
    assert result.fact_universe == (*original.fact_universe, "metadata.drainage_area.area")
    projection = result.fact_bindings[-1].transformation
    assert projection.external_inputs == original.fact_bindings[1].transformation.external_inputs
    assert projection.executable.symbol == "build_station_metadata"
    assert projection.declaration.symbol == "STATION_METADATA_FIELDS"
    assert result.fact_bindings[1].transformation.executable.symbol == "build_catalogue"
    assert result.fact_bindings[1].transformation.executable != build.build
    assert result.fact_bindings[1].transformation.declaration == build.declarations[0]
    assert reconstruct_provenance(_normalize(result)) == result


def test_no_metadata_adds_no_source_support_claim():
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs

    original = _provenance()
    frame = _projected_metadata().with_columns(pl.lit(None, dtype=pl.String).alias("support_fact"))
    result = _bind_catalogue_build_inputs(original, _publication_build(), frame)
    assert result.fact_universe == original.fact_universe
    assert len(result.fact_bindings) == len(original.fact_bindings)


@pytest.mark.parametrize(
    "mutation", ["missing_origins", "missing_mapping", "ambiguous_origins", "bad_fact", "absent_native"]
)
def test_metadata_publication_rejects_missing_or_ambiguous_lineage(mutation):
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    build = _publication_build().model_dump(mode="python")
    frame = _projected_metadata()
    if mutation == "missing_origins":
        build["declarations"] = build["declarations"][1:]
    elif mutation == "missing_mapping":
        build["declarations"] = build["declarations"][:1]
    elif mutation == "ambiguous_origins":
        build["declarations"] += (_code("maintenance/other.py", "build_acquisition_provenance", "e" * 40),)
    elif mutation == "bad_fact":
        frame = frame.with_columns(pl.lit("metadata.drainage_area.other").alias("support_fact"))
    else:
        build["inputs"][0]["usage"] = "reviewed_support"
    with pytest.raises(FatalContractError):
        _bind_catalogue_build_inputs(_provenance(), CatalogueBuildInputs.model_validate(build), frame)


def test_metadata_keeps_multiple_existing_acquisition_support_edges():
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs

    payload = _provenance().model_dump(mode="python")
    payload["fact_universe"] += ("native.other_source",)
    payload["source_records"][0]["acquisitions"] += (
        {
            **payload["source_records"][0]["acquisitions"][0],
            "acquisition_id": "another-acquisition",
        },
    )
    payload["fact_bindings"] += (
        {
            "fact_group": "other-native",
            "facts": ("native.other_source",),
            "source_id": "issuer",
            "acquisition_id": "another-acquisition",
        },
    )
    original = AcquisitionProvenance.model_validate(payload)
    build = _publication_build().model_dump(mode="python")
    build["inputs"][0]["facts"] += ("native.other_source",)
    result = _bind_catalogue_build_inputs(original, CatalogueBuildInputs.model_validate(build), _projected_metadata())
    assert result.source_records == original.source_records
    assert tuple(ref.fact for ref in result.fact_bindings[-1].transformation.external_inputs) == (
        "native.latitude",
        "native.other_source",
    )


def _publication_components():
    from datetime import datetime
    from io import BytesIO

    from rivretrieve._internal.acquisition_provenance import complete_transformed_fact_universe
    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.catalogues.native import NativeTable
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        PROVIDER_INFO_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
    )
    from rivretrieve._internal.catalogues.station_metadata import MetadataField

    provider = {
        "provider_id": "synthetic",
        "name": "Synthetic catalogue",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": None,
        "license": None,
        "citation": None,
    }
    stations = pl.DataFrame(
        [("synthetic", "001", 1.0, 2.0, "unknown")], schema=STATION_CATALOG_SCHEMA.polars_schema, orient="row"
    )
    frames = {
        "stations": stations,
        "products": pl.DataFrame(schema=PRODUCT_CATALOG_SCHEMA.polars_schema),
        "station_products": pl.DataFrame(schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema),
    }
    files = {"provider.json": json.dumps(provider).encode()}
    for name, frame in frames.items():
        buffer = BytesIO()
        frame.write_parquet(buffer)
        files[f"{name}.parquet"] = buffer.getvalue()
    origins = ({column: Field(NativeColumn(column)) for column in stations.columns},)
    native = NativeTable(
        pl.DataFrame(
            {
                "station_id": ["001"],
                "area": ["12 km2"],
                "retrieved_at": [datetime(2020, 1, 1, tzinfo=UTC)],
            }
        )
    )
    payload = _provenance().model_dump(mode="python")
    payload["native_table"]["byte_size"] = 1
    original = AcquisitionProvenance.model_validate(payload)
    facts = tuple(
        f"{carrier}.{column}"
        for carrier, schema in (
            ("provider", PROVIDER_INFO_CATALOG_SCHEMA),
            ("station", STATION_CATALOG_SCHEMA),
            ("product", PRODUCT_CATALOG_SCHEMA),
            ("station_product", STATION_PRODUCT_CATALOG_SCHEMA),
        )
        for column in schema.polars_schema
    )
    original = complete_transformed_fact_universe(
        original, facts, transformation=original.fact_bindings[1].transformation
    )
    return original, origins, files, native, (MetadataField("drainage_area", "area"),)


def test_synthetic_publication_descriptor_and_historical_compatibility():
    from hashlib import sha256
    from io import BytesIO

    from rivretrieve._internal.catalogues.descriptor import build_catalogue_descriptor
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions

    original, origins, files, native, metadata_fields = _publication_components()
    metadata = build_catalogue_metadata(
        original,
        origins,
        files,
        build_inputs=_publication_build(),
        native_table=native,
        metadata_fields=metadata_fields,
        source_descriptions=SourceDescriptions(provider_id="synthetic", descriptions=()),
    )
    descriptor = json.loads(metadata["croissant.json"])
    distribution = {item["@id"]: item for item in descriptor["distribution"]}
    assert (
        distribution["station_metadata.parquet"]["sha256"] == sha256(metadata["station_metadata.parquet"]).hexdigest()
    )
    assert distribution["station_metadata.parquet"]["contentSize"] == f"{len(metadata['station_metadata.parquet'])} B"
    record = next(record for record in descriptor["recordSet"] if record["@id"] == "station_metadata")
    support = next(field for field in record["field"] if field["@id"].endswith("/support_fact"))
    assert support["references"] == {"fileObject": {"@id": "provenance_facts.parquet"}, "extract": {"column": "name"}}
    assert descriptor["subjectOf"]["url"] == "provenance.json"
    assert original.native_table.revision in descriptor["isBasedOn"]["contentUrl"]
    header = EvidenceHeader.model_validate_json(metadata["provenance.json"])
    evidence = parse_catalogue_evidence(header, {filename: metadata[filename] for filename in header.files})
    frame = pl.read_parquet(BytesIO(metadata["station_metadata.parquet"]))
    support_names = set(frame["support_fact"].drop_nulls())
    assert support_names <= set(evidence.facts["name"])
    assert reconstruct_provenance(evidence).source_records == original.source_records

    historic = original.model_dump(mode="python")
    historic.pop("build_inputs")
    for binding in historic["fact_bindings"]:
        if transformation := binding.get("transformation"):
            transformation.pop("executable")
            transformation.pop("declaration")
    old = _normalize(AcquisitionProvenance.model_validate(historic))
    old_descriptor = build_catalogue_descriptor(old, origins, {**files, **encode_catalogue_evidence(old)})
    assert "station_metadata" not in {record["@id"] for record in old_descriptor["recordSet"]}


@pytest.mark.parametrize("mutation", ["missing_file", "dangling_support", "wrong_schema", "extra_station"])
def test_descriptor_rejects_invalid_metadata_publication(mutation):
    from io import BytesIO

    from rivretrieve._internal.catalogues.descriptor import build_catalogue_descriptor
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions
    from rivretrieve._internal.issues import FatalContractError

    original, origins, files, native, metadata_fields = _publication_components()
    metadata = build_catalogue_metadata(
        original,
        origins,
        files,
        build_inputs=_publication_build(),
        native_table=native,
        metadata_fields=metadata_fields,
        source_descriptions=SourceDescriptions(provider_id="synthetic", descriptions=()),
    )
    metadata.pop("croissant.json")
    header = EvidenceHeader.model_validate_json(metadata["provenance.json"])
    evidence = parse_catalogue_evidence(header, {filename: metadata[filename] for filename in header.files})
    if mutation == "missing_file":
        metadata.pop("station_metadata.parquet")
    else:
        frame = pl.read_parquet(BytesIO(metadata["station_metadata.parquet"]))
        if mutation == "dangling_support":
            frame = frame.with_columns(
                pl.when(pl.col("support_fact").is_not_null())
                .then(pl.lit("metadata.absent"))
                .otherwise(None)
                .alias("support_fact")
            )
        elif mutation == "wrong_schema":
            frame = frame.drop("support_fact")
        else:
            frame = pl.concat([frame, frame.with_columns(pl.lit("002").alias("station_id"))])
        buffer = BytesIO()
        frame.write_parquet(buffer)
        metadata["station_metadata.parquet"] = buffer.getvalue()
    with pytest.raises(FatalContractError):
        build_catalogue_descriptor(evidence, origins, {**files, **metadata})


def test_selected_metadata_graph_exposes_only_its_adopted_support_and_separate_code_refs():
    from rivretrieve._internal.catalogues.evidence_graph import FactSelection, resolve_evidence
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs

    payload = _provenance().model_dump(mode="python")
    payload["fact_universe"] += ("native.unrelated",)
    payload["fact_bindings"] += (
        {
            "fact_group": "unrelated-source",
            "facts": ("native.unrelated",),
            "source_id": "issuer",
            "acquisition_id": "historical-acquisition",
        },
    )
    payload["source_records"][0]["evidence"] = (
        {
            "evidence_id": "synthetic-document",
            "description": "Synthetic recording",
            "recording": {
                "recording_id": "recorded-page",
                "repository_path": "historical/recording.html",
                "source_url": "https://example.org/document",
                "retrieved_at": "2020-01-01T00:00:00Z",
                "media_type": "text/html",
                "sha256": "0" * 64,
            },
        },
    )
    original = AcquisitionProvenance.model_validate(payload)
    build = _publication_build().model_dump(mode="python")
    build["inputs"] += (
        RetainedInputUse(
            reference=_member(_reference(consumer_path="retained/other.parquet", artifact_id="unrelated-member")),
            usage="reviewed_support",
            facts=("native.unrelated",),
        ),
    )
    result = _bind_catalogue_build_inputs(original, CatalogueBuildInputs.model_validate(build), _projected_metadata())
    graph = resolve_evidence(_normalize(result), FactSelection(names=("metadata.drainage_area.area",)))
    nodes = {node["@id"]: node for node in graph["@graph"]}
    assert "retained-input/0" in nodes
    assert "retained-input/1" not in nodes
    adopted = nodes["retained-input/0"]
    assert adopted["sha256"] == _reference().sha256
    properties = {prop["name"]: prop["value"] for prop in adopted["additionalProperty"]}
    assert properties["collection_id"] == _reference().collection_id
    assert properties["manifest_sha256"] == _reference().manifest_sha256
    assert properties["usage"] == "native_table"
    assert "consumer_path" not in properties
    assert "contentUrl" not in adopted
    assert nodes["fact/0"]["citation"] == [{"@id": "retained-input/0"}]
    lineage = next(
        node
        for node in nodes.values()
        if node.get("identifier") == "metadata.drainage_area.area" and node["@id"].startswith("lineage/")
    )
    code = {node["name"]: node for node in lineage["subjectOf"]}
    executable = code["Executable implementation"]
    declaration = code["Authored declaration"]
    assert executable["identifier"] == "build_station_metadata"
    assert declaration["identifier"] == "STATION_METADATA_FIELDS"
    assert "/" + "d" * 40 + "/" in executable["codeRepository"]
    assert "/" + "e" * 40 + "/" in declaration["codeRepository"]
    recording = nodes["recording/0/0"]
    assert "contentUrl" not in recording
    assert recording["additionalProperty"]["name"] == "historical_repository_path"
    assert recording["additionalProperty"]["value"] == "historical/recording.html"


def test_publication_distinguishes_authored_constants_catalogue_and_runtime_implementations():
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs

    payload = _provenance().model_dump(mode="python")
    payload["fact_universe"] += ("provider.name", "observation.value")
    payload["fact_bindings"] += (
        {
            "fact_group": "authored-name",
            "facts": ("provider.name",),
            "source_id": None,
            "acquisition_id": None,
            "transformation": {"name": "authored_name", "kind": "authored_constant", "external_inputs": ()},
        },
        {
            "fact_group": "observation-value",
            "facts": ("observation.value",),
            "source_id": None,
            "acquisition_id": None,
            "transformation": {
                "name": "observation_value",
                "external_inputs": ({"source_id": "issuer", "fact": "native.latitude"},),
            },
        },
    )
    original = AcquisitionProvenance.model_validate(payload)
    result = _bind_catalogue_build_inputs(original, _publication_build(), _projected_metadata())
    catalogue, authored, observation = (result.fact_bindings[index].transformation for index in (1, 2, 3))
    assert catalogue.executable.symbol == "build_catalogue"
    assert catalogue.executable.repository_path.endswith("/synthetic/generate_catalogue.py")
    assert authored.executable is None
    assert authored.declaration.symbol == "build_catalogue"
    assert observation.executable.symbol == "assemble"
    assert observation.executable.repository_path == "src/rivretrieve/_internal/assembly.py"
    assert observation.declaration.symbol == "build_acquisition_provenance"
    assert result.build_inputs.build.symbol == "build"


def test_publication_rejects_unknown_transformation_responsibility():
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    payload = _provenance().model_dump(mode="python")
    payload["fact_universe"] = ("native.latitude", "unknown.output")
    payload["fact_bindings"][1]["facts"] = ("unknown.output",)
    with pytest.raises(FatalContractError, match="responsibility"):
        _bind_catalogue_build_inputs(
            AcquisitionProvenance.model_validate(payload), _publication_build(), _projected_metadata()
        )


def test_whole_authored_file_reference_roundtrips_but_cannot_name_executable():
    payload = _provenance().model_dump(mode="python")
    ledger = CodeReference(
        repository="https://github.com/RivRetrieve/RivRetrieve",
        revision="e" * 40,
        repository_path="maintenance/reviewed-ledger.json",
    )
    payload["build_inputs"]["declarations"] += (ledger,)
    payload["fact_bindings"][1]["transformation"]["declaration"] = ledger
    original = AcquisitionProvenance.model_validate(payload)
    assert reconstruct_provenance(_normalize(original)) == original
    payload["fact_bindings"][1]["transformation"]["executable"]["symbol"] = None
    with pytest.raises(ValidationError, match="requires a symbol"):
        AcquisitionProvenance.model_validate(payload)
    build = _build().model_dump(mode="python")
    build["build"]["symbol"] = None
    with pytest.raises(ValidationError, match="requires a symbol"):
        CatalogueBuildInputs.model_validate(build)


def test_publication_uses_explicit_builder_and_rejects_ambiguous_declarations():
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    build = _publication_build().model_dump(mode="python")
    build["declarations"][2]["symbol"] = "build_modern_catalogue"
    result = _bind_catalogue_build_inputs(
        _provenance(), CatalogueBuildInputs.model_validate(build), _projected_metadata()
    )
    assert result.fact_bindings[1].transformation.executable.symbol == "build_modern_catalogue"
    build["declarations"] += (
        _code("src/rivretrieve/_internal/providers/synthetic/generate_catalogue.py", "build_catalogue", "e" * 40),
    )
    with pytest.raises(FatalContractError, match="one exact catalogue builder"):
        _bind_catalogue_build_inputs(_provenance(), CatalogueBuildInputs.model_validate(build), _projected_metadata())


def test_reviewed_support_retains_exact_identity_and_omits_restricted_locations():
    from rivretrieve._internal.acquisition_provenance import (
        ArchiveMemberReference,
        RetainedSupportReference,
        RetainedSupportUse,
    )
    from rivretrieve._internal.catalogues.evidence_graph import FactSelection, resolve_evidence

    archive = _reference().model_dump(exclude={"consumer_path"})
    restricted = RetainedSupportReference(
        **archive,
        provider_id="ba_fhmzbih",
        verifier_path="verification/source-bodies.zip",
        verification_kind="full_positive",
    )
    receipt = RetainedInputReceipt(
        schema_version=2,
        code_revision="d" * 40,
        declaration_revision="e" * 40,
        inputs=(_reference(),),
        support_inputs=(restricted,),
    )
    assert RetainedInputReceipt.model_validate_json(receipt.model_dump_json()) == receipt
    public = RetainedSupportUse(
        reference=ArchiveMemberReference.model_validate(archive),
        facts=("native.latitude",),
        verification_kind=restricted.verification_kind,
        verifier=_code("maintenance/verify.py", "main"),
        member_selector="reviewed/workbook.xlsx",
    )
    payload = _provenance().model_dump(mode="python")
    payload["build_inputs"]["support"] = (public,)
    provenance = AcquisitionProvenance.model_validate(payload)
    encoded = serialize_acquisition_provenance(provenance)
    assert "verifier_path" not in encoded
    assert "verification/source-bodies.zip" not in encoded
    assert "reviewed/workbook.xlsx" in encoded
    assert reconstruct_provenance(_normalize(provenance)) == provenance
    graph = resolve_evidence(_normalize(provenance), FactSelection(names=("station.latitude",)))
    node = next(node for node in graph["@graph"] if node["@id"] == "retained-support/0")
    properties = {prop["name"]: prop["value"] for prop in node["additionalProperty"]}
    assert properties["usage"] == "reviewed_support"
    assert properties["verification_kind"] == "full_positive"
    assert properties["member_selector"] == "reviewed/workbook.xlsx"
    assert node["subjectOf"]["identifier"] == "main"
    assert "verifier_path" not in json.dumps(graph)
    with pytest.raises(ValidationError):
        RetainedSupportUse.model_validate({**public.model_dump(), "reference": restricted.model_dump()})


@pytest.mark.parametrize("mutation", ["old_receipt", "unverified", "verifier_path", "selector", "revision", "fact"])
def test_reviewed_support_rejects_unverified_or_dangling_identity(mutation):
    from rivretrieve._internal.acquisition_provenance import RetainedSupportUse

    archive = _reference().model_dump(exclude={"consumer_path"})
    if mutation in {"old_receipt", "unverified", "verifier_path"}:
        support = {
            **archive,
            "provider_id": "ba_fhmzbih",
            "verifier_path": "source.zip",
            "verification_kind": "full_positive",
        }
        receipt = {
            "schema_version": 2,
            "code_revision": "d" * 40,
            "declaration_revision": "e" * 40,
            "inputs": [_reference()],
            "support_inputs": [support],
        }
        if mutation == "old_receipt":
            receipt["schema_version"] = 1
        elif mutation == "unverified":
            support["verification_kind"] = "manifest_integrity"
        else:
            support["verifier_path"] = "../source.zip"
        with pytest.raises(ValidationError):
            RetainedInputReceipt.model_validate(receipt)
        return
    support = {
        "reference": archive,
        "facts": ("native.latitude",),
        "verification_kind": "full_positive",
        "verifier": _code("maintenance/verify.py", "main"),
        "member_selector": "member.xlsx",
    }
    if mutation == "selector":
        support["member_selector"] = "../member.xlsx"
        with pytest.raises(ValidationError):
            RetainedSupportUse.model_validate(support)
    else:
        if mutation == "revision":
            support["verifier"] = _code("maintenance/verify.py", "main", "e" * 40)
        else:
            support["facts"] = ("native.absent",)
        payload = _provenance().model_dump(mode="python")
        payload["build_inputs"]["support"] = (support,)
        with pytest.raises(ValidationError):
            AcquisitionProvenance.model_validate(payload)


def test_publication_requires_explicit_metadata_fields_and_accepts_empty_scope():
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions
    from rivretrieve._internal.issues import FatalContractError

    original, origins, files, native, _ = _publication_components()
    descriptions = SourceDescriptions(provider_id="synthetic", descriptions=())
    with pytest.raises(FatalContractError, match="metadata_fields"):
        build_catalogue_metadata(
            original,
            origins,
            files,
            build_inputs=_publication_build(),
            native_table=native,
            source_descriptions=descriptions,
        )
    metadata = build_catalogue_metadata(
        original,
        origins,
        files,
        build_inputs=_publication_build(),
        native_table=native,
        metadata_fields=(),
        source_descriptions=descriptions,
    )
    frame = pl.read_parquet(BytesIO(metadata["station_metadata.parquet"]))
    assert frame["state"].to_list() == ["no_metadata"] * 3
    assert frame["support_fact"].null_count() == 3


def test_public_consumed_input_rejects_restricted_locator_objects_and_fields():
    with pytest.raises(ValidationError, match="locators"):
        RetainedInputUse(reference=_reference(), usage="native_table", facts=("native.latitude",))
    with pytest.raises(ValidationError):
        RetainedInputUse.model_validate(
            {"reference": _reference().model_dump(), "usage": "native_table", "facts": ("native.latitude",)}
        )


@pytest.mark.parametrize("mutation", ["digest", "size", "no_native", "two_native"])
def test_publication_checks_native_archive_identity_even_without_exposed_fields(mutation):
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    payload = _provenance().model_dump(mode="python")
    payload["native_table"]["byte_size"] = 1
    build = _publication_build().model_dump(mode="python")
    if mutation == "digest":
        build["inputs"][0]["reference"]["sha256"] = "0" * 64
    elif mutation == "size":
        build["inputs"][0]["reference"]["byte_size"] = 0
    elif mutation == "no_native":
        build["inputs"][0]["usage"] = "reviewed_support"
    else:
        other = {**build["inputs"][0], "reference": {**build["inputs"][0]["reference"], "artifact_id": "another"}}
        build["inputs"] += (other,)
    frame = _projected_metadata().clear()
    with pytest.raises(FatalContractError):
        _bind_catalogue_build_inputs(
            AcquisitionProvenance.model_validate(payload), CatalogueBuildInputs.model_validate(build), frame
        )


def test_republication_replaces_only_metadata_leaf_projection():
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    original = _provenance()
    build = _publication_build()
    projected = _bind_catalogue_build_inputs(original, build, _projected_metadata())
    repeated = _bind_catalogue_build_inputs(_normalize(projected), build, _projected_metadata())
    assert repeated == projected
    new_metadata = _projected_metadata().with_columns(
        pl.lit("another_area").alias("source_field"),
        pl.lit("metadata.drainage_area.another_area").alias("support_fact"),
    )
    replaced = _bind_catalogue_build_inputs(_normalize(projected), build, new_metadata)
    assert replaced.source_records == original.source_records
    assert replaced.native_table == original.native_table
    assert "metadata.drainage_area.area" not in replaced.fact_universe
    assert "metadata.drainage_area.another_area" in replaced.fact_universe
    assert replaced.fact_bindings[:-1] == projected.fact_bindings[:-1]
    empty = _bind_catalogue_build_inputs(_normalize(projected), build, _projected_metadata().clear())
    assert empty.fact_universe == original.fact_universe

    payload = projected.model_dump(mode="python")
    payload["fact_bindings"][1]["transformation"]["external_inputs"] = (
        {"source_id": None, "fact": "metadata.drainage_area.area"},
    )
    with pytest.raises(FatalContractError, match="nonmetadata dependent"):
        _bind_catalogue_build_inputs(AcquisitionProvenance.model_validate(payload), build, new_metadata)
