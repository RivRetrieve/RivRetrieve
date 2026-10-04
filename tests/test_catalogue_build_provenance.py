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
        schema_version=3,
        archive_code_revision="f" * 40,
        code_revision="d" * 40,
        declaration_revision="e" * 40,
        inputs=(first, second),
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
            schema_version=3,
            archive_code_revision="f" * 40,
            code_revision="d" * 40,
            declaration_revision="e" * 40,
            inputs=(first, second),
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
            "source_scope": pl.Series([None], dtype=pl.String),
            "support_fact": ["metadata.drainage_area.area"],
            "source_datum_field": pl.Series([None], dtype=pl.String),
            "datum_support_fact": pl.Series([None], dtype=pl.String),
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
        build["declarations"] = tuple(
            item for item in build["declarations"] if item["symbol"] != "STATION_METADATA_FIELDS"
        )
    elif mutation == "ambiguous_origins":
        build["declarations"] += (_code("maintenance/other.py", "build_acquisition_provenance", "e" * 40),)
    elif mutation == "bad_fact":
        frame = frame.with_columns(pl.lit("metadata.drainage_area.other").alias("support_fact"))
    else:
        build["inputs"][0]["usage"] = "reviewed_support"
    expected = "field-mapping declaration" if mutation == "missing_mapping" else None
    with pytest.raises(FatalContractError, match=expected):
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


@pytest.mark.parametrize(
    "location",
    [
        ("src/rivretrieve/_internal/conversion.py", "convert"),
        ("src/rivretrieve/_internal/providers/ca_eccc/bulk.py", "_unpivot_month"),
    ],
)
def test_publication_distinguishes_authored_constants_catalogue_and_runtime_implementations(location):
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
    build = _publication_build().model_dump(mode="python")
    build["declarations"] += (_code(*location, revision="e" * 40),)
    result = _bind_catalogue_build_inputs(
        original,
        CatalogueBuildInputs.model_validate(build),
        _projected_metadata(),
        transformation_implementations={"observation-value": location},
    )
    catalogue, authored, observation = (result.fact_bindings[index].transformation for index in (1, 2, 3))
    assert catalogue.executable.symbol == "build_catalogue"
    assert catalogue.executable.repository_path.endswith("/synthetic/generate_catalogue.py")
    assert authored.executable is None
    assert authored.declaration.symbol == "build_catalogue"
    assert (observation.executable.repository_path, observation.executable.symbol) == location
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
        schema_version=3,
        archive_code_revision="f" * 40,
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
    assert frame["state"].to_list() == ["no_metadata"] * 4
    assert frame["support_fact"].null_count() == 4


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


@pytest.mark.parametrize(
    "provider_id,group,location",
    [
        (
            "ca_eccc",
            "canonical_observation_shape",
            ("src/rivretrieve/_internal/providers/ca_eccc/bulk.py", "_unpivot_month"),
        ),
        ("ch_foen", "canonical_observation_shape", ("src/rivretrieve/_internal/providers/ch_foen/parse.py", "parse")),
        ("cz_chmi", "canonical_observation", ("src/rivretrieve/_internal/conversion.py", "convert")),
        ("lt_lhmt", "canonical_observation", ("src/rivretrieve/_internal/conversion.py", "convert")),
    ],
)
def test_observation_operations_have_explicit_complete_provider_responsibility(provider_id, group, location):
    from importlib import import_module

    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    origins = import_module(f"rivretrieve._internal.providers.{provider_id}.origins")
    original = origins.build_acquisition_provenance()
    assert {group: location} == origins.TRANSFORMATION_IMPLEMENTATIONS
    observation_groups = {
        binding.fact_group
        for binding in original.fact_bindings
        if binding.transformation is not None
        and any(fact.startswith(("observation.", "canonical.observation.")) for fact in binding.facts)
    }
    assert set(origins.TRANSFORMATION_IMPLEMENTATIONS) == observation_groups
    native = original.native_table
    native_facts = tuple(
        fact
        for binding in original.fact_bindings
        if binding.acquisition_id in origins.NATIVE_TABLE_ACQUISITION_IDS
        for fact in binding.facts
    )
    reference = _member().model_dump(mode="python")
    reference.update(sha256=native.sha256, byte_size=native.byte_size)
    build = CatalogueBuildInputs(
        build=_code(f"src/rivretrieve/_internal/providers/{provider_id}/generate_catalogue.py", "write_catalogue"),
        declarations=tuple(_code(path, symbol, "e" * 40) for path, symbol in origins.CATALOGUE_BUILD_DECLARATIONS),
        inputs=(
            RetainedInputUse(
                reference=ArchiveMemberReference.model_validate(reference), usage="native_table", facts=native_facts
            ),
        ),
    )
    with pytest.raises(FatalContractError, match="responsibility"):
        _bind_catalogue_build_inputs(original, build, _projected_metadata().clear())
    result = _bind_catalogue_build_inputs(
        original,
        build,
        _projected_metadata().clear(),
        transformation_implementations=origins.TRANSFORMATION_IMPLEMENTATIONS,
    )
    transform = next(binding.transformation for binding in result.fact_bindings if binding.fact_group == group)
    assert (transform.executable.repository_path, transform.executable.symbol) == location
    assert transform.executable.revision == build.build.revision
    assert transform.declaration.repository_path == f"src/rivretrieve/_internal/providers/{provider_id}/origins.py"
    assert transform.declaration.symbol == "build_acquisition_provenance"
    assert result.source_records == original.source_records
    assert result.native_table == original.native_table
    assert result.fact_universe == original.fact_universe


