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
    _ensure_validated_header,
    encode_evidence_tables,
    evidence_file_identities,
)


def parse_catalogue_evidence(header: EvidenceHeader, table_bytes: Mapping[str, bytes]) -> CatalogueEvidence:
    """parse evidence : EvidenceHeader × EvidenceTableBytes → CatalogueEvidence (pure)."""
    # Reparse small declarations so unchecked model_copy updates cannot grant file authority.
    header = _ensure_validated_header(header)
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
        {**evidence.header.model_dump(mode="json"), "files": evidence_file_identities(frames, files)}
    )
    # Validate the actual value before publishing, including caller-mutated frames.
    CatalogueEvidence(header=header, **frames)
    return {"provenance.json": (header.model_dump_json() + "\n").encode(), **files}


def reconstruct_provenance(evidence: CatalogueEvidence) -> AcquisitionProvenance:
    """reconstruct provenance : CatalogueEvidence → AcquisitionProvenance (BUILD/TEST ONLY)."""
    from datetime import datetime

    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        ExternalFactReference,
        FactBinding,
        MaterialIdentity,
        SourceRecord,
        Transformation,
    )

    h = evidence.header
    names = evidence.facts["name"].to_list()
    source_ids = [s.source_id for s in h.source_records]
    source_acqs: list[list[AcquisitionRecord]] = [[] for _ in h.source_records]

    acq_cols = evidence.acquisitions.to_dict(as_series=False)
    acq_ids = acq_cols["acquisition_id"]
    for (
        src_ord,
        acq_id,
        method,
        instant_type,
        desc_id,
        req_from,
        start_str,
        end_str,
        rec_ids,
        mat_fn,
        mat_sha,
        mat_bytes,
    ) in zip(
        acq_cols["source_ordinal"],
        acq_ids,
        acq_cols["method"],
        acq_cols["instant_type"],
        acq_cols["description_id"],
        acq_cols["requested_from"],
        acq_cols["retrieved_at_start"],
        acq_cols["retrieved_at_end"],
        acq_cols["recording_ids"],
        acq_cols["material_filename"],
        acq_cols["material_sha256"],
        acq_cols["material_byte_count"],
        strict=True,
    ):
        material = (
            None
            if mat_fn is None
            else MaterialIdentity.model_construct(filename=mat_fn, byte_count=mat_bytes, sha256=mat_sha)
        )
        source_acqs[src_ord].append(
            AcquisitionRecord.model_construct(
                acquisition_id=acq_id,
                method=method,
                instant_type=instant_type,
                description=h.descriptions[desc_id],
                requested_from=tuple(req_from),
                retrieved_at_start=datetime.fromisoformat(start_str) if start_str is not None else None,
                retrieved_at_end=datetime.fromisoformat(end_str) if end_str is not None else None,
                recording_ids=tuple(rec_ids),
                material=material,
            )
        )

    sources = tuple(
        SourceRecord.model_construct(
            source_id=s.source_id,
            issuer=s.issuer,
            operator=s.operator,
            acquisitions=tuple(source_acqs[idx]),
            evidence=s.evidence,
            statements=s.statements,
        )
        for idx, s in enumerate(h.source_records)
    )

    num_bindings = evidence.bindings.height
    outputs: list[list[str]] = [[] for _ in range(num_bindings)]
    inputs: list[list[ExternalFactReference]] = [[] for _ in range(num_bindings)]

    bf_cols = evidence.binding_facts.to_dict(as_series=False)
    for b, fact in zip(bf_cols["binding_id"], bf_cols["fact_id"], strict=True):
        outputs[b].append(names[fact])

    ei_cols = evidence.external_inputs.to_dict(as_series=False)
    ext_ref_cache: dict[tuple[int | None, int], ExternalFactReference] = {}
    for b, source, fact in zip(ei_cols["binding_id"], ei_cols["source_ordinal"], ei_cols["fact_id"], strict=True):
        ref_key = (source, fact)
        ref = ext_ref_cache.get(ref_key)
        if ref is None:
            ref = ExternalFactReference.model_construct(
                source_id=source_ids[source] if source is not None else None,
                fact=names[fact],
            )
            ext_ref_cache[ref_key] = ref
        inputs[b].append(ref)

    bind_cols = evidence.bindings.to_dict(as_series=False)
    transformations = h.transformations
    transform_cache: dict[tuple[int, tuple[ExternalFactReference, ...]], Transformation] = {}
    bindings: list[FactBinding] = []
    for b, group, source, acquisition, transformation in zip(
        bind_cols["binding_id"],
        bind_cols["fact_group"],
        bind_cols["source_ordinal"],
        bind_cols["acquisition_key"],
        bind_cols["transformation_id"],
        strict=True,
    ):
        if transformation is None:
            transform_obj = None
        else:
            inputs_tuple = tuple(inputs[b])
            cache_key = (transformation, inputs_tuple)
            transform_obj = transform_cache.get(cache_key)
            if transform_obj is None:
                td = transformations[transformation]
                transform_obj = Transformation.model_construct(
                    name=td.name,
                    kind=td.kind,
                    marker_value=td.marker_value,
                    external_inputs=inputs_tuple,
                    executable=td.executable,
                    declaration=td.declaration,
                )
                transform_cache[cache_key] = transform_obj
        bindings.append(
            FactBinding.model_construct(
                fact_group=group,
                facts=tuple(outputs[b]),
                source_id=source_ids[source] if source is not None else None,
                acquisition_id=acq_ids[acquisition] if acquisition is not None else None,
                transformation=transform_obj,
            )
        )

    return AcquisitionProvenance(
        schema_version=2,
        provider_id=h.provider_id,
        native_table=h.native_table,
        build_inputs=h.build_inputs,
        source_records=sources,
        fact_universe=tuple(names),
        fact_bindings=tuple(bindings),
        withheld_facts=h.withheld_facts,
    )
