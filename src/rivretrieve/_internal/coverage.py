"""remainder : RequestedInterval × tuple[RequestedInterval, ...] → tuple[RequestedInterval, ...] (pure)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from rivretrieve._internal.primitives import ProductId

_PRECISION = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class RequestedInterval:
    """A closed native wall-clock interval at the store's microsecond precision."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("coverage endpoints must be naive native wall-clock timestamps")
        if self.start > self.end:
            raise ValueError("coverage start must not exceed end")


@dataclass(frozen=True, slots=True)
class CoverageInterval:
    station_id: str
    product_id: ProductId
    interval: RequestedInterval
    retrieved_at: datetime

    def __post_init__(self) -> None:
        if not self.station_id or not self.product_id or any(c in self.product_id for c in "/="):
            raise ValueError("coverage requires a station and a partition-safe product identifier")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() != timedelta(0):
            raise ValueError("coverage retrieval instant must be UTC")


def remainder(requested: RequestedInterval, held: tuple[RequestedInterval, ...]) -> tuple[RequestedInterval, ...]:
    remaining = [requested]
    for interval in held:
        pieces: list[RequestedInterval] = []
        for piece in remaining:
            if interval.end < piece.start or interval.start > piece.end:
                pieces.append(piece)
                continue
            if piece.start < interval.start:
                pieces.append(RequestedInterval(piece.start, interval.start - _PRECISION))
            if piece.end > interval.end:
                pieces.append(RequestedInterval(interval.end + _PRECISION, piece.end))
        remaining = pieces
    return tuple(remaining)


def served_coverage(
    held: tuple[CoverageInterval, ...], station_id: str, product_id: ProductId, requested: RequestedInterval
) -> tuple[CoverageInterval, ...]:
    return tuple(
        CoverageInterval(
            item.station_id,
            item.product_id,
            RequestedInterval(max(item.interval.start, requested.start), min(item.interval.end, requested.end)),
            item.retrieved_at,
        )
        for item in held
        if item.station_id == station_id
        and item.product_id == product_id
        and item.interval.start <= requested.end
        and item.interval.end >= requested.start
    )
