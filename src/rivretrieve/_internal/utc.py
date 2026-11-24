"""to_utc : ObservationResult → ObservationResult (pure)."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.engine import ZoneValue
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationResult
from rivretrieve._internal.source_annotations import AnnotationBundle, with_annotations


def _convert_iana_series(wall_series: pl.Series, tz_name: str, naive_dtype: pl.DataType) -> pl.Series:
    try:
        converted = (
            wall_series.dt.replace_time_zone(tz_name, ambiguous="earliest", non_existent="null")
            .dt.convert_time_zone("UTC")
            .dt.replace_time_zone(None)
        )
    except pl.exceptions.ComputeError:
        return pl.Series(
            "time",
            [_convert_wall_clock(ts, tz_name) for ts in wall_series.to_list()],
            dtype=naive_dtype,
        )
    if converted.dtype != naive_dtype:
        converted = converted.cast(naive_dtype)
    gap_mask = converted.is_null() & wall_series.is_not_null()
    if gap_mask.any():
        gap_indices = gap_mask.arg_true().to_list()
        gap_walls = wall_series.gather(gap_indices).to_list()
        patched = pl.DataFrame(
            {
                "_idx": pl.Series("_idx", gap_indices, dtype=pl.Int64),
                "_val": pl.Series(
                    "_val",
                    [_convert_wall_clock(ts, tz_name) for ts in gap_walls],
                    dtype=naive_dtype,
                ),
            }
        )
        converted = (
            pl.DataFrame({"_idx": pl.arange(0, wall_series.len(), eager=True, dtype=pl.Int64), "time": converted})
            .join(patched, on="_idx", how="left", maintain_order="left")
            .select(pl.when(pl.col("_val").is_not_null()).then(pl.col("_val")).otherwise(pl.col("time")).alias("time"))[
                "time"
            ]
        )
    return converted


def _convert_frame_timestamps(
    frame: pl.DataFrame,
    *,
    provider_id: object,
    row_kind: str,
) -> tuple[pl.Series, pl.DataType]:
    unknown_count = frame["time_zone"].eq("unknown").sum()
    if unknown_count:
        raise FatalContractError(
            f"Cannot convert {unknown_count} {row_kind} rows for provider "
            f"{str(provider_id)!r} to UTC because time_zone is 'unknown'"
        )

    time_dtype = frame.schema["time"]
    naive_dtype = pl.Datetime(time_dtype.time_unit) if isinstance(time_dtype, pl.Datetime) else time_dtype
    if frame.is_empty():
        return pl.Series("time", [], dtype=naive_dtype), naive_dtype
    wall_clocks = frame["time"]
    if isinstance(time_dtype, pl.Datetime) and time_dtype.time_zone is not None:
        wall_clocks = wall_clocks.dt.replace_time_zone(None)

    unique_zones = frame["time_zone"].unique(maintain_order=True).to_list()
    fixed_offset_us: dict[str, int] = {}
    iana_zones: list[str] = []
    for raw_zone in unique_zones:
        zone = ZoneValue(raw_zone)
        tz = _tzinfo(zone)
        if isinstance(tz, ZoneInfo):
            iana_zones.append(raw_zone)
        else:
            offset = tz.utcoffset(None)
            assert offset is not None
            fixed_offset_us[raw_zone] = (offset.days * 86_400 + offset.seconds) * 1_000_000 + offset.microseconds

    if not iana_zones:
        if len(fixed_offset_us) == 1:
            offset_us = next(iter(fixed_offset_us.values()))
            converted = wall_clocks if offset_us == 0 else (wall_clocks - timedelta(microseconds=offset_us))
            if converted.dtype != naive_dtype:
                converted = converted.cast(naive_dtype)
            return converted.alias("time"), naive_dtype
        converted = pl.DataFrame({"_t": wall_clocks, "time_zone": frame["time_zone"]}).select(
            (
                pl.col("_t")
                - pl.col("time_zone").replace_strict(fixed_offset_us, return_dtype=pl.Int64).cast(pl.Duration("us"))
            )
            .cast(naive_dtype)
            .alias("time")
        )["time"]
        return converted, naive_dtype

    if len(iana_zones) == 1 and not fixed_offset_us:
        return _convert_iana_series(wall_clocks, iana_zones[0], naive_dtype).alias("time"), naive_dtype

    base = pl.DataFrame(
        {
            "_row": pl.arange(0, frame.height, eager=True, dtype=pl.Int64),
            "time": wall_clocks,
            "time_zone": frame["time_zone"],
        }
    )
    parts: list[pl.DataFrame] = []
    if fixed_offset_us:
        fixed_sub = base.filter(pl.col("time_zone").is_in(list(fixed_offset_us)))
        parts.append(
            fixed_sub.select(
                "_row",
                (
                    pl.col("time")
                    - pl.col("time_zone").replace_strict(fixed_offset_us, return_dtype=pl.Int64).cast(pl.Duration("us"))
                )
                .cast(naive_dtype)
                .alias("time"),
            )
        )
    for tz_name in iana_zones:
        iana_sub = base.filter(pl.col("time_zone") == tz_name)
        converted_sub = _convert_iana_series(iana_sub["time"], tz_name, naive_dtype)
        parts.append(iana_sub.select("_row").with_columns(converted_sub.alias("time")))
    return pl.concat(parts).sort("_row")["time"], naive_dtype


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
    converted_times, _ = _convert_frame_timestamps(
        result.data,
        provider_id=result.provenance.provider_id,
        row_kind="observation",
    )
    converted_data = result.data.with_columns(
        converted_times.alias("time"),
        pl.lit("+00:00", dtype=pl.Utf8).alias("time_zone"),
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