@pytest.mark.parametrize(
    "mapping",
    [
        {"absent-group": ("src/rivretrieve/_internal/conversion.py", "convert")},
        {"canonical-location": ("src/unlisted.py", "not_declared")},
    ],
)
def test_explicit_transformation_responsibility_requires_known_group_and_declared_code(mapping):
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    with pytest.raises(FatalContractError):
        _bind_catalogue_build_inputs(
            _provenance(), _publication_build(), _projected_metadata(), transformation_implementations=mapping
        )


def test_station_metadata_notice_is_scoped_verbatim_and_readable_offline(tmp_path, monkeypatch):
    import socket

    import mlcroissant as mlc

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions

    original, origins, files, native, fields = _publication_components()
    payload = original.model_dump(mode="python")
    source = payload["source_records"][0]
    source["acquisitions"] += (
        {
            "acquisition_id": "synthetic-terms",
            "method": "http_request",
            "instant_type": "retrieval",
            "description": "Synthetic source terms",
            "requested_from": ("https://example.org/terms",),
            "retrieved_at_start": "2020-01-01T00:00:00Z",
            "recording_ids": ("synthetic-terms",),
        },
    )
    source["evidence"] = (
        {
            "evidence_id": "synthetic-terms",
            "description": "Synthetic source terms",
            "recording": {
                "recording_id": "synthetic-terms",
                "repository_path": "synthetic/terms.html",
                "source_url": "https://example.org/terms",
                "retrieved_at": "2020-01-01T00:00:00Z",
                "media_type": "text/html",
                "sha256": "0" * 64,
            },
        },
    )
    terms = {
        "license": "Synthetic source licence, exact wording.",
        "citation": "Synthetic source citation, exact wording.",
    }
    source["statements"] = tuple(
        {"kind": kind, "exact_text": words, "recording_id": "synthetic-terms", "fact": f"source.terms.{kind}"}
        for kind, words in terms.items()
    )
    term_facts = tuple(statement["fact"] for statement in source["statements"])
    payload["fact_universe"] += term_facts
    payload["fact_bindings"] += (
        {
            "fact_group": "synthetic-terms",
            "facts": term_facts,
            "source_id": "issuer",
            "acquisition_id": "synthetic-terms",
        },
    )
    notice = "RivRetrieve station metadata projection. Source names remain verbatim."
    metadata = build_catalogue_metadata(
        AcquisitionProvenance.model_validate(payload),
        origins,
        files,
        build_inputs=_publication_build(),
        native_table=native,
        metadata_fields=fields,
        station_metadata_notice=notice,
        source_descriptions=SourceDescriptions(provider_id="synthetic", descriptions=()),
    )
    descriptor = json.loads(metadata["croissant.json"])
    assert {kind: descriptor[kind] for kind in terms} == terms
    record = next(item for item in descriptor["recordSet"] if item["@id"] == "station_metadata")
    assert record["description"] == notice
    assert notice not in descriptor["description"]
    for name, content in {**files, **metadata}.items():
        (tmp_path / name).write_bytes(content)
    from rivretrieve._internal.catalogues.descriptor import write_catalogue_descriptor

    header = EvidenceHeader.model_validate_json(metadata["provenance.json"])
    evidence = parse_catalogue_evidence(header, {name: metadata[name] for name in header.files})
    write_catalogue_descriptor(
        tmp_path / "croissant.json",
        evidence,
        origins,
        {**files, **{name: content for name, content in metadata.items() if name != "croissant.json"}},
        station_metadata_notice=notice,
    )
    assert json.loads((tmp_path / "croissant.json").read_text()) == descriptor

    def deny_network(*args, **kwargs):
        raise AssertionError("Metadata notice inspection attempted network access")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    dataset = mlc.Dataset(tmp_path / "croissant.json")
    loaded = next(record for record in dataset.metadata.record_sets if record.id == "station_metadata")
    assert loaded.description == notice


