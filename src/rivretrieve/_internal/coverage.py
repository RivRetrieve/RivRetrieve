"""Successful concrete-series interval coverage and closed interval arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

_PRECISION = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class RequestedInterval:
    """A closed interval on the native wall-clock label axis."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("coverage endpoints must be naive native wall-clock timestamps")
        if self.start > self.end:
            raise ValueError("coverage start must not exceed end")


@dataclass(frozen=True, slots=True)
class CoverageInterval:
    """Successful coverage for exactly one concrete source series, not inventory."""

    series_id: str
    interval: RequestedInterval
    retrieved_at: datetime | None
    outcome_id: str
    facts_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.facts_ids)) != len(self.facts_ids) or any(not value for value in self.facts_ids):
            raise ValueError("coverage physical fact identifiers must be unique and nonempty")
        if not self.series_id or not self.outcome_id:
            raise ValueError("coverage requires a concrete series and successful outcome")
        if self.retrieved_at is not None and (
            self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("known coverage retrieval instant must be UTC")


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
    held: tuple[CoverageInterval, ...], series_id: str, requested: RequestedInterval
) -> tuple[CoverageInterval, ...]:
    return tuple(
        CoverageInterval(
            item.series_id,
            RequestedInterval(max(item.interval.start, requested.start), min(item.interval.end, requested.end)),
            item.retrieved_at,
            item.outcome_id,
            item.facts_ids,
        )
        for item in held
        if item.series_id == series_id and item.interval.start <= requested.end and item.interval.end >= requested.start
    )
