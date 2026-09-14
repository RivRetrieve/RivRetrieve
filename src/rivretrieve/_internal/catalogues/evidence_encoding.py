"""evidence encoding : CatalogueEvidence ↔ EvidenceHeader × EvidenceTableBytes (pure).

The explicit reconstruction function is for build/test equivalence only. Runtime
reading constructs normalized relations and never calls the v2 model.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from hashlib import sha256

import polars as pl

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogues.evidence import (
    EVIDENCE_FILENAMES,
    EVIDENCE_SCHEMAS,
    CatalogueEvidence,
    EvidenceHeader,
    encode_evidence_tables,
    evidence_file_identities,
)


def parse_catalogue_evidence(header: EvidenceHeader, table_bytes: Mapping[str, bytes]) -> CatalogueEvidence:
    """parse evidence : EvidenceHeader × EvidenceTableBytes → CatalogueEvidence (pure)."""
    # Reparse small declarations so unchecked model_copy updates cannot grant file authority.
    header = EvidenceHeader.model_validate(header.model_dump(mode="python"))
    if set(table_bytes) != set(EVIDENCE_FILENAMES.values()):
        raise ValueError("exactly five fixed evidence file basenames required")
    frames = {}
    for name, filename in EVIDENCE_FILENAMES.items():
        content = table_bytes[filename]
        identity = header.files[filename]
        if len(content) != identity.byte_count or sha256(content).hexdigest() != identity.sha256:
            raise ValueError(f"{filename} digest or byte count mismatch")
        try:
            frames[name] = pl.read_parquet(io.BytesIO(content))
        except pl.exceptions.PolarsError as error:
            raise ValueError(f"invalid evidence Parquet {filename}: {error}") from error
    return CatalogueEvidence(header=header, **frames)


def encode_catalogue_evidence(evidence: CatalogueEvidence) -> dict[str, bytes]:
    """encode evidence : CatalogueEvidence → PublicEvidenceFileBytes (pure)."""
    frames = {name: getattr(evidence, name) for name in EVIDENCE_SCHEMAS}
    files = encode_evidence_tables(frames)
    header = EvidenceHeader.model_validate(
        {**evidence.header.model_dump(mode="python"), "files": evidence_file_identities(frames, files)}
    )
    # Validate the actual value before publishing, including caller-mutated frames.
    CatalogueEvidence(header=header, **frames)
    return {"provenance.json": (header.model_dump_json(indent=2) + "\n").encode(), **files}


def reconstruct_provenance(evidence: CatalogueEvidence) -> AcquisitionProvenance:
    """reconstruct provenance : CatalogueEvidence → AcquisitionProvenance (BUILD/TEST ONLY)."""
    h = evidence.header
    names = evidence.facts["name"].to_list()
    source_ids = [s.source_id for s in h.source_records]
    sources = [s.model_dump(mode="python") | {"acquisitions": []} for s in h.source_records]
    acquisitions = list(evidence.acquisitions.iter_rows(named=True))
    for a in acquisitions:
        sources[a["source_ordinal"]]["acquisitions"].append(
            {
                "acquisition_id": a["acquisition_id"],
                "method": a["method"],
                "instant_type": a["instant_type"],
                "description": h.descriptions[a["description_id"]],
                "requested_from": a["requested_from"],
                "retrieved_at_start": a["retrieved_at_start"],
                "retrieved_at_end": a["retrieved_at_end"],
                "recording_ids": a["recording_ids"],
                "material": None
                if a["material_filename"] is None
                else {
                    "filename": a["material_filename"],
                    "sha256": a["material_sha256"],
                    "byte_count": a["material_byte_count"],
                },
            }
        )
    outputs: list[list[str]] = [[] for _ in range(evidence.bindings.height)]
    inputs: list[list[dict]] = [[] for _ in outputs]
    for b, _, fact in evidence.binding_facts.iter_rows():
        outputs[b].append(names[fact])
    for b, _, source, fact in evidence.external_inputs.iter_rows():
        inputs[b].append({"source_id": source_ids[source] if source is not None else None, "fact": names[fact]})
    bindings = []
    for b, group, source, acquisition, transformation in evidence.bindings.iter_rows():
        bindings.append(
            {
                "fact_group": group,
                "facts": outputs[b],
                "source_id": source_ids[source] if source is not None else None,
                "acquisition_id": acquisitions[acquisition]["acquisition_id"] if acquisition is not None else None,
                "transformation": None
                if transformation is None
                else {**h.transformations[transformation].model_dump(mode="python"), "external_inputs": inputs[b]},
            }
        )
    return AcquisitionProvenance.model_validate(
        {
            "schema_version": 2,
            "provider_id": h.provider_id,
            "native_table": h.native_table,
            "source_records": sources,
            "fact_universe": names,
            "fact_bindings": bindings,
            "withheld_facts": h.withheld_facts,
        }
    )