@pytest.mark.parametrize("notice", ["", "   "])
def test_station_metadata_notice_requires_nonblank_text(notice):
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions
    from rivretrieve._internal.issues import FatalContractError

    original, origins, files, native, fields = _publication_components()
    with pytest.raises(FatalContractError, match="nonblank"):
        build_catalogue_metadata(
            original,
            origins,
            files,
            build_inputs=_publication_build(),
            native_table=native,
            metadata_fields=fields,
            station_metadata_notice=notice,
            source_descriptions=SourceDescriptions(provider_id="synthetic", descriptions=()),
        )


def _supported_provenance():
    from rivretrieve._internal.acquisition_provenance import RetainedSupportUse

    first = _member()
    same_bytes_elsewhere = ArchiveMemberReference.model_validate({**first.model_dump(), "collection_id": "another"})
    verifier = _code("maintenance/verify.py", "main")
    payload = _provenance().model_dump(mode="python")
    payload["build_inputs"]["support"] = (
        RetainedSupportUse(
            reference=first,
            verifier=verifier,
            verification_kind="full_positive",
            facts=("native.latitude",),
            member_selector="body/first.json",
        ),
        RetainedSupportUse(
            reference=first,
            verifier=verifier,
            verification_kind="full_positive",
            facts=("native.latitude",),
            member_selector="body/second.json",
        ),
        RetainedSupportUse(
            reference=same_bytes_elsewhere,
            verifier=_code("maintenance/verify.py", "other"),
            verification_kind="full_positive",
            facts=("native.latitude",),
            member_selector="body/third.json",
        ),
    )
    return AcquisitionProvenance.model_validate(payload)


def test_normalized_header_interns_exact_support_identities_without_changing_logical_build_inputs():
    original = _supported_provenance()
    evidence = _normalize(original)
    files = encode_catalogue_evidence(evidence)
    encoded_header = json.loads(files.pop("provenance.json"))
    encoded = encoded_header["build_inputs"]
    assert encoded["encoding_version"] == 1
    assert len(encoded["support_references"]) == len(encoded["support_verifiers"]) == 2
    assert [item["reference"] for item in encoded["support"]] == [0, 0, 1]
    assert [item["verifier"] for item in encoded["support"]] == [0, 0, 1]
    assert "encoding_version" not in original.build_inputs.model_dump(mode="json")
    with pytest.raises(ValidationError):
        CatalogueBuildInputs.model_validate(encoded)
    header = EvidenceHeader.model_validate_json(json.dumps(encoded_header))
    parsed = parse_catalogue_evidence(header, files)
    json_roundtrip = CatalogueEvidence.model_validate_json(parsed.model_dump_json())
    for item in (evidence, parsed, json_roundtrip):
        assert item.header.build_inputs == original.build_inputs
        support = item.header.build_inputs.support
        assert support[0].reference is support[1].reference
        assert support[0].verifier is support[1].verifier
        assert support[0].reference is not support[2].reference
        assert support[0].verifier is not support[2].verifier
        assert support[0].reference.sha256 == support[2].reference.sha256
        assert reconstruct_provenance(item) == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference", True),
        ("reference", -1),
        ("reference", 2),
        ("reference", "0"),
        ("verifier", False),
        ("verifier", -1),
        ("verifier", 2),
        ("verifier", 0.0),
    ],
)
def test_interned_support_indices_are_strict_bounded_ordinals(field, value):
    payload = _normalize(_supported_provenance()).header.model_dump(mode="json")
    payload["build_inputs"]["support"][0][field] = value
    with pytest.raises(ValidationError):
        EvidenceHeader.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("pool", ["support_references", "support_verifiers"])
@pytest.mark.parametrize("mutation", ["duplicate", "unused", "missing"])
def test_interned_support_pools_are_unique_used_and_closed(pool, mutation):
    payload = _normalize(_supported_provenance()).header.model_dump(mode="json")
    values = payload["build_inputs"][pool]
    if mutation == "missing":
        values.pop()
    else:
        extra = dict(values[0])
        if mutation == "unused":
            extra["artifact_id" if pool == "support_references" else "symbol"] = "unused"
        values.append(extra)
    with pytest.raises(ValidationError, match="pool"):
        EvidenceHeader.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("version", [2, True])
def test_header_encoding_is_declared_and_does_not_accept_cli_build_input_json(version):
    original = _supported_provenance()
    payload = _normalize(original).header.model_dump(mode="json")
    payload["build_inputs"]["encoding_version"] = version
    with pytest.raises(ValidationError):
        EvidenceHeader.model_validate_json(json.dumps(payload))
    payload["build_inputs"] = original.build_inputs.model_dump(mode="json")
    with pytest.raises(ValidationError, match="encoding_version"):
        EvidenceHeader.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_header_json_schema_declares_pooled_wire_form_while_cli_schema_stays_logical(mode):
    schema = EvidenceHeader.model_json_schema(mode=mode)
    build_reference = next(item["$ref"] for item in schema["properties"]["build_inputs"]["anyOf"] if "$ref" in item)
    encoded = schema["$defs"][build_reference.rsplit("/", 1)[1]]
    assert {"encoding_version", "support_references", "support_verifiers", "support"} <= set(encoded["properties"])
    edge_reference = encoded["properties"]["support"]["items"]["$ref"]
    edge = schema["$defs"][edge_reference.rsplit("/", 1)[1]]
    for field in ("reference", "verifier"):
        assert edge["properties"][field]["type"] == "integer"
        assert edge["properties"][field]["minimum"] == 0
    logical = CatalogueBuildInputs.model_json_schema(mode=mode)
    assert "encoding_version" not in logical["properties"]
    logical_edge_reference = logical["properties"]["support"]["items"]["$ref"]
    logical_edge = logical["$defs"][logical_edge_reference.rsplit("/", 1)[1]]
    assert "$ref" in logical_edge["properties"]["reference"]
    assert "$ref" in logical_edge["properties"]["verifier"]


