"""resolve evidence : CatalogueEvidence × FactSelection × CanonicalPair? → JSONLD (pure)."""

from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, field_validator

from rivretrieve._internal.catalogues.descriptor import _context, _organization, _reference
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence, IssuingSource
from rivretrieve._internal.issues import FatalContractError


class FactSelection(BaseModel):
    """Exact declared fact names, in caller order."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    names: tuple[str, ...]

    @field_validator("names")
    @classmethod
    def _nonempty_unique(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        if not names or any(not name for name in names) or len(set(names)) != len(names):
            raise ValueError("Select nonempty unique exact fact names")
        return names


class CanonicalPair(BaseModel):
    """The caller-supplied canonical row, never an inferred availability verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    provider_id: str
    station_id: str
    product_id: str
    availability: Literal["available", "unknown", "unavailable"]
    availability_reason: str | None


def _source_nodes(source: IssuingSource, ordinal: int) -> list[dict[str, object]]:
    identity = f"issuer/{ordinal}"
    node: dict[str, object] = {
        "@id": identity,
        "@type": "sc:CreativeWork",
        "identifier": source.source_id,
        "creator": _organization(source.issuer),
    }
    if source.operator is not None:
        node["provider"] = _organization(source.operator)
    nodes = [node]
    recordings: dict[str, str] = {}
    for index, evidence in enumerate(source.evidence):
        recording = evidence.recording
        recording_identity = f"recording/{ordinal}/{index}"
        recordings[recording.recording_id] = recording_identity
        nodes.append(
            {
                "@id": recording_identity,
                "@type": "sc:MediaObject",
                "identifier": recording.recording_id,
                "name": evidence.evidence_id,
                "description": evidence.description,
                "url": recording.source_url,
                "contentUrl": recording.repository_path,
                "sha256": recording.sha256,
                "encodingFormat": recording.media_type,
                "subjectOf": {
                    "@type": "sc:Event",
                    "name": "retrieval",
                    "startDate": recording.retrieved_at.isoformat(),
                },
                "creator": _organization(source.issuer),
            }
        )
    node["hasPart"] = [_reference(f"recording/{ordinal}/{index}") for index in range(len(source.evidence))]
    node["subjectOf"] = [_reference(f"statement/{ordinal}/{index}") for index in range(len(source.statements))]
    for index, statement in enumerate(source.statements):
        statement_node: dict[str, object] = {
            "@id": f"statement/{ordinal}/{index}",
            "@type": "sc:CreativeWork",
            "name": statement.kind,
            "description": statement.verification_status,
            "about": _reference(identity),
        }
        if statement.verification_status == "verified_public_recording":
            assert statement.recording_id is not None
            statement_node.update(
                text=statement.exact_text,
                identifier=statement.fact,
                isBasedOn=_reference(recordings[statement.recording_id]),
            )
        elif statement.private_verification is not None:
            # Redacted verification facts, not private words or locations.
            statement_node["additionalProperty"] = [
                {"@type": "sc:PropertyValue", "name": name, "value": value}
                for name, value in statement.private_verification.model_dump(mode="json").items()
            ]
        nodes.append(statement_node)
    return nodes


def _acquisition_node(evidence: CatalogueEvidence, row: dict) -> dict[str, object]:
    ordinal = row["source_ordinal"]
    source = evidence.header.source_records[ordinal]
    description = evidence.header.descriptions[row["description_id"]]
    node: dict[str, object] = {
        "@id": f"acquisition/{row['acquisition_key']}",
        "@type": "sc:CreativeWork" if row["material_filename"] is None else "sc:MediaObject",
        "identifier": row["acquisition_id"],
        "name": row["method"],
        "description": description,
        "creator": _organization(source.issuer),
        "about": _reference(f"issuer/{ordinal}"),
    }
    node["additionalProperty"] = {"@type": "sc:PropertyValue", "name": "method", "value": row["method"]}
    if source.operator is not None:
        node["provider"] = _organization(source.operator)
    locations = [url for url in row["requested_from"] if url.startswith(("http://", "https://"))]
    if locations:
        node["url"] = locations
    if row["material_filename"] is not None:
        node.update(
            name=row["material_filename"], sha256=row["material_sha256"], contentSize=f"{row['material_byte_count']} B"
        )
    event: dict[str, object] = {"@type": "sc:Event", "name": row["instant_type"], "description": description}
    if row["retrieved_at_start"] is not None:
        event["startDate"] = row["retrieved_at_start"]
    if row["retrieved_at_end"] is not None:
        event["endDate"] = row["retrieved_at_end"]
    node["subjectOf"] = event
    recording_ids = {item.recording.recording_id: index for index, item in enumerate(source.evidence)}
    if row["recording_ids"]:
        node["associatedMedia"] = [
            _reference(f"recording/{ordinal}/{recording_ids[name]}") for name in row["recording_ids"]
        ]
    terms: dict[str, list[dict[str, object]]] = {}
    for index, statement in enumerate(source.statements):
        if statement.verification_status == "verified_public_recording":
            predicate = statement.kind if statement.kind in {"license", "citation"} else "usageInfo"
            terms.setdefault(predicate, []).append(_reference(f"statement/{ordinal}/{index}"))
    node.update(terms)
    return node


