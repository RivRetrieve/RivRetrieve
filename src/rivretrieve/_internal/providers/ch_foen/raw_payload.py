from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

from rivretrieve._internal.primitives import ProviderId


@dataclass(frozen=True)
class ChFoenRawCsvResponse:
    csv_bytes: bytes
    endpoint: str
    query: str
    status_code: int | None = None
    retrieved_at: datetime | None = None
    station_id: str | None = None
    product_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


@dataclass(frozen=True)
class ChFoenRawPayload:
    provider_id: ProviderId
    responses: tuple[ChFoenRawCsvResponse, ...]
    parsed: pl.DataFrame | None = None