@pytest.mark.parametrize("mutation", ["reference_hash", "verifier_revision", "selector"])
def test_header_revalidation_rejects_unchecked_copied_support_identities(mutation):
    evidence = _normalize(_supported_provenance())
    build = evidence.header.build_inputs
    first = build.support[0]
    if mutation == "reference_hash":
        first = first.model_copy(update={"reference": first.reference.model_copy(update={"sha256": "invalid"})})
    elif mutation == "verifier_revision":
        first = first.model_copy(update={"verifier": first.verifier.model_copy(update={"revision": "e" * 40})})
    else:
        first = first.model_copy(update={"member_selector": "../unvalidated"})
    unchecked = evidence.header.model_copy(
        update={"build_inputs": build.model_copy(update={"support": (first, *build.support[1:])})}
    )
    files = encode_catalogue_evidence(evidence)
    files.pop("provenance.json")
    with pytest.raises(ValidationError):
        parse_catalogue_evidence(unchecked, files)
    with pytest.raises(ValidationError):
        encode_catalogue_evidence(evidence.model_copy(update={"header": unchecked}))


def test_private_declarations_and_verifiers_keep_independent_reviewed_revision():
    from rivretrieve._internal.acquisition_provenance import RetainedSupportUse

    private = CodeReference(
        repository="https://github.com/RivRetrieve/verification-evidence",
        revision="f" * 40,
        repository_path="declarations/synthetic/ledger.json",
    )
    verifier = private.model_copy(update={"repository_path": "verification/synthetic/verify.py", "symbol": "main"})
    build = CatalogueBuildInputs.model_validate(
        {
            **_build().model_dump(),
            "declarations": (*_build().declarations, private),
            "support": (
                RetainedSupportUse(
                    reference=_member(),
                    facts=("native.latitude",),
                    verification_kind="full_positive",
                    verifier=verifier,
                ),
            ),
        }
    )
    provenance = AcquisitionProvenance.model_validate({**_provenance().model_dump(), "build_inputs": build})
    files = encode_catalogue_evidence(_normalize(provenance))
    header = EvidenceHeader.model_validate_json(files.pop("provenance.json"))
    restored = reconstruct_provenance(parse_catalogue_evidence(header, files))
    assert restored.build_inputs == build
    wrong = build.model_dump()
    wrong["support"][0]["verifier"]["revision"] = build.build.revision
    with pytest.raises(ValidationError, match="owner's reviewed revision"):
        CatalogueBuildInputs.model_validate(wrong)
    wrong = build.model_dump()
    wrong["build"]["repository"] = private.repository
    with pytest.raises(ValidationError, match="public library"):
        CatalogueBuildInputs.model_validate(wrong)


def test_private_reference_cannot_impersonate_public_transformation_executable():
    document = _provenance().model_dump()
    transformation = document["fact_bindings"][1]["transformation"]
    transformation["executable"]["repository"] = "https://github.com/RivRetrieve/verification-evidence"
    with pytest.raises(ValidationError, match="owner or revision"):
        AcquisitionProvenance.model_validate(document)


