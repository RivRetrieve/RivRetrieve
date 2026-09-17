"""to_utc : ObservationResult → ObservationResult (pure)."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.engine import ZoneValue
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationResult


def to_utc(result: ObservationResult) -> ObservationResult:
    """Convert observation labels to UTC using each row's published zone.

    Parameters
    ----------
    result : ObservationResult
        Result whose time_zone values are established IANA identifiers or
        fixed offsets. Unknown zones are refused before converting any row.

    Returns
    -------
    ObservationResult
        New result with naive UTC time values and time_zone="+00:00" on every row.
        Data keeps its five columns and timestamp precision. Provenance, issues
        and receipts are unchanged. The input is not modified.

    Raises
    ------
    FatalContractError
        If any row has time_zone="unknown". The error gives the provider and count.
    ValueError
        If a zone value violates the zone vocabulary.
    zoneinfo.ZoneInfoNotFoundError
        If an IANA zone cannot be resolved by the local timezone database.

    Notes
    -----
    No station catalogue or coordinate lookup is used. IANA conversions use
    Python timezone rules and the default fold for ambiguous labels. This does
    not establish a daily product's day definition or make series comparable.
    """
    unknown_count = result.data["time_zone"].eq("unknown").sum()
    if unknown_count:
        raise FatalContractError(
            f"Cannot convert {unknown_count} observation rows for provider "
            f"{str(result.provenance.provider_id)!r} to UTC because time_zone is 'unknown'"
        )

    time_dtype = result.data.schema["time"]
    naive_dtype = pl.Datetime(time_dtype.time_unit) if isinstance(time_dtype, pl.Datetime) else time_dtype
    wall_clocks = result.data["time"]
    if isinstance(time_dtype, pl.Datetime) and time_dtype.time_zone is not None:
        wall_clocks = wall_clocks.dt.replace_time_zone(None)
    converted_times = [
        _convert_wall_clock(wall_clock, zone)
        for wall_clock, zone in zip(
            wall_clocks.to_list(),
            result.data["time_zone"].to_list(),
            strict=True,
        )
    ]
    converted_data = result.data.with_columns(
        pl.Series("time", converted_times, dtype=naive_dtype),
        pl.Series("time_zone", ["+00:00"] * result.data.height, dtype=pl.Utf8),
    )
    return result.model_copy(update={"data": converted_data})


def _convert_wall_clock(wall_clock: datetime, raw_zone: str) -> datetime:
    zone = ZoneValue(raw_zone)
    tzinfo = _tzinfo(zone)
    return wall_clock.replace(tzinfo=tzinfo).astimezone(UTC).replace(tzinfo=None)


def _tzinfo(zone: ZoneValue) -> timezone | ZoneInfo:
    if zone.value.startswith(("+", "-")):
        hours, minutes = (int(part) for part in zone.value[1:].split(":"))
        offset = timedelta(hours=hours, minutes=minutes)
        if zone.value.startswith("-"):
            offset = -offset
        return timezone(offset)
    return ZoneInfo(zone.value)
