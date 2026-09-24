"""Rebuild HydroPortail from retained source bytes and immutable history ledger."""

import hashlib
import json
import lzma
from datetime import datetime
from pathlib import Path

from rivretrieve._internal.acquisition_provenance import (
    EvidenceReference,
    NativeTableIdentity,
    RecordingReference,
    verify_provenance_recordings,
)
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import decode_availability
from rivretrieve._internal.providers.fr_hydroportail.generate_catalogue import (
    build_catalogue,
    read_inventory,
    write_catalogue,
)
from rivretrieve._internal.providers.fr_hydroportail.origins import STATION_CATALOGUE_ORIGINS

root = Path(__file__).resolve().parents[4]
evidence = root / "maintenance/catalogue/fr_hydroportail/evidence"
native, receipt = read_inventory(evidence / "national-tests.body", evidence / "national-tests.receipt.json")
history = decode_availability(
    lzma.decompress((root / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz").read_bytes())
)
documents = []
for name in ("about", "legal", "chunk-8529.fdb00780.js"):
    metadata = json.loads((evidence / f"{name}.receipt.json").read_bytes())
    documents.append(
        EvidenceReference(
            evidence_id=name,
            description={
                "about": "HydroPortail publication and PHyC platform",
                "legal": "HydroPortail public access and operator; reuse licence not established",
                "chunk-8529.fdb00780.js": "Module 71324 emits station x/y directly as GeoJSON longitude/latitude",
            }[name],
            recording=RecordingReference(
                recording_id=name,
                repository_path=f"maintenance/catalogue/fr_hydroportail/evidence/{name}.body",
                source_url=metadata["url"],
                retrieved_at=datetime.fromisoformat(metadata["retrieved_at"]),
                media_type=metadata["content_type"],
                sha256=metadata["sha256"],
            ),
        )
    )
native_path = "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue/native.parquet"
native_bytes = (root / native_path).read_bytes()
native_identity = NativeTableIdentity(
    repository_path=native_path,
    revision="eb2b4fcb3a38875329225b7dbe5f949216c01599",
    sha256=hashlib.sha256(native_bytes).hexdigest(),
    byte_size=len(native_bytes),
)
catalogue = build_catalogue(native, STATION_CATALOGUE_ORIGINS, history, receipt, tuple(documents), native_identity)
verify_provenance_recordings(catalogue.acquisition_provenance, root)
write_catalogue(catalogue, root / "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue")