def _elevation_publication():
    from rivretrieve._internal.catalogues.station_metadata import MetadataField
    from rivretrieve._internal.station_metadata import SOURCE_METADATA_SCHEMA

    original = _provenance().model_dump(mode="python")
    original["fact_universe"] = (*original["fact_universe"], "source.height_unit", "source.height_datum")
    original["fact_bindings"] = list(original["fact_bindings"])
    source = original["source_records"][0]
    source["acquisitions"] = (
        *source["acquisitions"],
        {
            **source["acquisitions"][0],
            "acquisition_id": "height-definition",
        },
    )
    original["fact_bindings"].append(
        {
            "fact_group": "height-definition",
            "facts": ("source.height_unit", "source.height_datum"),
            "source_id": "issuer",
            "acquisition_id": "height-definition",
        }
    )
    build = _publication_build().model_dump(mode="python")
    build["inputs"] = (
        *build["inputs"],
        {
            "reference": _member(_reference(artifact_id="height-definition", role="publisher_original")),
            "usage": "reviewed_support",
            "facts": ("source.height_unit", "source.height_datum"),
        },
    )
    field = MetadataField(
        "elevation",
        "height",
        "m",
        datum_field="code",
        datum_support=("source.height_datum",),
        support_facts=("source.height_unit",),
    )
    metadata = pl.DataFrame(
        [
            {
                "provider_id": "synthetic",
                "station_id": "001",
                "attribute_role": "elevation",
                "source_field": "height",
                "source_value": "3.0",
                "source_dtype": "Float64",
                "source_unit": "m",
                "state": "value",
                "support_fact": "metadata.elevation.height",
                "source_datum": "3",
                "source_datum_field": "code",
                "source_datum_dtype": "Int64",
                "datum_support_fact": "metadata.elevation.height.datum",
            }
        ],
        schema=SOURCE_METADATA_SCHEMA,
    )
    return AcquisitionProvenance.model_validate(original), CatalogueBuildInputs.model_validate(build), field, metadata


def test_publication_binds_value_semantics_and_datum_association_separately():
    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs

    original, build, field, metadata = _elevation_publication()
    bound = _bind_catalogue_build_inputs(original, build, metadata, metadata_fields=(field,))
    bindings = {binding.fact_group: binding for binding in bound.fact_bindings}
    value = bindings["metadata.elevation.height"].transformation
    datum = bindings["metadata.elevation.height.datum"].transformation
    assert [(item.source_id, item.fact) for item in value.external_inputs] == [
        ("issuer", "native.latitude"),
        ("issuer", "source.height_unit"),
    ]
    assert [(item.source_id, item.fact) for item in datum.external_inputs] == [
        ("issuer", "native.latitude"),
        ("issuer", "source.height_datum"),
    ]
    assert datum.name == "associate_elevation_datum"
    assert datum.declaration.symbol == "STATION_METADATA_FIELDS"
    assert datum.executable.symbol == "build_station_metadata"
    assert bound.source_records == original.source_records
    repeated = _bind_catalogue_build_inputs(_normalize(bound), build, metadata, metadata_fields=(field,))
    assert repeated == bound


@pytest.mark.parametrize("fault", ["missing_declaration", "wrong_datum_field", "missing_fact", "unadopted", "runtime"])
def test_publication_rejects_unsupported_datum_association(fault):
    from dataclasses import replace

    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    original, build, field, metadata = _elevation_publication()
    if fault == "wrong_datum_field":
        field = replace(field, datum_field="other_code")
    elif fault == "missing_fact":
        field = replace(field, datum_support=("source.absent",))
    elif fault == "unadopted":
        payload = build.model_dump(mode="python")
        payload["inputs"] = payload["inputs"][:1]
        build = CatalogueBuildInputs.model_validate(payload)
        field = replace(field, support_facts=())
    elif fault == "runtime":
        payload = original.model_dump(mode="python")
        acquisition = payload["source_records"][0]["acquisitions"][1]
        acquisition.update(method="runtime_http_request", instant_type="runtime", retrieved_at_start=None)
        original = AcquisitionProvenance.model_validate_json(
            json.dumps(payload, default=str).replace("source.height_", "source.observation.height_")
        )
        build = CatalogueBuildInputs.model_validate_json(
            build.model_dump_json().replace("source.height_", "source.observation.height_")
        )
        field = replace(field, support_facts=(), datum_support=("source.observation.height_datum",))
    with pytest.raises(FatalContractError):
        _bind_catalogue_build_inputs(
            original, build, metadata, metadata_fields=() if fault == "missing_declaration" else (field,)
        )


def test_publication_rejects_unbound_field_semantics():
    from dataclasses import replace

    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs
    from rivretrieve._internal.issues import FatalContractError

    original, build, field, metadata = _elevation_publication()
    with pytest.raises(FatalContractError, match="adopted direct source fact"):
        _bind_catalogue_build_inputs(
            original, build, metadata, metadata_fields=(replace(field, support_facts=("source.absent",)),)
        )


