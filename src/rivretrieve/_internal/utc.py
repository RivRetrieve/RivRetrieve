"""to_utc : ObservationResult → ObservationResult (pure)."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.engine import ZoneValue
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationResult
from rivretrieve._internal.source_annotations import AnnotationBundle, with_annotations


def _convert_frame_timestamps(
    frame: pl.DataFrame,
    *,
    provider_id: object,
    row_kind: str,
) -> tuple[list[datetime], pl.DataType]:
    unknown_count = frame["time_zone"].eq("unknown").sum()
    if unknown_count:
        raise FatalContractError(
            f"Cannot convert {unknown_count} {row_kind} rows for provider "
            f"{str(provider_id)!r} to UTC because time_zone is 'unknown'"
        )

    time_dtype = frame.schema["time"]
    naive_dtype = pl.Datetime(time_dtype.time_unit) if isinstance(time_dtype, pl.Datetime) else time_dtype
    wall_clocks = frame["time"]
    if isinstance(time_dtype, pl.Datetime) and time_dtype.time_zone is not None:
        wall_clocks = wall_clocks.dt.replace_time_zone(None)
    converted_times = [
        _convert_wall_clock(wall_clock, zone)
        for wall_clock, zone in zip(
            wall_clocks.to_list(),
            frame["time_zone"].to_list(),
            strict=True,
        )
    ]
    return converted_times, naive_dtype


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
        Data keeps its ten identity-bearing columns and timestamp dtype. Conversion uses Python
        datetime values with microsecond precision, so submicrosecond precision
        is not preserved. Provenance, issues and receipts are unchanged.
        The input is not modified.

    Raises
    ------
    FatalContractError
        If any row has time_zone="unknown". The error gives the provider and count.
    ValueError
        If a zone value violates the zone vocabulary or an IANA zone cannot
        be resolved by the local timezone database.

    Notes
    -----
    No station catalogue or coordinate lookup is used. IANA conversions use
    Python timezone rules and the default fold for ambiguous labels. This does
    not establish a daily product's day definition or make series comparable.
    """
    converted_times, naive_dtype = _convert_frame_timestamps(
        result.data,
        provider_id=result.provenance.provider_id,
        row_kind="observation",
    )
    converted_data = result.data.with_columns(
        pl.Series("time", converted_times, dtype=naive_dtype),
        pl.Series("time_zone", ["+00:00"] * result.data.height, dtype=pl.Utf8),
    )
    converted = result.model_copy(update={"data": converted_data})
    if result._annotations.is_empty or not result._annotations.observation_tables:
        return converted
    converted_obs = {}
    for schema_id, table in result._annotations.observation_tables.items():
        ann_times, ann_dtype = _convert_frame_timestamps(
            table.rows,
            provider_id=result.provenance.provider_id,
            row_kind="annotation",
        )
        converted_obs[schema_id] = table.with_utc_timestamps(ann_times, ann_dtype)
    return with_annotations(
        converted,
        AnnotationBundle(
            observation_tables=converted_obs,
            series_tables=result._annotations.series_tables,
        ),
    )


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
