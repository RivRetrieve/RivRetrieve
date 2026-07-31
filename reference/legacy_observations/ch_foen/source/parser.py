from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ch_foen.issue_codes import (
    ChFoenObservationIssueCodes,
    ChFoenParserFatalCodes,
)

PROVIDER_ID = ProviderId("ch_foen")
REQUIRED_COLUMNS = frozenset({"_time", "_value", "_field", "_measurement", "loc"})
_EXPLICIT_OFFSET_PATTERN = re.compile(r"(Z|[+-]\d{2}:\d{2})$")

_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "native_field": pl.Utf8,
        "native_value": pl.Float64,
        "measurement": pl.Utf8,
        "window_start": pl.Datetime(time_unit="us", time_zone="UTC"),
        "window_stop": pl.Datetime(time_unit="us", time_zone="UTC"),
        "table": pl.Int64,
    }
)


class ChFoenObservationParserError(FatalContractError):
    def __init__(self, code: ChFoenParserFatalCodes | str, message: str) -> None:
        self.code = str(code)
        super().__init__(message)


@dataclass(frozen=True)
class ChFoenParsedObservationPayload:
    records: pl.DataFrame
    source_columns: tuple[str, ...]
    issues: tuple[Issue, ...]


def parse_ch_foen_observation_csv(csv_bytes: bytes) -> ChFoenParsedObservationPayload:
    if not csv_bytes.strip():
        return ChFoenParsedObservationPayload(
            records=_empty_records(),
            source_columns=(),
            issues=(_missing_data_issue(),),
        )

    try:
        csv_bytes.decode("utf-8")
        source = pl.read_csv(BytesIO(csv_bytes), infer_schema=False)
    except (UnicodeDecodeError, pl.exceptions.PolarsError) as exc:
        raise ChFoenObservationParserError(ChFoenParserFatalCodes.MALFORMED_CSV, "malformed Flux CSV") from exc

    source_columns = tuple(source.columns)
    missing_columns = REQUIRED_COLUMNS - set(source_columns)
    if missing_columns:
        raise ChFoenObservationParserError(
            ChFoenParserFatalCodes.MISSING_REQUIRED_COLUMN,
            f"missing required Flux CSV columns: {sorted(missing_columns)}",
        )

    if source.is_empty():
        return ChFoenParsedObservationPayload(
            records=_empty_records(),
            source_columns=source_columns,
            issues=(_missing_data_issue(),),
        )

    source = source.filter(pl.any_horizontal(pl.col(column).is_not_null() for column in REQUIRED_COLUMNS))
    if source.is_empty():
        return ChFoenParsedObservationPayload(
            records=_empty_records(),
            source_columns=source_columns,
            issues=(_missing_data_issue(),),
        )

    parsed = source.with_columns(
        time=pl.col("_time").str.to_datetime(time_zone="UTC", strict=False),
        native_value=pl.col("_value").cast(pl.Float64, strict=False),
        window_start=_datetime_column("_start", source_columns),
        window_stop=_datetime_column("_stop", source_columns),
        table=_integer_column("table", source_columns),
    )
    invalid_timestamp_count = parsed.filter(pl.col("time").is_null()).height
    invalid_numeric_count = parsed.filter(pl.col("native_value").is_null()).height
    timezone_ambiguous_count = parsed.filter(
        pl.col("time").is_not_null()
        & pl.col("_time").is_not_null()
        & ~pl.col("_time").str.contains(_EXPLICIT_OFFSET_PATTERN.pattern)
    ).height

    records = (
        parsed.filter(pl.col("time").is_not_null() & pl.col("native_value").is_not_null())
        .select(
            "time",
            pl.col("loc").cast(pl.Utf8).alias("station_id"),
            pl.col("_field").cast(pl.Utf8).alias("native_field"),
            "native_value",
            pl.col("_measurement").cast(pl.Utf8).alias("measurement"),
            "window_start",
            "window_stop",
            "table",
        )
        .cast(_RECORDS_SCHEMA)
    )

    issues: list[Issue] = []
    if records.is_empty():
        issues.append(_missing_data_issue())
    else:
        if invalid_timestamp_count:
            issues.append(
                _parser_issue(
                    ChFoenObservationIssueCodes.INVALID_TIMESTAMP,
                    "Dropped rows with invalid timestamps",
                    {"dropped_rows": invalid_timestamp_count},
                )
            )
        if invalid_numeric_count:
            issues.append(
                _parser_issue(
                    ChFoenObservationIssueCodes.INVALID_NUMERIC_VALUE,
                    "Dropped rows with invalid numeric values",
                    {"dropped_rows": invalid_numeric_count},
                )
            )
        if timezone_ambiguous_count:
            issues.append(
                _parser_issue(
                    ChFoenObservationIssueCodes.TIMEZONE_AMBIGUITY,
                    "Parsed rows with timestamps that lack an explicit UTC offset",
                    {"rows": timezone_ambiguous_count},
                )
            )

    return ChFoenParsedObservationPayload(
        records=records,
        source_columns=source_columns,
        issues=tuple(issues),
    )


def _datetime_column(name: str, source_columns: tuple[str, ...]) -> pl.Expr:
    if name in source_columns:
        return pl.col(name).str.to_datetime(time_zone="UTC", strict=False)
    return pl.lit(None, dtype=pl.Datetime(time_unit="us", time_zone="UTC"))


def _integer_column(name: str, source_columns: tuple[str, ...]) -> pl.Expr:
    if name in source_columns:
        return pl.col(name).cast(pl.Int64, strict=False)
    return pl.lit(None, dtype=pl.Int64)


def _empty_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_RECORDS_SCHEMA)


def _missing_data_issue() -> Issue:
    return _parser_issue(ChFoenObservationIssueCodes.MISSING_DATA, "No observation rows found", None)


def _parser_issue(
    code: ChFoenObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