def test_descriptor_requires_bound_datum_association_support():
    from io import BytesIO

    from rivretrieve._internal.catalogues.descriptor import build_catalogue_descriptor
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions
    from rivretrieve._internal.catalogues.station_metadata import MetadataField
    from rivretrieve._internal.issues import FatalContractError

    original, origins, files, native, _ = _publication_components()
    products = build_catalogue_metadata(
        original,
        origins,
        files,
        build_inputs=_publication_build(),
        native_table=native,
        metadata_fields=(
            MetadataField("elevation", "area", datum="Synthetic datum", datum_support=("native.latitude",)),
        ),
        source_descriptions=SourceDescriptions(provider_id="synthetic", descriptions=()),
    )
    header = EvidenceHeader.model_validate_json(products["provenance.json"])
    evidence = parse_catalogue_evidence(header, {name: products[name] for name in header.files})
    # Keep a structurally valid native-field association but remove its bound fact.
    frame = pl.read_parquet(BytesIO(products["station_metadata.parquet"]))
    assert frame.filter(pl.col("attribute_role") == "elevation")["source_datum"].item() == "Synthetic datum"
    descriptor = json.loads(products.pop("croissant.json"))
    record = next(record for record in descriptor["recordSet"] if record["@id"] == "station_metadata")
    datum = next(field for field in record["field"] if field["@id"] == "station_metadata/datum_support_fact")
    assert datum["references"]["extract"]["column"] == "name"
    frame = frame.with_columns(
        pl.when(pl.col("attribute_role") == "elevation")
        .then(pl.lit("other"))
        .otherwise(pl.col("source_field"))
        .alias("source_field"),
        pl.when(pl.col("attribute_role") == "elevation")
        .then(pl.lit("metadata.elevation.other.datum"))
        .otherwise(pl.col("datum_support_fact"))
        .alias("datum_support_fact"),
    )
    buffer = BytesIO()
    frame.write_parquet(buffer)
    products["station_metadata.parquet"] = buffer.getvalue()
    with pytest.raises(FatalContractError, match="support facts must resolve"):
        build_catalogue_descriptor(evidence, origins, {**files, **products})


_SCOPED_METADATA_IMPLEMENTATION = (
    "src/rivretrieve/_internal/providers/synthetic/station_metadata.py",
    "project_station_metadata",
)


def _scoped_metadata_publication():
    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.catalogues.native import NativeTable
    from rivretrieve._internal.catalogues.station_metadata import MetadataField, build_station_metadata

    original, origins, files, native, _ = _publication_components()
    payload = original.model_dump(mode="python")
    payload["fact_universe"] = (*payload["fact_universe"], "source.site")
    payload["fact_bindings"] = (
        *payload["fact_bindings"],
        {
            "fact_group": "site-source",
            "facts": ("source.site",),
            "source_id": "issuer",
            "acquisition_id": "site-acquisition",
        },
    )
    source = payload["source_records"][0]
    source["acquisitions"] = (
        *source["acquisitions"],
        {
            **source["acquisitions"][0],
            "acquisition_id": "site-acquisition",
        },
    )
    build = _publication_build().model_dump(mode="python")
    build["declarations"] = (*build["declarations"], _code(*_SCOPED_METADATA_IMPLEMENTATION, revision="e" * 40))
    build["inputs"] = (
        *build["inputs"],
        {
            "reference": _member(_reference(artifact_id="site-response", role="publisher_original")),
            "usage": "original",
            "facts": ("source.site",),
        },
    )
    native = NativeTable(native.data.with_columns(pl.lit("Station river").alias("name")))
    site = NativeTable(native.data.with_columns(pl.lit("Site river").alias("name")))
    fields = (
        MetadataField("water_body_name", "name", source_scope="station"),
        MetadataField("water_body_name", "name", source_scope="site", source_facts=("source.site",)),
    )
    stations = pl.DataFrame({"station_id": ["001"]})
    station_rows = build_station_metadata("synthetic", native, stations, Field(NativeColumn("station_id")), fields[:1])
    site_rows = build_station_metadata("synthetic", site, stations, Field(NativeColumn("station_id")), fields[1:])
    projection = pl.concat([station_rows, site_rows.filter(pl.col("state") != "no_metadata")])
    return (
        AcquisitionProvenance.model_validate(payload),
        CatalogueBuildInputs.model_validate(build),
        origins,
        files,
        native,
        fields,
        projection,
    )


