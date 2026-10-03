"""Rebuild the Hub’Eau catalogue from retained source responses, without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode  # noqa: TID251 -- structural request encoding only

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    CatalogueBuildInputs,
    EvidenceReference,
    NativeTableIdentity,
    RecordingReference,
    SemanticDigest,
    verify_provenance_recordings,
)
from rivretrieve._internal.catalogues.native import RetrievedAt, write_native_table
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import (
    NativeInventoryCapture,
    build_catalogue,
    decode_availability,
    native_table_content_digest,
    refresh_native_table,
    write_catalogue,
)
from rivretrieve._internal.providers.fr_hubeau.origins import FRANCE_ORIGIN_DECLARATIONS


def rebuild(
    evidence_root: Path,
    availability_ledger: Path,
    output: Path,
    capture_output: Path,
    revision: str,
    *,
    build_inputs: CatalogueBuildInputs,
) -> None:
    for destination in (output, capture_output):
        if any((parent / ".git").exists() for parent in (destination, *destination.parents)):
            raise ValueError("Outputs must be outside source checkouts")
        if destination.is_relative_to(evidence_root):
            raise ValueError("Outputs must be separate from retained evidence")
    inventory = evidence_root / "maintenance/catalogue/fr_hubeau/inventory"
    payloads, instants, acquisitions, evidence = [], [], [], []
    for endpoint in ("hydrometry", "temperature"):
        stem = f"{endpoint}-stations-2026-09-21"
        path = inventory / f"{stem}.json.xz"
        stored = path.read_bytes()
        raw = lzma.decompress(stored)
        receipt = json.loads((inventory / f"{stem}.receipt.json").read_bytes())
        if hashlib.sha256(raw).hexdigest() != receipt["sha256"] or len(raw) != receipt["bytes"]:
            raise ValueError(f"{endpoint} retained HTTP body identity mismatch")
        if receipt["status"] != 200 or receipt["content_type"] != "application/json":
            raise ValueError(f"{endpoint} station request did not return JSON success")
        payload = json.loads(raw)
        payloads.append(payload)
        instant = datetime.fromisoformat(receipt["retrieved_at"])
        instants.append(RetrievedAt(instant))
        identifier = f"{endpoint}_catalogue_capture_2026_09_21"
        url = receipt["url"] + "?" + urlencode(receipt["params"])
        recording = RecordingReference(
            recording_id=identifier,
            repository_path=path.relative_to(evidence_root).as_posix(),
            source_url=url,
            retrieved_at=instant,
            media_type="application/x-xz",
            sha256=hashlib.sha256(stored).hexdigest(),
        )
        evidence.append(
            EvidenceReference(
                evidence_id=identifier,
                recording=recording,
                description="Lossless XZ storage of publisher application/json response; HTTP body hash and size in retained receipt.",
            )
        )
        acquisitions.append(
            AcquisitionRecord(
                acquisition_id=identifier,
                method="http_request",
                instant_type="retrieval",
                requested_from=(url,),
                retrieved_at_start=instant,
                recording_ids=(identifier,),
                description=f"Complete {endpoint} station response: count={payload['count']}, next=null. "
                f"Publisher application/json HTTP body SHA256={receipt['sha256']}, bytes={receipt['bytes']}; "
                "retained recording uses lossless XZ compression. Identity/location only, not observation history.",
            )
        )
    outcome = refresh_native_table(*payloads, hydro_retrieved_at=instants[0], temperature_retrieved_at=instants[1])
    if outcome.issues:
        raise ValueError(outcome.issues)
    native = outcome.value
    output.mkdir(parents=True, exist_ok=True)
    capture_output.parent.mkdir(parents=True, exist_ok=True)
    native_path = output / "native.parquet"
    write_native_table(native, native_path)
    raw_native = native_path.read_bytes()
    capture = NativeInventoryCapture(
        native_table=NativeTableIdentity(
            repository_path="src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
            revision=revision,
            sha256=hashlib.sha256(raw_native).hexdigest(),
            byte_size=len(raw_native),
            semantic_digest=SemanticDigest(
                name="fr_hubeau.native_table_content_sha256", sha256=native_table_content_digest(native)
            ),
        ),
        hydrometry=acquisitions[0],
        temperature=acquisitions[1],
        evidence=tuple(evidence),
    )
    capture_output.write_text(capture.model_dump_json(indent=2) + "\n")
    availability = decode_availability(lzma.decompress(availability_ledger.read_bytes()))
    catalogue = build_catalogue(native, FRANCE_ORIGIN_DECLARATIONS, availability, native_capture=capture)
    verify_provenance_recordings(catalogue.acquisition_provenance, evidence_root)
    write_catalogue(catalogue, output, build_inputs=build_inputs, native_table=native)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument(
        "--availability-ledger",
        type=Path,
        default=Path(__file__).resolve().parent / "governing_evidence.json.xz",
    )
    parser.add_argument("--build-inputs", type=Path, required=True, help="Reviewed adopted CatalogueBuildInputs JSON.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--capture-output", type=Path, required=True)
    parser.add_argument("--revision", required=True, help="Repository revision containing the retained native input")
    args = parser.parse_args()
    rebuild(
        args.evidence_root.resolve(),
        args.availability_ledger.resolve(),
        args.out.resolve(),
        args.capture_output.resolve(),
        args.revision,
        build_inputs=CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes()),
    )
