from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isclose

import polars as pl

from rivretrieve._internal.issues import InvalidObservationRequestError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ch_foen.issue_codes import ChFoenObservationIssueCodes
from rivretrieve._internal.providers.ch_foen.query import (
    ChFoenProductPolicy,
    ChFoenTimeWindow,
    native_unit_for,
    provider_query_fields_json,
)

PROVIDER_ID = ProviderId("ch_foen")
UTC_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")

_DATA_SCHEMA = {
    "time": UTC_DTYPE,
    "station_id": pl.Utf8,
    "product_id": pl.Utf8,
    "value": pl.Float64,
}
_ROW_ANNOTATION_SCHEMA = {
    "time": pl.Datetime(time_unit="us"),
    "station_id": pl.Utf8,
    "product_id": pl.Utf8,
    "annotation": pl.Utf8,
    "value": pl.Utf8,
}
_SERIES_ANNOTATION_SCHEMA = {
    "station_id": pl.Utf8,
    "product_id": pl.Utf8,
    "annotation": pl.Utf8,
    "value": pl.Utf8,
}


@dataclass(frozen=True)
class ChFoenTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


@dataclass(frozen=True)
class _SelectedPoint:
    time: datetime
    station_id: str
    product_id: str
    native_field: str
    native_unit: str
    raw_value: float
    value: float
    alternative_native_field: str | None = None
    alternative_raw_value: float | None = None
    alternative_native_unit: str | None = None


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: ChFoenProductPolicy,
    windows: tuple[ChFoenTimeWindow, ...],
    endpoint: str,
    source_query: str,
    timezone_mismatch: bool = False,
) -> ChFoenTransformedSeries:
    scoped = _scope_records(records, station_id=station_id, policy=policy)
    if scoped.is_empty():
        return ChFoenTransformedSeries(
            data=_empty_data(),
            row_annotations=_empty_row_annotations(),
            series_annotations=_series_annotations(
                station_id=station_id,
                policy=policy,
                windows=windows,
                endpoint=endpoint,
                returned_start=None,
                returned_end=None,
                fallback_used=False,
                native_units=(),
                timezone_mismatch=timezone_mismatch,
            ),
            issues=(
                _issue(
                    ChFoenObservationIssueCodes.MISSING_DATA,
                    "No rows remained after station/product/native-field filtering",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    selected, selection_issues = _select_points(scoped, policy=policy)
    selected = tuple(point for point in selected if _in_windows(point.time, windows))
    if policy.aggregate_daily:
        selected = _aggregate_daily(selected, policy=policy)

    selected = tuple(sorted(selected, key=lambda point: point.time))
    gap_issues = _gap_issues(selected, policy=policy, windows=windows, station_id=station_id)
    issues = selection_issues + gap_issues
    if not selected:
        issues = issues + (
            _issue(
                ChFoenObservationIssueCodes.MISSING_DATA,
                "No observation rows remained after transformation",
                {"station_id": station_id, "product_id": policy.product_id},
            ),
        )

    native_units = tuple(sorted({point.native_unit for point in selected}))
    fallback_used = any(point.native_field == policy.fallback_field for point in selected)
    returned_start = selected[0].time if selected else None
    returned_end = selected[-1].time if selected else None

    return ChFoenTransformedSeries(
        data=_data_frame(selected),
        row_annotations=_row_annotations(selected, source_query=source_query, policy=policy),
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            windows=windows,
            endpoint=endpoint,
            returned_start=returned_start,
            returned_end=returned_end,
            fallback_used=fallback_used,
            native_units=native_units,
            timezone_mismatch=timezone_mismatch,
        ),
        issues=issues,
    )


def stitch_transformed_series(series: tuple[ChFoenTransformedSeries, ...]) -> ChFoenTransformedSeries:
    if not series:
        return ChFoenTransformedSeries(_empty_data(), _empty_row_annotations(), _empty_series_annotations(), ())

    data = pl.concat([item.data for item in series], how="vertical") if series else _empty_data()
    rows = pl.concat([item.row_annotations for item in series], how="vertical") if series else _empty_row_annotations()
    series_annotations = _merge_series_annotations(tuple(item.series_annotations for item in series))
    issues: list[Issue] = [issue for item in series for issue in item.issues]

    if data.is_empty():
        return ChFoenTransformedSeries(data, rows, series_annotations, tuple(issues))

    kept_rows: list[dict[str, object]] = []
    for (_station_id, _product_id, _time), group in data.group_by(
        "station_id", "product_id", "time", maintain_order=True
    ):
        values = group["value"].to_list()
        kept_rows.append(group.row(0, named=True))
        if len(values) <= 1:
            continue
        if all(isclose(float(value), float(values[0]), rel_tol=0.0, abs_tol=1e-12) for value in values[1:]):
            issues.append(
                _issue(
                    ChFoenObservationIssueCodes.OVERLAP,
                    "Duplicate stitched rows carried the same canonical value",
                    {"station_id": _station_id, "product_id": _product_id, "time": _iso_z(_time)},
                )
            )
        else:
            issues.append(
                _issue(
                    ChFoenObservationIssueCodes.CONFLICT,
                    "Duplicate stitched rows carried conflicting canonical values",
                    {"station_id": _station_id, "product_id": _product_id, "time": _iso_z(_time)},
                )
            )

    return ChFoenTransformedSeries(
        data=pl.DataFrame(kept_rows, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"]),
        row_annotations=rows,
        series_annotations=series_annotations,
        issues=tuple(issues),
    )


def empty_data() -> pl.DataFrame:
    return _empty_data()


def empty_row_annotations() -> pl.DataFrame:
    return _empty_row_annotations()


def empty_series_annotations() -> pl.DataFrame:
    return _empty_series_annotations()


def _scope_records(records: pl.DataFrame, *, station_id: str, policy: ChFoenProductPolicy) -> pl.DataFrame:
    if records.is_empty():
        return records
    return records.filter(
        (pl.col("station_id") == station_id)
        & (pl.col("measurement") == "hydro")
        & pl.col("native_field").is_in(policy.native_fields)
    )


def _select_points(
    records: pl.DataFrame, *, policy: ChFoenProductPolicy
) -> tuple[tuple[_SelectedPoint, ...], tuple[Issue, ...]]:
    selected: list[_SelectedPoint] = []
    issues: list[Issue] = []
    for (_station_id, _time), group in records.group_by("station_id", "time", maintain_order=True):
        by_field = {row["native_field"]: row for row in group.iter_rows(named=True)}
        preferred = by_field.get(policy.preferred_field)
        fallback = by_field.get(policy.fallback_field) if policy.fallback_field is not None else None
        chosen = preferred or fallback
        alternative = fallback if preferred is not None else None
        if chosen is None:
            issues.append(
                _issue(
                    ChFoenObservationIssueCodes.UNIT_CONVERSION_AMBIGUITY,
                    "No deterministic conversion rule for provider native field",
                    {"native_fields": sorted(by_field)},
                )
            )
            continue

        try:
            point = _point_from_row(chosen, product_id=policy.product_id)
        except InvalidObservationRequestError:
            issues.append(
                _issue(
                    ChFoenObservationIssueCodes.UNIT_CONVERSION_AMBIGUITY,
                    "No deterministic conversion rule for provider native field",
                    {"native_field": chosen["native_field"]},
                )
            )
            continue
        if alternative is not None:
            try:
                alt_point = _point_from_row(alternative, product_id=policy.product_id)
            except InvalidObservationRequestError:
                issues.append(
                    _issue(
                        ChFoenObservationIssueCodes.UNIT_CONVERSION_AMBIGUITY,
                        "No deterministic conversion rule for alternative provider native field",
                        {"native_field": alternative["native_field"]},
                    )
                )
                selected.append(point)
                continue
            point = _SelectedPoint(
                time=point.time,
                station_id=point.station_id,
                product_id=point.product_id,
                native_field=point.native_field,
                native_unit=point.native_unit,
                raw_value=point.raw_value,
                value=point.value,
                alternative_native_field=alt_point.native_field,
                alternative_raw_value=alt_point.raw_value,
                alternative_native_unit=alt_point.native_unit,
            )
            if isclose(point.value, alt_point.value, rel_tol=0.0, abs_tol=1e-12):
                code = ChFoenObservationIssueCodes.OVERLAP
                message = "Preferred and fallback native fields overlap at one timestamp"
            else:
                code = ChFoenObservationIssueCodes.CONFLICT
                message = "Preferred and fallback native fields conflict at one timestamp"
            issues.append(
                _issue(
                    code,
                    message,
                    {
                        "station_id": _station_id,
                        "product_id": policy.product_id,
                        "time": _iso_z(_time),
                        "preferred_field": policy.preferred_field,
                        "fallback_field": policy.fallback_field,
                    },
                )
            )
        selected.append(point)
    return tuple(selected), tuple(issues)


def _point_from_row(row: dict[str, object], *, product_id: str) -> _SelectedPoint:
    native_field = str(row["native_field"])
    native_value_obj = row["native_value"]
    if not isinstance(native_value_obj, int | float):
        raise InvalidObservationRequestError("native_value must be numeric")
    native_value = float(native_value_obj)
    time = row["time"]
    if not isinstance(time, datetime):
        raise InvalidObservationRequestError("time must be a datetime")
    native_unit = native_unit_for(native_field)
    return _SelectedPoint(
        time=time,
        station_id=str(row["station_id"]),
        product_id=product_id,
        native_field=native_field,
        native_unit=native_unit,
        raw_value=native_value,
        value=_convert_value(native_field, native_value),
    )


def _convert_value(native_field: str, raw_value: float) -> float:
    if native_field == "flow_ls":
        return raw_value * 0.001
    return raw_value


def _aggregate_daily(points: tuple[_SelectedPoint, ...], *, policy: ChFoenProductPolicy) -> tuple[_SelectedPoint, ...]:
    grouped: dict[tuple[str, datetime], list[_SelectedPoint]] = {}
    for point in points:
        day = datetime(point.time.year, point.time.month, point.time.day, tzinfo=UTC)
        grouped.setdefault((point.station_id, day), []).append(point)

    aggregated: list[_SelectedPoint] = []
    for (station_id, day), day_points in grouped.items():
        value = sum(point.value for point in day_points) / len(day_points)
        raw_value = sum(point.raw_value for point in day_points) / len(day_points)
        native_fields = {point.native_field for point in day_points}
        native_field = policy.preferred_field if policy.preferred_field in native_fields else day_points[0].native_field
        native_unit = native_unit_for(native_field)
        alternatives = [point for point in day_points if point.alternative_native_field is not None]
        alt_field = alternatives[0].alternative_native_field if alternatives else None
        alt_raw = (
            sum(point.alternative_raw_value for point in alternatives if point.alternative_raw_value is not None)
            / len(alternatives)
            if alternatives
            else None
        )
        alt_unit = alternatives[0].alternative_native_unit if alternatives else None
        aggregated.append(
            _SelectedPoint(
                time=day,
                station_id=station_id,
                product_id=policy.product_id,
                native_field=native_field,
                native_unit=native_unit,
                raw_value=raw_value,
                value=value,
                alternative_native_field=alt_field,
                alternative_raw_value=alt_raw,
                alternative_native_unit=alt_unit,
            )
        )
    return tuple(aggregated)


def _gap_issues(
    points: tuple[_SelectedPoint, ...],
    *,
    policy: ChFoenProductPolicy,
    windows: tuple[ChFoenTimeWindow, ...],
    station_id: str,
) -> tuple[Issue, ...]:
    if not policy.aggregate_daily or not points or not windows:
        return ()
    returned_days = {point.time.date() for point in points}
    expected_days = set()
    for window in windows:
        current = window.start.date()
        while current <= window.end.date():
            expected_days.add(current)
            current += timedelta(days=1)
    missing = sorted(day.isoformat() for day in expected_days - returned_days)
    if not missing:
        return ()
    return (
        _issue(
            ChFoenObservationIssueCodes.GAP,
            "Daily observation series has missing dates",
            {"station_id": station_id, "product_id": policy.product_id, "missing_dates": missing},
        ),
    )


def _in_windows(value: datetime, windows: tuple[ChFoenTimeWindow, ...]) -> bool:
    return any(window.start <= value < window.query_stop for window in windows)


def _data_frame(points: tuple[_SelectedPoint, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "time": point.time,
                "station_id": point.station_id,
                "product_id": point.product_id,
                "value": point.value,
            }
            for point in points
        ],
        schema=_DATA_SCHEMA,
    )


def _row_annotations(
    points: tuple[_SelectedPoint, ...],
    *,
    source_query: str,
    policy: ChFoenProductPolicy,
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for point in points:
        base = {
            "time": _annotation_time(point.time),
            "station_id": point.station_id,
            "product_id": point.product_id,
        }
        values = {
            "native_field": point.native_field,
            "native_unit": point.native_unit,
            "converted_unit": policy.canonical_unit,
            "source_endpoint_or_query": source_query,
            "raw_value": _float_string(point.raw_value),
            "alternative_native_field": point.alternative_native_field,
            "alternative_raw_value": None
            if point.alternative_raw_value is None
            else _float_string(point.alternative_raw_value),
            "alternative_native_unit": point.alternative_native_unit,
        }
        rows.extend({**base, "annotation": annotation, "value": value} for annotation, value in values.items())
    return pl.DataFrame(rows, schema=_ROW_ANNOTATION_SCHEMA)


def _series_annotations(
    *,
    station_id: str,
    policy: ChFoenProductPolicy,
    windows: tuple[ChFoenTimeWindow, ...],
    endpoint: str,
    returned_start: datetime | None,
    returned_end: datetime | None,
    fallback_used: bool,
    native_units: tuple[str, ...],
    timezone_mismatch: bool,
) -> pl.DataFrame:
    values = {
        "preferred_source": policy.preferred_field,
        "fallback_source_used": _bool_string(fallback_used),
        "native_unit_returned": json.dumps(list(native_units), sort_keys=True, separators=(",", ":")),
        "converted_unit": policy.canonical_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_mismatch_flag": _bool_string(timezone_mismatch),
        "provider_endpoint": endpoint,
        "provider_query_fields": provider_query_fields_json(station_id=station_id, policy=policy, windows=windows),
    }
    return pl.DataFrame(
        [
            {
                "station_id": station_id,
                "product_id": policy.product_id,
                "annotation": annotation,
                "value": value,
            }
            for annotation, value in values.items()
        ],
        schema=_SERIES_ANNOTATION_SCHEMA,
    )


def _merge_series_annotations(frames: tuple[pl.DataFrame, ...]) -> pl.DataFrame:
    if not frames:
        return _empty_series_annotations()
    merged = pl.concat(frames, how="vertical")
    if merged.is_empty():
        return merged
    return merged.unique(subset=["station_id", "product_id", "annotation"], keep="last", maintain_order=True)


def _empty_data() -> pl.DataFrame:
    return pl.DataFrame(schema=_DATA_SCHEMA)


def _empty_row_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_ROW_ANNOTATION_SCHEMA)


def _empty_series_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_SERIES_ANNOTATION_SCHEMA)


def _issue(code: ChFoenObservationIssueCodes, message: str, details: dict[str, object] | None) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)


def _float_string(value: float) -> str:
    return format(value, ".15g")


def _bool_string(value: bool) -> str:
    return "true" if value else "false"


def _iso_z(value: datetime) -> str:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _annotation_time(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.replace(tzinfo=None)