def test_explicit_projection_keeps_scoped_sources_and_their_own_acquisitions():
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions

    original, build, origins, files, native, fields, projection = _scoped_metadata_publication()
    products = build_catalogue_metadata(
        original,
        origins,
        files,
        build_inputs=build,
        native_table=native,
        metadata_fields=fields,
        station_metadata=projection,
        metadata_implementation=_SCOPED_METADATA_IMPLEMENTATION,
        source_descriptions=SourceDescriptions(provider_id="synthetic", descriptions=()),
    )
    header = EvidenceHeader.model_validate_json(products["provenance.json"])
    evidence = parse_catalogue_evidence(header, {name: products[name] for name in header.files})
    bound = reconstruct_provenance(evidence)
    bindings = {binding.fact_group: binding for binding in bound.fact_bindings}
    assert [item.fact for item in bindings["metadata.water_body_name.station.name"].transformation.external_inputs] == [
        "native.latitude"
    ]
    assert [item.fact for item in bindings["metadata.water_body_name.site.name"].transformation.external_inputs] == [
        "source.site"
    ]
    site_binding = next(binding for binding in bound.fact_bindings if "source.site" in binding.facts)
    assert site_binding.acquisition_id == "site-acquisition"
    assert bindings["metadata.water_body_name.site.name"].transformation.executable == _code(
        *_SCOPED_METADATA_IMPLEMENTATION
    )
    result = pl.read_parquet(BytesIO(products["station_metadata.parquet"]))
    assert result.filter(pl.col("attribute_role") == "water_body_name").select(
        "source_scope", "source_value"
    ).rows() == [
        ("site", '"Site river"'),
        ("station", '"Station river"'),
    ]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_projection",
        "missing_implementation",
        "undeclared_implementation",
        "wrong_scope",
        "missing_declaration",
        "wrong_unit",
        "undeclared_source",
        "unadopted_source",
        "unknown_source",
        "outside_station",
    ],
)
def test_explicit_projection_rejects_unmatched_scope_or_source(fault):
    from dataclasses import replace

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions
    from rivretrieve._internal.issues import FatalContractError

    original, build, origins, files, native, fields, projection = _scoped_metadata_publication()
    implementation = _SCOPED_METADATA_IMPLEMENTATION
    if fault == "missing_projection":
        projection = None
        implementation = None
    elif fault == "missing_implementation":
        implementation = None
    elif fault == "undeclared_implementation":
        implementation = (_SCOPED_METADATA_IMPLEMENTATION[0], "undeclared")
    elif fault == "wrong_scope":
        fields = (fields[0], replace(fields[1], source_scope="other"))
    elif fault == "missing_declaration":
        fields = fields[:1]
    elif fault == "wrong_unit":
        fields = (replace(fields[0], source_unit="unsupported"), fields[1])
    elif fault == "undeclared_source":
        fields = (fields[0], replace(fields[1], source_field="supplement", source_facts=()))
        projection = projection.with_columns(
            pl.when(pl.col("source_scope") == "site")
            .then(pl.lit("supplement"))
            .otherwise(pl.col("source_field"))
            .alias("source_field"),
            pl.when(pl.col("source_scope") == "site")
            .then(pl.lit("metadata.water_body_name.site.supplement"))
            .otherwise(pl.col("support_fact"))
            .alias("support_fact"),
        )
    elif fault == "unadopted_source":
        build = build.model_copy(update={"inputs": build.inputs[:1]})
    elif fault == "unknown_source":
        fields = (fields[0], replace(fields[1], source_facts=("source.unknown",)))
    else:
        projection = projection.with_columns(pl.lit("outside").alias("station_id"))
    with pytest.raises(FatalContractError):
        build_catalogue_metadata(
            original,
            origins,
            files,
            build_inputs=build,
            native_table=native,
            metadata_fields=fields,
            station_metadata=projection,
            metadata_implementation=implementation,
            source_descriptions=SourceDescriptions(provider_id="synthetic", descriptions=()),
        )


def test_scoped_datum_binding_uses_its_declared_source():
    from dataclasses import replace

    from rivretrieve._internal.catalogues.publication import _bind_catalogue_build_inputs

    original, build, field, metadata = _elevation_publication()
    field = replace(field, source_scope="site", source_facts=("source.height_unit",))
    metadata = metadata.with_columns(
        pl.lit("site").alias("source_scope"),
        pl.lit("metadata.elevation.site.height").alias("support_fact"),
        pl.lit("metadata.elevation.site.height.datum").alias("datum_support_fact"),
    )
    result = _bind_catalogue_build_inputs(original, build, metadata, metadata_fields=(field,))
    binding = next(
        binding for binding in result.fact_bindings if binding.fact_group == "metadata.elevation.site.height.datum"
    )
    assert [item.fact for item in binding.transformation.external_inputs] == [
        "source.height_unit",
        "source.height_datum",
    ]


def _publish_explicit_metadata(components):
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions

    original, build, origins, files, native, fields, projection = components
    return build_catalogue_metadata(
        original,
        origins,
        files,
        build_inputs=build,
        native_table=native,
        metadata_fields=fields,
        station_metadata=projection,
        metadata_implementation=_SCOPED_METADATA_IMPLEMENTATION,
        source_descriptions=SourceDescriptions(provider_id="synthetic", descriptions=()),
    )


def test_explicit_projection_rejects_supplementary_value_claiming_native_support():
    from dataclasses import replace

    from rivretrieve._internal.issues import FatalContractError

    components = list(_scoped_metadata_publication())
    fields = components[5]
    components[5] = (fields[0], replace(fields[1], source_facts=()))
    with pytest.raises(FatalContractError, match="historical native projection"):
        _publish_explicit_metadata(components)


