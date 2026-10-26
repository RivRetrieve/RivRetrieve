"""Interpret public windows using established physical calendar facts."""

import re
from datetime import datetime, time, timedelta

from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.source_series import ClippingAxis, PhysicalFacts


def _fixed_offset(value: str | None) -> timedelta | None:
    if value == "UTC":
        return timedelta()
    if value is None:
        return None
    value = value.removeprefix("UTC")
    if re.fullmatch(r"[+-](?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is None:
        return None
    offset = timedelta(hours=int(value[1:3]), minutes=int(value[4:6]))
    return -offset if value.startswith("-") else offset


def native_window(start: datetime, end: datetime, facts: PhysicalFacts) -> RequestedInterval:
    """Return closed source-label bounds for a public physical window.

    Established start-labelled calendar periods use their fixed calendar zone.
    Daily labels retain whole-date clipping; monthly and yearly labels preserve
    explicit clock bounds. Other series use source timestamps. Returned
    observation labels are never changed.
    """
    offset = None
    if (
        facts.temporal_support.value in {"calendar_day", "calendar_month", "calendar_year"}
        and facts.timestamp_anchor.value == "start"
    ):
        calendar = _fixed_offset(facts.day_definition.value)
        source = _fixed_offset(facts.time_zone.value)
        if calendar is not None and source is not None:
            offset = calendar - source
    if (
        offset is not None and facts.temporal_support.value == "calendar_day"
    ) or facts.clipping_axis is ClippingAxis.CALENDAR_DATE:
        start = datetime.combine(start.date(), time.min)
        end = datetime.combine(end.date(), time.max)
    if offset is not None:
        start -= offset
        end -= offset
    return RequestedInterval(start, end)


def native_window_envelope(start: datetime, end: datetime, facts: tuple[PhysicalFacts, ...]) -> RequestedInterval:
    """Bound the source-label intervals needed by the selected physical facts."""
    intervals = tuple(native_window(start, end, fact) for fact in facts)
    return (
        RequestedInterval(min(item.start for item in intervals), max(item.end for item in intervals))
        if intervals
        else RequestedInterval(start, end)
    )
