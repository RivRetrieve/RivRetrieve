"""ThaiWater availability evidence : ReviewedLedgerBytes → GraphAvailabilityEvidence (pure).

The pinned ledger was accepted after private full-body verification. Parsing it
checks metadata identity, not source bodies. Updating the pin requires renewed
source-body acceptance. No controlled review corpus is a public recording.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import InitVar, dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Literal, cast

from rivretrieve._internal.acquisition_provenance import AcquisitionRecord, MaterialIdentity
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId

# Accepted governing station/product ledger, September 11 and 13, 2026.
REVIEWED_LEDGER_SHA256 = "f96e89c7fa62380ff24bc32bceda8a1075e804b29d004f0c33c6f8d013c23fed"


@dataclass(frozen=True)
class GraphProductEvidence:
    station_id: str
    product_id: ProductId
    source_id: str
    native_field: str
    window_start: date
    window_end: date
    nonnull_observations: int
    availability: Literal["available", "unknown"]
    acquisition: AcquisitionRecord

    @property
    def availability_reason(self) -> str:
        conclusion = (
            f"{self.nonnull_observations} non-null {self.native_field} measurements"
            if self.availability == "available"
            else f"null-only {self.native_field}; availability outside the tested window is unknown"
        )
        return (
            f"ThaiWater graph {self.acquisition.acquisition_id}: {conclusion}; "
            f"tested {self.window_start} through {self.window_end} inclusive"
        )


@dataclass(frozen=True)
class GraphAvailabilityEvidence:
    reviewed_ledger: InitVar[bytes]
    pairs: tuple[GraphProductEvidence, ...] = field(init=False)

    def __post_init__(self, reviewed_ledger: bytes) -> None:
        if hashlib.sha256(reviewed_ledger).hexdigest() != REVIEWED_LEDGER_SHA256:
            raise FatalContractError("ThaiWater availability evidence digest mismatch: not the reviewed ledger")
        pairs = []
        for row in csv.DictReader(io.StringIO(reviewed_ledger.decode("utf-8"))):
            acquisition = AcquisitionRecord(
                acquisition_id=row["request_id"],
                method="http_request",
                instant_type="retrieval",
                description=(
                    f"Complete ThaiWater graph for station {row['station_id']}, "
                    f"{row['window_start']} through {row['window_end']} inclusive; "
                    "supplied through HII's platform by the native station agency. "
                    "This does not identify every historical original measurement producer. "
                    "Private source bytes verified at research acceptance; metadata binding only in public CI."
                ),
                requested_from=(row["request_url"],),
                retrieved_at_start=datetime.fromisoformat(row["retrieved_at"]),
                material=MaterialIdentity(
                    filename=PurePosixPath(row["evidence_body"]).name,
                    byte_count=int(row["response_bytes"]),
                    sha256=row["response_sha256"],
                ),
            )
            pairs.append(
                GraphProductEvidence(
                    station_id=row["station_id"],
                    product_id=ProductId(row["product_id"]),
                    source_id=row["source_id"],
                    native_field=row["native_field"],
                    window_start=date.fromisoformat(row["window_start"]),
                    window_end=date.fromisoformat(row["window_end"]),
                    nonnull_observations=int(row["nonnull_observations"]),
                    availability=cast('Literal["available", "unknown"]', row["availability"]),
                    acquisition=acquisition,
                )
            )
        object.__setattr__(self, "pairs", tuple(pairs))