def resolve_evidence(
    evidence: CatalogueEvidence,
    selection: FactSelection,
    canonical_pair: CanonicalPair | None = None,
) -> dict[str, object]:
    """Resolve selected facts only; all files and canonical values are supplied by the caller.

    The optional pair must match exactly one selected availability locator. Its status
    and reason are reported verbatim, not certified from an acquisition description.
    """
    selected = evidence.facts.filter(pl.col("name").is_in(selection.names))
    if selected.height != len(selection.names):
        raise FatalContractError("Evidence selection contains an undeclared exact fact name")
    if canonical_pair is not None:
        matched = selected.filter(
            (pl.col("carrier") == "station_product")
            & (pl.col("locator_role") == "availability")
            & (pl.col("station_id") == canonical_pair.station_id)
            & (pl.col("product_id") == canonical_pair.product_id)
        )
        if canonical_pair.provider_id != evidence.header.provider_id or matched.height != 1:
            raise FatalContractError("Canonical pair identity does not match the selected evidence locator")
    withheld = {fact: group for group in evidence.header.withheld_facts for fact in group.facts}
    nodes: dict[str, dict[str, object]] = {}
    sources: set[int] = set()
    pending = selected["fact_id"].to_list()
    visited: set[int] = set()
    while pending:
        fact_ids = [identity for identity in pending if identity not in visited]
        pending = []
        if not fact_ids:
            break
        visited.update(fact_ids)
        facts = evidence.facts.filter(pl.col("fact_id").is_in(fact_ids))
        memberships = evidence.binding_facts.filter(pl.col("fact_id").is_in(fact_ids))
        producers = dict(memberships.select("fact_id", "binding_id").iter_rows())
        for fact in facts.iter_rows(named=True):
            identity = f"fact/{fact['fact_id']}"
            node: dict[str, object] = {"@id": identity, "@type": "sc:CreativeWork", "identifier": fact["name"]}
            if fact["name"] in withheld:
                group = withheld[fact["name"]]
                node["rr:absence"] = {"kind": "withheld", "reason": group.reason}
                if group.source_id is not None:
                    ordinal = next(
                        i
                        for i, source in enumerate(evidence.header.source_records)
                        if source.source_id == group.source_id
                    )
                    sources.add(ordinal)
                    node["about"] = _reference(f"issuer/{ordinal}")
            else:
                node["isBasedOn"] = _reference(f"lineage/{producers[fact['fact_id']]}")
            nodes[identity] = node
        bindings = evidence.bindings.filter(pl.col("binding_id").is_in(list(producers.values())))
        for binding in bindings.iter_rows(named=True):
            identity = f"lineage/{binding['binding_id']}"
            if identity in nodes:
                continue
            node = {
                "@id": identity,
                "@type": "sc:CreativeWork",
                "identifier": binding["fact_group"],
                "creator": _organization("RivRetrieve"),
            }
            outputs = (
                evidence.binding_facts.filter(pl.col("binding_id") == binding["binding_id"])
                .sort("position")
                .join(evidence.facts.select("fact_id", "name"), on="fact_id", maintain_order="left")
            )
            node["hasPart"] = [{"@type": "sc:CreativeWork", "identifier": name} for name in outputs["name"]]
            if binding["acquisition_key"] is not None:
                row = evidence.acquisitions.filter(pl.col("acquisition_key") == binding["acquisition_key"]).row(
                    0, named=True
                )
                acquisition = _acquisition_node(evidence, row)
                nodes[str(acquisition["@id"])] = acquisition
                sources.add(row["source_ordinal"])
                node["isBasedOn"] = _reference(str(acquisition["@id"]))
                node["description"] = binding["fact_group"]
            else:
                transform = evidence.header.transformations[binding["transformation_id"]]
                node.update(description=transform.name, name=transform.kind)
                inputs = evidence.external_inputs.filter(pl.col("binding_id") == binding["binding_id"]).sort("position")
                node["isBasedOn"] = [_reference(f"fact/{value}") for value in inputs["fact_id"]]
                pending.extend(inputs["fact_id"].to_list())
                if transform.marker_value is not None:
                    node["additionalProperty"] = {
                        "@type": "sc:PropertyValue",
                        "name": "marker_value",
                        "value": transform.marker_value.value,
                    }
            nodes[identity] = node
    for ordinal in sorted(sources):
        source_nodes = _source_nodes(evidence.header.source_records[ordinal], ordinal)
        corroborations = evidence.acquisitions.filter(
            (pl.col("source_ordinal") == ordinal) & (pl.col("method") == "corroborating_receipt")
        )
        if corroborations.height:
            source_nodes[0]["citation"] = {
                "@type": "sc:CreativeWork",
                "name": "Separate corroborating material; not the historical acquisition",
                "citation": [_reference(f"acquisition/{key}") for key in corroborations["acquisition_key"]],
            }
            source_nodes.extend(_acquisition_node(evidence, row) for row in corroborations.iter_rows(named=True))
        nodes.update((str(node["@id"]), node) for node in source_nodes)
    by_name = dict(selected.select("name", "fact_id").iter_rows())
    result: dict[str, object] = {
        "@context": _context(),
        "@type": "sc:CreativeWork",
        "identifier": evidence.header.provider_id,
        "about": [_reference(f"fact/{by_name[name]}") for name in selection.names],
        "@graph": list(nodes.values()),
    }
    if canonical_pair is not None:
        result["additionalProperty"] = [
            {"@type": "sc:PropertyValue", "name": name, "value": value}
            for name, value in canonical_pair.model_dump().items()
        ]
    return result