def _native_elevation_projection():
    from rivretrieve._internal.catalogues.native import NativeTable
    from rivretrieve._internal.catalogues.station_metadata import build_station_metadata

    original, build, origins, files, native, _, _ = _scoped_metadata_publication()
    elevation_original, elevation_build, field, _ = _elevation_publication()
    payload = original.model_dump(mode="python")
    payload["fact_universe"] = (*payload["fact_universe"], "source.height_unit", "source.height_datum")
    payload["fact_bindings"] = (*payload["fact_bindings"], elevation_original.fact_bindings[-1])
    payload["source_records"][0]["acquisitions"] = (
        *payload["source_records"][0]["acquisitions"],
        elevation_original.source_records[0].acquisitions[-1],
    )
    original = AcquisitionProvenance.model_validate(payload)
    build = build.model_copy(update={"inputs": (*build.inputs, elevation_build.inputs[-1])})
    native = NativeTable(native.data.with_columns(pl.lit(3.0).alias("height"), pl.lit(3, dtype=pl.Int64).alias("code")))
    projection = build_station_metadata(
        "synthetic",
        native,
        pl.DataFrame({"station_id": ["001"]}),
        origins[0]["station_id"],
        (field,),
    )
    return [original, build, origins, files, native, (field,), projection]


@pytest.mark.parametrize(
    "changes",
    [
        {"source_value": "4.0"},
        {"source_dtype": "Float32"},
        {"source_value": "3", "source_dtype": "Int64"},
        {"source_value": None, "state": "source_null"},
        {"source_datum": "4"},
        {"source_datum_dtype": "Int32"},
        {"source_datum": None},
    ],
)
def test_explicit_projection_rejects_native_value_state_or_datum_mismatch(changes):
    from rivretrieve._internal.issues import FatalContractError

    components = _native_elevation_projection()
    components[-1] = components[-1].with_columns(
        pl.when(pl.col("attribute_role") == "elevation")
        .then(pl.lit(value, dtype=pl.String))
        .otherwise(pl.col(column))
        .alias(column)
        for column, value in changes.items()
    )
    with pytest.raises(FatalContractError, match="historical native projection"):
        _publish_explicit_metadata(components)


@pytest.mark.parametrize("source_null", [False, True])
def test_explicit_projection_preserves_matching_native_elevation(source_null):
    from io import BytesIO

    from polars.testing import assert_frame_equal

    from rivretrieve._internal.catalogues.native import NativeTable

    components = _native_elevation_projection()
    if source_null:
        components[4] = NativeTable(components[4].data.with_columns(pl.lit(None, dtype=pl.Float64).alias("height")))
        components[-1] = components[-1].with_columns(
            pl.lit(None, dtype=pl.String).alias("source_value"),
            pl.when(pl.col("attribute_role") == "elevation")
            .then(pl.lit("source_null"))
            .otherwise(pl.col("state"))
            .alias("state"),
        )
    products = _publish_explicit_metadata(components)
    assert_frame_equal(pl.read_parquet(BytesIO(products["station_metadata.parquet"])), components[-1])


@pytest.mark.parametrize("wrong_station", [False, True])
def test_explicit_projection_matches_converted_station_and_preserves_non_exposure(wrong_station):
    from io import BytesIO

    from polars.testing import assert_frame_equal

    from rivretrieve._internal.catalogue_origins import ConversionName, Field, FieldConversion, NativeColumn
    from rivretrieve._internal.catalogues.native import NativeTable
    from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.station_metadata import source_metadata_frame

    class PaddedIdentity(FieldConversion):
        @property
        def name(self):
            return ConversionName("padded_identity")

        def apply(self, canonical_column, native_column, native_row):
            return native_row[native_column].zfill(3)

    components = list(_scoped_metadata_publication())
    _, _, origins, files, _, fields, projection = components
    origin = Field(NativeColumn("station_id"), PaddedIdentity())
    components[2] = ({**origins[0], "station_id": origin},)
    stations = pl.read_parquet(BytesIO(files["stations.parquet"]))
    stations = pl.concat([stations, stations.with_columns(pl.lit("002").alias("station_id"))])
    buffer = BytesIO()
    stations.write_parquet(buffer)
    components[3] = {**files, "stations.parquet": buffer.getvalue()}
    native = NativeTable(
        pl.DataFrame({"station_id": ["2", "1"], "name": ["Other river", "Station river"]}).with_columns(
            pl.lit(components[4].data["retrieved_at"][0]).alias("retrieved_at")
        )
    )
    components[4] = native
    second = build_station_metadata("synthetic", native, stations.filter(pl.col("station_id") == "002"), origin, ())
    # The native field and supplementary field are both unexposed at station 002.
    components[-1] = source_metadata_frame(
        stations.select("provider_id", "station_id"), pl.concat([projection, second])
    )
    if wrong_station:
        components[-1] = components[-1].with_columns(
            pl.when(pl.col("source_scope") == "station")
            .then(pl.lit('"Other river"'))
            .otherwise(pl.col("source_value"))
            .alias("source_value")
        )
        with pytest.raises(FatalContractError, match="historical native projection"):
            _publish_explicit_metadata(components)
    else:
        products = _publish_explicit_metadata(components)
        assert_frame_equal(pl.read_parquet(BytesIO(products["station_metadata.parquet"])), components[-1])
