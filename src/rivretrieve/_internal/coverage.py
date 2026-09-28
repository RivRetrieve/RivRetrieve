"""Successful concrete-series interval coverage and closed interval arithmetic."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from rivretrieve._internal.time_axis import TimeAxis

_PRECISION = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class RequestedInterval:
    """A closed interval on an explicit time axis.

    ``start`` and ``end`` are naive timestamps, and both are included. The
    native axis uses source wall-clock labels. The UTC axis uses UTC labels.
    """

    start: datetime
    end: datetime
    axis: TimeAxis = field(default=TimeAxis.NATIVE, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.axis, TimeAxis):
            raise ValueError("coverage requires an explicit TimeAxis")
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("coverage endpoints must be naive timestamps on the declared axis")
        if self.start > self.end:
            raise ValueError("coverage start must not exceed end")


@dataclass(frozen=True, slots=True)
class CoverageInterval:
    """Successful coverage for exactly one concrete source series, not inventory.

    Coverage records that a retrieval succeeded for an interval. It does not
    mean that observations exist at every time step in that interval.

    Attributes
    ----------
    series_id : str
        Source series that was retrieved.
    interval : RequestedInterval
        Covered interval on its declared native or UTC time axis.
    retrieved_at : datetime.datetime or None
        UTC instant of the source retrieval, or None when it is not known.
    outcome_id : str
        Retrieval outcome that established the coverage. A successful
        answer with no rows can also establish coverage.
    facts_ids : tuple[str, ...]
        Physical-fact segments covered, when recorded.
    """

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
    if any(interval.axis != requested.axis for interval in held):
        raise ValueError("Cannot subtract coverage on a different time axis")
    remaining = [requested]
    for interval in held:
        pieces: list[RequestedInterval] = []
        for piece in remaining:
            if interval.end < piece.start or interval.start > piece.end:
                pieces.append(piece)
                continue
            if piece.start < interval.start:
                pieces.append(RequestedInterval(piece.start, interval.start - _PRECISION, axis=requested.axis))
            if piece.end > interval.end:
                pieces.append(RequestedInterval(interval.end + _PRECISION, piece.end, axis=requested.axis))
        remaining = pieces
    return tuple(remaining)


def served_coverage(
    held: tuple[CoverageInterval, ...], series_id: str, requested: RequestedInterval
) -> tuple[CoverageInterval, ...]:
    return tuple(
        CoverageInterval(
            item.series_id,
            RequestedInterval(
                max(item.interval.start, requested.start), min(item.interval.end, requested.end), axis=requested.axis
            ),
            item.retrieved_at,
            item.outcome_id,
            item.facts_ids,
        )
        for item in held
        if item.series_id == series_id
        and item.interval.axis == requested.axis
        and item.interval.start <= requested.end
        and item.interval.end >= requested.start
    )


def interval_envelope(interval: RequestedInterval, target: TimeAxis) -> RequestedInterval:
    """Bound possible labels on another axis without assigning a source zone.

    Bounds expand by 23 hours and 59 minutes at each end to include every
    representable fixed offset. This mathematical envelope is a request bound,
    not a transformation of complete coverage or evidence of a known zone.
    """
    if not isinstance(target, TimeAxis):
        raise ValueError("An interval envelope requires an explicit TimeAxis")
    if interval.axis == target:
        return interval
    offset = timedelta(hours=23, minutes=59)
    start = interval.start - min(offset, interval.start - datetime.min)
    end = interval.end + min(offset, datetime.max - interval.end)
    return RequestedInterval(start, end, axis=target)
