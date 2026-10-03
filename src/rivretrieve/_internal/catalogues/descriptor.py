"""catalogue descriptor : CatalogueEvidence × OriginDeclarations × CatalogueFiles → JSONLD (pure); publication : JSONLD × DescriptorPath → File."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal, TypedDict

import polars as pl

from rivretrieve._internal.acquisition_provenance import verified_source_terms
from rivretrieve._internal.catalogue_origins import (
    Authored,
    Documented,
    Field,
    NotPublished,
    OriginDeclarations,
    Withheld,
)
from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
from rivretrieve._internal.catalogues.evidence import EVIDENCE_FILENAMES, EVIDENCE_SCHEMAS, CatalogueEvidence
from rivretrieve._internal.catalogues.schemas import PROVIDER_INFO_CATALOG_SCHEMA, CatalogueDtype
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.station_metadata import SOURCE_METADATA_SCHEMA, source_metadata_frame

ABSENCE_NAMESPACE = "https://github.com/RivRetrieve/RivRetrieve/blob/main/docs/catalogue-absence.md#"


PROFILE_URI = "https://github.com/RivRetrieve/RivRetrieve/blob/main/docs/catalogue-evidence.md#profile-3"


def _fact_locator(fact: str) -> dict[str, object]:
    return {
        "@type": "sc:CreativeWork",
        "identifier": fact,
        "url": "provenance_facts.parquet",
        "conformsTo": PROFILE_URI,
        "description": "Select the exact name key in provenance_facts.",
    }


def _evidence_record_sets() -> list[dict[str, object]]:
    keys = {
        "facts": ("fact_id",),
        "acquisitions": ("acquisition_key",),
        "bindings": ("binding_id",),
        "binding_facts": ("binding_id", "position"),
        "external_inputs": ("binding_id", "position"),
    }
    targets = {"fact_id": "facts", "binding_id": "bindings", "acquisition_key": "acquisitions"}
    records: list[dict[str, object]] = []
    for relation, schema in EVIDENCE_SCHEMAS.items():
        identity = f"provenance_{relation}"
        fields: list[dict[str, object]] = []
        for column, dtype in schema.items():
            array = isinstance(dtype, pl.List)
            field: dict[str, object] = {
                "@id": f"{identity}/{column}",
                "@type": "cr:Field",
                "dataType": _data_type(
                    pl.Schema({"item": dtype.inner})["item"] if isinstance(dtype, pl.List) else dtype
                ),
                "source": {"fileObject": _reference(EVIDENCE_FILENAMES[relation]), "extract": {"column": column}},
            }
            if array:
                field.update(isArray=True, arrayShape="-1")
            if column in targets and targets[column] != relation:
                # Croissant's standard physical-column reference avoids the reference
                # loader's cross-RecordSet generator join; the exact FK is unchanged.
                field["references"] = {
                    "fileObject": _reference(EVIDENCE_FILENAMES[targets[column]]),
                    "extract": {"column": column},
                }
            fields.append(field)
        records.append(
            {
                "@id": identity,
                "@type": "cr:RecordSet",
                "field": fields,
                "key": [_reference(f"{identity}/{column}") for column in keys[relation]],
            }
        )
    return records


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
            for name in (
                "recordSet",
                "field",
                "source",
                "fileObject",
                "extract",
                "column",
                "jsonPath",
                "references",
                "key",
                "isArray",
                "arrayShape",
            )
        },
    }


def _organization(name: str) -> dict[str, str]:
    return {"@type": "sc:Organization", "name": name}


def _reference(identity: str) -> dict[str, object]:
    return {"@id": identity}


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


def _data_type(dtype: CatalogueDtype) -> str:
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
    evidence: CatalogueEvidence,
    origins: Sequence[OriginDeclarations],
    files: Mapping[str, bytes],
    *,
    station_metadata_notice: str | None = None,
) -> dict[str, object]:
    """Describe exact packaged bytes and their recorded historical inputs, without IO.

    An optional notice describes only the station-metadata record set. It leaves
    the source's top-level licence and citation quotations unchanged.
    """
    if station_metadata_notice is not None and (
        not isinstance(station_metadata_notice, str)
        or not station_metadata_notice.strip()
        or evidence.header.build_inputs is None
    ):
        raise FatalContractError("A station metadata notice requires nonblank text and a metadata product")
    expected_files = (*REQUIRED_ARTIFACT_FILES, "provenance.json", *EVIDENCE_FILENAMES.values())
    if "format.json" in files or "source_series.json" in files:
        expected_files += ("format.json", "source_series.json", "series_claims.parquet")
    if evidence.header.build_inputs is not None:
        expected_files += ("station_metadata.parquet",)
    if "monitoring_locations.json" in files:
        expected_files += ("monitoring_locations.json",)
    if set(files) != set(expected_files):
        raise FatalContractError(
            "Descriptor requires exactly the public catalogue, source-description and evidence files"
        )
    if evidence.header.native_table is not None and not origins:
        raise FatalContractError("Certified catalogue descriptor requires station origins")
    if evidence.header.native_table is not None and evidence.header.native_table.byte_size is None:
        raise FatalContractError("Native table byte size must be established before describing it")
    if json.loads(files["provenance.json"]) != evidence.header.model_dump(mode="json"):
        raise FatalContractError("Descriptor evidence header disagrees with supplied provenance.json")
    for filename, identity in evidence.header.files.items():
        content = files[filename]
        if sha256(content).hexdigest() != identity.sha256 or len(content) != identity.byte_count:
            raise FatalContractError(f"Descriptor evidence file identity disagrees: {filename}")
    provider = json.loads(files["provider.json"])
    if provider["provider_id"] != evidence.header.provider_id:
        raise FatalContractError("Descriptor provider identity disagrees with acquisition provenance")
    tables = {
        "provider": pl.DataFrame([provider], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
        **{
            name: pl.read_parquet(BytesIO(files[f"{name}.parquet"]))
            for name in ("products", "stations", "station_products")
        },
    }
    withheld = {fact: item.reason for item in evidence.header.withheld_facts for fact in item.facts}
    canonical_names = [
        f"{carrier}.{column}"
        for carrier, table in zip(("provider", "product", "station", "station_product"), tables.values(), strict=True)
        for column in table.columns
    ]
    canonical_facts = evidence.facts.filter(pl.col("name").is_in(canonical_names))
    bindings = {
        row["name"]: row
        for row in canonical_facts.join(evidence.binding_facts, on="fact_id")
        .join(evidence.bindings, on="binding_id")
        .iter_rows(named=True)
    }
    distributions = [
        {
            "@id": name,
            "@type": "cr:FileObject",
            "contentUrl": name,
            "encodingFormat": "application/json" if name.endswith(".json") else "application/x-parquet",
            "sha256": sha256(contents).hexdigest(),
            "contentSize": f"{len(contents)} B",
        }
        for name in expected_files
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
            if fact not in bindings and fact not in withheld:
                raise FatalContractError(f"Canonical column has no lineage or withheld fact: {fact}")
            field["subjectOf"] = _fact_locator(fact)
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
                    references = list(dict.fromkeys(str(origin.evidence) for origin in not_published))
                    field["rr:absence"] = NotPublishedAbsence(
                        kind="not_published", evidence=references[0] if len(references) == 1 else references
                    )
                if any(isinstance(origin, Withheld) for origin in declared):
                    if not all(isinstance(origin, Withheld) for origin in declared):
                        raise FatalContractError(f"Station column mixes established and withheld origins: {column}")
                    if fact in withheld:
                        fields.append(field)
                        continue
                    binding = bindings[fact]
                    if binding["transformation_id"] is None:
                        raise FatalContractError(f"Withheld origin has no recorded transformation: {fact}")
                    input_names = evidence.external_inputs.filter(pl.col("binding_id") == binding["binding_id"]).join(
                        evidence.facts.select("fact_id", "name"), on="fact_id"
                    )["name"]
                    reasons = {withheld[name] for name in input_names if name in withheld}
                    if len(reasons) != 1:
                        raise FatalContractError(f"Withheld origin has no unique recorded reason: {fact}")
                    field["rr:absence"] = WithheldAbsence(kind="withheld", reason=next(iter(reasons)))
            fields.append(field)
        record: dict[str, object] = {"@id": table_name, "@type": "cr:RecordSet", "field": fields}
        record["subjectOf"] = {
            "@type": "sc:CreativeWork",
            "identifier": carrier,
            "name": "Exact catalogue fact locator relation",
            "url": "provenance_facts.parquet",
            "conformsTo": PROFILE_URI,
        }
        row_locators = {
            locator
            for item in evidence.header.withheld_facts
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
                            for item in evidence.header.withheld_facts
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
    if evidence.header.build_inputs is not None:
        metadata = pl.read_parquet(BytesIO(files["station_metadata.parquet"]))
        keys = tables["stations"].select("provider_id", "station_id")
        scoped = source_metadata_frame(keys, metadata)
        if scoped.height != metadata.height:
            raise FatalContractError("Station metadata contains identities outside the canonical catalogue")
        bound_names = set(evidence.facts.join(evidence.binding_facts, on="fact_id")["name"].to_list())
        if not set(metadata["support_fact"].drop_nulls().to_list()) <= bound_names:
            raise FatalContractError("Station metadata support facts must resolve bound catalogue facts")
        fields = []
        for column, dtype in SOURCE_METADATA_SCHEMA.items():
            field = {
                "@id": f"station_metadata/{column}",
                "@type": "cr:Field",
                "dataType": _data_type(dtype),
                "source": {"fileObject": _reference("station_metadata.parquet"), "extract": {"column": column}},
            }
            if column == "support_fact":
                field["references"] = {
                    "fileObject": _reference("provenance_facts.parquet"),
                    "extract": {"column": "name"},
                }
            fields.append(field)
        metadata_record: dict[str, object] = {"@id": "station_metadata", "@type": "cr:RecordSet", "field": fields}
        if station_metadata_notice is not None:
            metadata_record["description"] = station_metadata_notice
        record_sets.append(metadata_record)
    record_sets.extend(_evidence_record_sets())
    descriptor: dict[str, object] = {
        "@context": _context(),
        "@type": "sc:Dataset",
        "name": f"rivretrieve-{evidence.header.provider_id}-catalogue",
        "description": f"Packaged provider, product, station and station-product catalogue for {evidence.header.provider_id}.",
        "conformsTo": "http://mlcommons.org/croissant/1.0",
        "schemaVersion": PROFILE_URI,
        "creator": [
            _organization(issuer)
            for issuer in dict.fromkeys(source.issuer for source in evidence.header.source_records)
        ],
        **verified_source_terms(evidence.header.source_records),
        "distribution": distributions,
        "recordSet": record_sets,
        "subjectOf": {
            "@type": "sc:CreativeWork",
            "url": "provenance.json",
            "name": "Issuing sources, exact statements and evidence declarations",
            "conformsTo": PROFILE_URI,
        },
    }
    if evidence.header.build_inputs is not None:
        descriptor["subjectOf"] = {
            "@type": "sc:CreativeWork",
            "url": "provenance.json",
            "name": "Source acquisitions, adopted archived inputs and executable and authored code references",
            "description": (
                "build_inputs records exact adopted archive members, their supported fact names, "
                "and build and declaration revisions. transformations records executable and "
                "authored declaration references. Historical acquisition identities remain separate."
            ),
            "conformsTo": PROFILE_URI,
        }
    if provider["catalogue_version"] is not None:
        descriptor.update(version=provider["catalogue_version"], datePublished=provider["catalogue_version"])
    native = evidence.header.native_table
    if native is not None:
        if native.byte_size is None:
            raise FatalContractError("Native table byte size must be established before describing it")
        descriptor["isBasedOn"] = {
            "@id": "native-table",
            "@type": "sc:MediaObject",
            "name": (
                "Historical committed native catalogue build input"
                if evidence.header.build_inputs is not None
                else "Committed native catalogue build input"
            ),
            "contentUrl": f"https://github.com/RivRetrieve/RivRetrieve/blob/{native.revision}/{native.repository_path}",
            "sha256": native.sha256,
            "contentSize": f"{native.byte_size} B",
            "creator": _organization("RivRetrieve"),
            "description": "RivRetrieve materialization of the separately attributed source inputs.",
        }
    return descriptor


def write_catalogue_descriptor(
    destination: Path,
    evidence: CatalogueEvidence,
    origins: Sequence[OriginDeclarations],
    files: Mapping[str, bytes],
    *,
    station_metadata_notice: str | None = None,
) -> None:
    descriptor = build_catalogue_descriptor(evidence, origins, files, station_metadata_notice=station_metadata_notice)
    destination.write_text(json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
