"""catalogue descriptor : AcquisitionProvenance × OriginDeclarations × CatalogueFiles → JSONLD (pure); publication : JSONLD × DescriptorPath → File."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal, TypedDict

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    FactBinding,
    SourceRecord,
    _catalogue_fact_identity,
    verified_source_terms,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    Documented,
    Field,
    NotPublished,
    OriginDeclarations,
    Withheld,
)
from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
from rivretrieve._internal.catalogues.schemas import PROVIDER_INFO_CATALOG_SCHEMA
from rivretrieve._internal.issues import FatalContractError

ABSENCE_NAMESPACE = "https://github.com/RivRetrieve/RivRetrieve/blob/main/docs/catalogue-absence.md#"


class WithheldAbsence(TypedDict):
    kind: Literal["withheld"]
    reason: str


class NotPublishedAbsence(TypedDict):
    kind: Literal["not_published"]
    evidence: str | list[str]


def _context() -> dict[str, object]:
    return {
        "@vocab": "https://schema.org/",
        "@language": None,
        "sc": "https://schema.org/",
        "cr": "http://mlcommons.org/croissant/",
        "dct": "http://purl.org/dc/terms/",
        "rr": ABSENCE_NAMESPACE,
        "conformsTo": "dct:conformsTo",
        "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
        "rr:absence": {"@id": "rr:absence", "@type": "@json"},
        **{
            name: f"cr:{name}"
            for name in ("recordSet", "field", "source", "fileObject", "extract", "column", "jsonPath")
        },
    }


def _organization(name: str) -> dict[str, str]:
    return {"@type": "sc:Organization", "name": name}


def _reference(identity: str) -> dict[str, object]:
    return {"@id": identity}


def _source_terms(source: SourceRecord) -> dict[str, object]:
    terms: dict[str, object] = dict(verified_source_terms((source,)))
    usage = [
        {"@type": "sc:CreativeWork", "name": statement.kind, "text": statement.exact_text}
        for statement in source.statements
        if statement.kind in {"terms", "access"} and statement.verification_status == "verified_public_recording"
    ]
    if usage:
        terms["usageInfo"] = usage
    return terms


def _source_identity(source: SourceRecord, acquisition: AcquisitionRecord) -> str:
    return f"acquisition/{source.source_id}/{acquisition.acquisition_id}"


def _acquired_material(source: SourceRecord, acquisition: AcquisitionRecord) -> dict[str, object]:
    """Describe acquired material without turning a receipt into a download claim."""
    node: dict[str, object] = {
        "@id": _source_identity(source, acquisition),
        "@type": "sc:MediaObject" if acquisition.material is not None else "sc:CreativeWork",
        "identifier": acquisition.acquisition_id,
        "name": acquisition.method,
        "description": acquisition.description,
        "creator": _organization(source.issuer),
        **_source_terms(source),
    }
    if source.operator is not None:
        node["provider"] = _organization(source.operator)
    public_locations = [url for url in acquisition.requested_from if url.startswith(("http://", "https://"))]
    if public_locations:
        node["url"] = public_locations
    if acquisition.material is not None:
        node.update(
            name=acquisition.material.filename,
            sha256=acquisition.material.sha256,
            contentSize=f"{acquisition.material.byte_count} B",
        )
    event: dict[str, object] = {
        "@type": "sc:Event",
        "name": acquisition.instant_type,
        "description": acquisition.description,
    }
    if acquisition.retrieved_at_start is not None:
        event["startDate"] = acquisition.retrieved_at_start.isoformat()
    if acquisition.retrieved_at_end is not None:
        event["endDate"] = acquisition.retrieved_at_end.isoformat()
    node["subjectOf"] = event
    return node


def _source_description(source: SourceRecord) -> dict[str, object]:
    historical = [
        _acquired_material(source, item) for item in source.acquisitions if item.method != "corroborating_receipt"
    ]
    corroboration = [
        _acquired_material(source, item) for item in source.acquisitions if item.method == "corroborating_receipt"
    ]
    description: dict[str, object] = {
        "@id": f"issuer/{source.source_id}",
        "@type": "sc:CreativeWork",
        "identifier": source.source_id,
        "name": f"Recorded material issued by {source.issuer}",
        "creator": _organization(source.issuer),
        "hasPart": historical,
        **_source_terms(source),
    }
    if corroboration:
        description["subjectOf"] = {
            "@type": "sc:CreativeWork",
            "name": "Separate corroborating material; not the historical acquisition",
            "citation": corroboration,
        }
    return description


def _lineage(
    provenance: AcquisitionProvenance,
) -> tuple[dict[str, FactBinding], dict[str, dict[str, object]], dict[str, str]]:
    bindings = {fact: binding for binding in provenance.fact_bindings for fact in binding.facts}
    withheld: dict[str, str] = {fact: item.reason for item in provenance.withheld_facts for fact in item.facts}
    acquisitions = {
        (source.source_id, acquisition.acquisition_id): _source_identity(source, acquisition)
        for source in provenance.source_records
        for acquisition in source.acquisitions
        if acquisition.method != "corroborating_receipt"
    }
    documents: dict[str, dict[str, object]] = {}
    visiting: set[str] = set()

    def resolve(binding: FactBinding) -> str:
        identity = f"lineage/{binding.fact_group}"
        if identity in documents:
            return identity
        if identity in visiting:
            raise FatalContractError(f"Cyclic catalogue lineage: {binding.fact_group}")
        visiting.add(identity)
        node: dict[str, object] = {
            "@id": identity,
            "@type": "sc:CreativeWork",
            "identifier": binding.fact_group,
            "creator": _organization("RivRetrieve"),
            "url": f"provenance.json#/fact_bindings/{provenance.fact_bindings.index(binding)}",
        }
        if binding.transformation is None:
            assert binding.source_id is not None and binding.acquisition_id is not None
            key = (binding.source_id, binding.acquisition_id)
            if key not in acquisitions:
                raise FatalContractError(f"Catalogue lineage is not an established historical acquisition: {key}")
            node["isBasedOn"] = [_reference(acquisitions[key])]
            node["description"] = binding.fact_group
        else:
            node["description"] = binding.transformation.name
            inputs: list[dict[str, object]] = []
            seen: set[str] = set()
            for external in binding.transformation.external_inputs:
                if external.fact in withheld:
                    input_id = f"withheld/{external.fact}"
                    if input_id not in seen:
                        inputs.append(
                            {
                                "@id": input_id,
                                "@type": "sc:CreativeWork",
                                "identifier": external.fact,
                                "name": "Withheld source fact",
                                "description": withheld[external.fact],
                            }
                        )
                elif external.fact in bindings:
                    input_id = resolve(bindings[external.fact])
                    if input_id not in seen:
                        inputs.append(_reference(input_id))
                else:
                    raise FatalContractError(f"Catalogue lineage has no acquisition or absence for {external.fact}")
                seen.add(input_id)
            if inputs:
                node["isBasedOn"] = inputs
        visiting.remove(identity)
        documents[identity] = node
        return identity

    canonical = {"provider", "product", "station", "station_product"}
    for fact, binding in bindings.items():
        if fact.partition(".")[0] in canonical or _catalogue_fact_identity(fact) is not None:
            resolve(binding)
    return bindings, documents, withheld


def _origin_description(origin: object) -> str:
    if isinstance(origin, Field):
        return f"Native column {origin.native_column}; conversion {origin.conversion.name}."
    if isinstance(origin, Documented):
        return f"Documented value {origin.value}; evidence {origin.evidence}."
    if isinstance(origin, Authored):
        return f"RivRetrieve-authored provider identity {origin.value}."
    if isinstance(origin, NotPublished):
        return f"Not published; evidence {origin.evidence}."
    if isinstance(origin, Withheld):
        return "Source fact withheld because acquisition is not established."
    raise FatalContractError(f"Unsupported catalogue origin: {origin!r}")


def _data_type(dtype: pl.DataType) -> str:
    if dtype == pl.Boolean:
        return "sc:Boolean"
    if dtype.is_float():
        return "sc:Float"
    if dtype.is_integer():
        return "sc:Integer"
    if dtype == pl.Date:
        return "sc:Date"
    if dtype == pl.String or isinstance(dtype, pl.Enum):
        return "sc:Text"
    raise FatalContractError(f"No Croissant type for catalogue dtype {dtype}")


def build_catalogue_descriptor(
    provenance: AcquisitionProvenance,
    origins: Sequence[OriginDeclarations],
    files: Mapping[str, bytes],
) -> dict[str, object]:
    """Describe exact packaged bytes and their recorded historical inputs, without IO."""
    if set(files) != set(REQUIRED_ARTIFACT_FILES):
        raise FatalContractError("Descriptor requires exactly the four packaged catalogue files")
    if provenance.native_table is not None and not origins:
        raise FatalContractError("Certified catalogue descriptor requires station origins")
    provider = json.loads(files["provider.json"])
    if provider["provider_id"] != provenance.provider_id:
        raise FatalContractError("Descriptor provider identity disagrees with acquisition provenance")
    tables = {
        "provider": pl.DataFrame([provider], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
        **{
            name: pl.read_parquet(BytesIO(files[f"{name}.parquet"]))
            for name in ("products", "stations", "station_products")
        },
    }
    bindings, lineage, withheld = _lineage(provenance)
    distributions = [
        {
            "@id": name,
            "@type": "cr:FileObject",
            "contentUrl": name,
            "encodingFormat": "application/json" if name.endswith(".json") else "application/x-parquet",
            "sha256": sha256(contents).hexdigest(),
            "contentSize": f"{len(contents)} B",
        }
        for name in REQUIRED_ARTIFACT_FILES
        for contents in (files[name],)
    ]
    record_sets: list[dict[str, object]] = []
    for table_name, table in tables.items():
        carrier = {
            "provider": "provider",
            "products": "product",
            "stations": "station",
            "station_products": "station_product",
        }[table_name]
        filename = "provider.json" if table_name == "provider" else f"{table_name}.parquet"
        fields: list[dict[str, object]] = []
        for column, dtype in table.schema.items():
            fact = f"{carrier}.{column}"
            field: dict[str, object] = {
                "@id": f"{table_name}/{column}",
                "@type": "cr:Field",
                "dataType": _data_type(dtype),
                "source": {
                    "fileObject": _reference(filename),
                    "extract": {"jsonPath": f"$.{column}"} if carrier == "provider" else {"column": column},
                },
            }
            if fact in bindings:
                field["subjectOf"] = _reference(f"lineage/{bindings[fact].fact_group}")
            elif fact not in withheld:
                raise FatalContractError(f"Canonical column has no lineage or withheld fact: {fact}")
            if fact in withheld:
                field["rr:absence"] = WithheldAbsence(kind="withheld", reason=withheld[fact])
            if carrier == "station" and origins:
                if any(column not in declarations for declarations in origins):
                    raise FatalContractError(f"Station column has no origin: {column}")
                declared = [declarations[column] for declarations in origins]
                field["description"] = " ".join(dict.fromkeys(_origin_description(origin) for origin in declared))
                not_published = [origin for origin in declared if isinstance(origin, NotPublished)]
                if not_published:
                    if len(not_published) != len(declared):
                        raise FatalContractError(f"Station column mixes published and absent origins: {column}")
                    evidence = list(dict.fromkeys(str(origin.evidence) for origin in not_published))
                    field["rr:absence"] = NotPublishedAbsence(
                        kind="not_published", evidence=evidence[0] if len(evidence) == 1 else evidence
                    )
                if any(isinstance(origin, Withheld) for origin in declared):
                    if not all(isinstance(origin, Withheld) for origin in declared):
                        raise FatalContractError(f"Station column mixes established and withheld origins: {column}")
                    if fact in withheld:
                        fields.append(field)
                        continue
                    binding = bindings[fact]
                    transformation = binding.transformation
                    if transformation is None:
                        raise FatalContractError(f"Withheld origin has no recorded transformation: {fact}")
                    reasons = {withheld[item.fact] for item in transformation.external_inputs if item.fact in withheld}
                    if len(reasons) != 1:
                        raise FatalContractError(f"Withheld origin has no unique recorded reason: {fact}")
                    field["rr:absence"] = WithheldAbsence(kind="withheld", reason=next(iter(reasons)))
            fields.append(field)
        record: dict[str, object] = {"@id": table_name, "@type": "cr:RecordSet", "field": fields}
        row_bindings = {
            f"lineage/{binding.fact_group}"
            for fact, binding in bindings.items()
            if (identity := _catalogue_fact_identity(fact)) is not None and identity[0] == carrier
        }
        if row_bindings:
            record["subjectOf"] = [_reference(identity) for identity in sorted(row_bindings)]
        row_locators = {
            locator
            for item in provenance.withheld_facts
            for locator in item.catalogue_rows
            if locator.carrier == carrier
        }
        if row_locators:
            record["rr:absence"] = {
                "kind": "withheld",
                "reason": next(
                    iter(
                        {
                            item.reason
                            for item in provenance.withheld_facts
                            if any(locator.carrier == carrier for locator in item.catalogue_rows)
                        }
                    )
                ),
                "rowCount": len(row_locators),
            }
        elif any(fact.startswith(f"{carrier}.") for fact in withheld):
            record["rr:absence"] = {
                "kind": "withheld",
                "reason": next(iter({reason for fact, reason in withheld.items() if fact.startswith(f"{carrier}.")})),
                "fields": [fact.partition(".")[2] for fact in withheld if fact.startswith(f"{carrier}.")],
            }
        record_sets.append(record)
    source_descriptions = [_source_description(source) for source in provenance.source_records]
    descriptor: dict[str, object] = {
        "@context": _context(),
        "@type": "sc:Dataset",
        "name": f"rivretrieve-{provenance.provider_id}-catalogue",
        "description": f"Packaged provider, product, station and station-product catalogue for {provenance.provider_id}.",
        "conformsTo": "http://mlcommons.org/croissant/1.0",
        "creator": [
            _organization(issuer) for issuer in dict.fromkeys(source.issuer for source in provenance.source_records)
        ],
        **verified_source_terms(provenance.source_records),
        "distribution": distributions,
        "recordSet": record_sets,
        "subjectOf": [*source_descriptions, *lineage.values()],
    }
    if provider["catalogue_version"] is not None:
        descriptor.update(version=provider["catalogue_version"], datePublished=provider["catalogue_version"])
    native = provenance.native_table
    if native is not None:
        if native.byte_size is None:
            raise FatalContractError("Native table byte size must be established before describing it")
        descriptor["isBasedOn"] = {
            "@id": "native-table",
            "@type": "sc:MediaObject",
            "name": "Committed native catalogue build input",
            "contentUrl": f"https://github.com/RivRetrieve/RivRetrieve/blob/{native.revision}/{native.repository_path}",
            "sha256": native.sha256,
            "contentSize": f"{native.byte_size} B",
            "creator": _organization("RivRetrieve"),
            "description": "RivRetrieve materialization of the separately attributed source inputs.",
        }
    return descriptor


def write_catalogue_descriptor(
    destination: Path,
    provenance: AcquisitionProvenance,
    origins: Sequence[OriginDeclarations],
    files: Mapping[str, bytes],
) -> None:
    descriptor = build_catalogue_descriptor(provenance, origins, files)
    destination.write_text(json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
