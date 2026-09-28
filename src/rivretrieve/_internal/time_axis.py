"""Explicit axes for source wall-clock labels and UTC instants."""

import re
from datetime import datetime, timedelta
from enum import StrEnum

import polars as pl


class TimeAxis(StrEnum):
    NATIVE = "native"
    UTC = "utc"


def axis_time_expression(axis: TimeAxis) -> pl.Expr:
    """Read native labels or convert labels with published fixed offsets to UTC.

    UTC values remain naive timestamps on the UTC axis. Unknown zones, IANA
    names, and malformed offsets produce nulls rather than inferred instants.
    """
    if axis == TimeAxis.NATIVE:
        return pl.col("time")
    if axis != TimeAxis.UTC:
        raise ValueError(f"Unknown time axis: {axis}")
    zone = pl.col("time_zone")
    valid = zone.str.contains(r"^[+-](?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    hours = zone.str.slice(1, 2).cast(pl.Int64, strict=False)
    minutes = zone.str.slice(4, 2).cast(pl.Int64, strict=False)
    sign = pl.when(zone.str.starts_with("-")).then(-1).otherwise(1)
    offset = sign * (hours * 60 + minutes)
    return pl.when(valid).then(pl.col("time") - pl.duration(minutes=offset)).otherwise(None).alias("time")


def timestamp_on_axis(timestamp: datetime, zone: str | None, axis: TimeAxis) -> datetime | None:
    """Convert a source label using only its published fixed offset.

    Unknown zones and named zones have no established UTC value here.
    """
    if axis == TimeAxis.NATIVE:
        return timestamp
    if axis != TimeAxis.UTC:
        raise ValueError(f"Unknown time axis: {axis}")
    if zone is None or re.fullmatch(r"[+-](?:[01][0-9]|2[0-3]):[0-5][0-9]", zone) is None:
        return None
    offset = timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
    return timestamp + offset if zone.startswith("-") else timestamp - offset
