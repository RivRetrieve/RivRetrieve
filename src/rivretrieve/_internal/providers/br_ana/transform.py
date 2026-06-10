from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.br_ana.issue_codes import BrAnaObservationIssueCodes
from rivretrieve._internal.providers.br_ana.parser import TELEMETRIC_QUALITY_FLAG_MAP

# ANA's documented operating timezone for telemetric stations (Brasília Standard Time).
# True per-station timezone is undocumented; BRT (UTC-3, no DST since 2019) is used as
# the most defensible single interpretation — see naive_local_timestamp issue.
_BRT = timezone(timedelta(hours=-3))

PROVIDER_ID = ProviderId("br_ana")
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
class BrAnaProductPolicy:
    product_id: str
    day_column_prefix: str  # "Vazao_" or "Cota_"
    api_endpoint: str
    native_unit: str
    canonical_unit: str
    conversion_factor: float  # divide raw by this


@dataclass(frozen=True)
class BrAnaTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, BrAnaProductPolicy] = {
    "discharge_daily_mean": BrAnaProductPolicy(
        product_id="discharge_daily_mean",
        day_column_prefix="Vazao_",
        api_endpoint="https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieVazao/v1",
        native_unit="m3/s",
        canonical_unit="m3/s",
        conversion_factor=1.0,
    ),
    "stage_daily_mean": BrAnaProductPolicy(
        product_id="stage_daily_mean",
        day_column_prefix="Cota_",
        api_endpoint="https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieCotas/v1",
        native_unit="cm",
        canonical_unit="m",
        conversion_factor=100.0,
    ),
}


@dataclass(frozen=True)
class BrAnaTelemetricProductPolicy:
    product_id: str
    native_field: str  # e.g. "Vazao_Adotada" / "Cota_Adotada" / "Temperatura_Agua"
    api_endpoint: str
    native_unit: str
    canonical_unit: str
    conversion_factor: float  # divide raw by this


TELEMETRIC_PRODUCT_POLICIES: dict[str, BrAnaTelemetricProductPolicy] = {
    "discharge_instantaneous": BrAnaTelemetricProductPolicy(
        product_id="discharge_instantaneous",
        native_field="Vazao_Adotada",
        api_endpoint="https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1",
        native_unit="m3/s",
        canonical_unit="m3/s",
        conversion_factor=1.0,
    ),
    "stage_instantaneous": BrAnaTelemetricProductPolicy(
        product_id="stage_instantaneous",
        native_field="Cota_Adotada",
        api_endpoint="https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1",
        native_unit="cm",
        canonical_unit="m",
        conversion_factor=100.0,
    ),
    "water_temperature_instantaneous": BrAnaTelemetricProductPolicy(
        product_id="water_temperature_instantaneous",
        native_field="Temperatura_Agua",
        api_endpoint="https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaDetalhada/v1",
        native_unit="degC",
        canonical_unit="degC",
        conversion_factor=1.0,
    ),
}


def resolve_telemetric_product_policy(product_id: str) -> BrAnaTelemetricProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in TELEMETRIC_PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported br_ana telemetric observation product: {product_id}")
    return TELEMETRIC_PRODUCT_POLICIES[product_id]


def resolve_product_policy(product_id: str) -> BrAnaProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported br_ana observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: BrAnaProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
) -> BrAnaTransformedSeries:
    if records.is_empty():
        return _empty_series(station_id, policy, windows, endpoints, "No rows after parsing")

    valid = records.filter(pl.col("raw_value").is_not_null())
    if valid.is_empty():
        return _empty_series(station_id, policy, windows, endpoints, "No rows with non-null raw_value")

    deduped = valid.sort("time").unique(subset=["time"], keep="last", maintain_order=True)

    rows_data: list[dict[str, object]] = []
    rows_ann: list[dict[str, object]] = []

    for row in deduped.iter_rows(named=True):
        t = row["time"]
        if not isinstance(t, datetime):
            continue
        raw = row["raw_value"]
        if not isinstance(raw, float):
            raw = float(raw)
        value = raw / policy.conversion_factor

        rows_data.append(
            {
                "time": t,
                "station_id": station_id,
                "product_id": policy.product_id,
                "value": value,
            }
        )

        ann_time = t.replace(tzinfo=None) if t.tzinfo is not None else t
        ann_pairs: dict[str, str] = {
            "native_unit": policy.native_unit,
            "converted_unit": policy.canonical_unit,
            "raw_value": _float_string(raw),
        }
        for annotation, ann_value in ann_pairs.items():
            rows_ann.append(
                {
                    "time": ann_time,
                    "station_id": station_id,
                    "product_id": policy.product_id,
                    "annotation": annotation,
                    "value": ann_value,
                }
            )

    if not rows_data:
        return _empty_series(
            station_id, policy, windows, endpoints, "No observation rows remained after transformation"
        )

    data_df = pl.DataFrame(rows_data, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)

    times_list = data_df["time"].to_list()
    returned_start = times_list[0] if times_list else None
    returned_end = times_list[-1] if times_list else None

    return BrAnaTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            windows=windows,
            endpoints=endpoints,
            returned_start=returned_start,
            returned_end=returned_end,
        ),
        issues=(),
    )


def transform_telemetric_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: BrAnaTelemetricProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
) -> BrAnaTransformedSeries:
    """Transform parsed telemetric records (naive local time + raw quality_flag).

    Differences from ``transform_series`` (legacy daily columnar series):
    - Input timestamps are naive local (Brasília Standard Time, UTC-3) and are
      converted to UTC here.
    - A ``quality_flag`` row annotation is emitted alongside ``native_unit``/
      ``converted_unit``/``raw_value``, mapping ANA's numeric status codes
      ("0"/"1"/"2") to canonical strings ("ok"/"suspect"/"poor") via
      ``TELEMETRIC_QUALITY_FLAG_MAP``. Unknown/missing codes pass through as
      "unknown".
    """
    if records.is_empty():
        return _empty_telemetric_series(station_id, policy, windows, endpoints, "No rows after parsing")

    valid = records.filter(pl.col("raw_value").is_not_null())
    if valid.is_empty():
        return _empty_telemetric_series(station_id, policy, windows, endpoints, "No rows with non-null raw_value")

    deduped = valid.sort("time").unique(subset=["time"], keep="last", maintain_order=True)

    rows_data: list[dict[str, object]] = []
    rows_ann: list[dict[str, object]] = []

    for row in deduped.iter_rows(named=True):
        local_t = row["time"]
        if not isinstance(local_t, datetime):
            continue
        utc_t = local_t.replace(tzinfo=_BRT).astimezone(UTC)

        raw = row["raw_value"]
        if not isinstance(raw, float):
            raw = float(raw)
        value = raw / policy.conversion_factor

        rows_data.append(
            {
                "time": utc_t,
                "station_id": station_id,
                "product_id": policy.product_id,
                "value": value,
            }
        )

        ann_time = utc_t.replace(tzinfo=None)
        flag_raw = row.get("quality_flag") or ""
        flag_canonical = TELEMETRIC_QUALITY_FLAG_MAP.get(flag_raw, "unknown" if flag_raw else "")
        ann_pairs: dict[str, str] = {
            "native_unit": policy.native_unit,
            "converted_unit": policy.canonical_unit,
            "raw_value": _float_string(raw),
        }
        if flag_canonical:
            ann_pairs["quality_flag"] = flag_canonical
        for annotation, ann_value in ann_pairs.items():
            rows_ann.append(
                {
                    "time": ann_time,
                    "station_id": station_id,
                    "product_id": policy.product_id,
                    "annotation": annotation,
                    "value": ann_value,
                }
            )

    if not rows_data:
        return _empty_telemetric_series(
            station_id, policy, windows, endpoints, "No observation rows remained after transformation"
        )

    data_df = pl.DataFrame(rows_data, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)

    times_list = data_df["time"].to_list()
    returned_start = times_list[0] if times_list else None
    returned_end = times_list[-1] if times_list else None

    return BrAnaTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_telemetric_series_annotations(
            station_id=station_id,
            policy=policy,
            windows=windows,
            endpoints=endpoints,
            returned_start=returned_start,
            returned_end=returned_end,
        ),
        issues=(),
    )


def _empty_telemetric_series(
    station_id: str,
    policy: BrAnaTelemetricProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    reason: str,
) -> BrAnaTransformedSeries:
    return BrAnaTransformedSeries(
        data=empty_data(),
        row_annotations=empty_row_annotations(),
        series_annotations=_telemetric_series_annotations(
            station_id=station_id,
            policy=policy,
            windows=windows,
            endpoints=endpoints,
            returned_start=None,
            returned_end=None,
        ),
        issues=(
            _issue(
                BrAnaObservationIssueCodes.MISSING_DATA,
                reason,
                {"station_id": station_id, "product_id": policy.product_id},
            ),
        ),
    )


def _telemetric_series_annotations(
    *,
    station_id: str,
    policy: BrAnaTelemetricProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": "naive_local_brt_minus_3",
        "date_only_timestamp_flag": "false",
        "provider_endpoints": json.dumps(list(endpoints), sort_keys=True, separators=(",", ":")),
        "requested_windows": json.dumps([list(w) for w in windows], sort_keys=True, separators=(",", ":")),
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


def empty_data() -> pl.DataFrame:
    return pl.DataFrame(schema=_DATA_SCHEMA)


def empty_row_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_ROW_ANNOTATION_SCHEMA)


def empty_series_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_SERIES_ANNOTATION_SCHEMA)


def _empty_series(
    station_id: str,
    policy: BrAnaProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    reason: str,
) -> BrAnaTransformedSeries:
    return BrAnaTransformedSeries(
        data=empty_data(),
        row_annotations=empty_row_annotations(),
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            windows=windows,
            endpoints=endpoints,
            returned_start=None,
            returned_end=None,
        ),
        issues=(
            _issue(
                BrAnaObservationIssueCodes.MISSING_DATA,
                reason,
                {"station_id": station_id, "product_id": policy.product_id},
            ),
        ),
    )


def _series_annotations(
    *,
    station_id: str,
    policy: BrAnaProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": "date_only_utc_midnight",
        "date_only_timestamp_flag": "true",
        "provider_endpoints": json.dumps(list(endpoints), sort_keys=True, separators=(",", ":")),
        "requested_windows": json.dumps([list(w) for w in windows], sort_keys=True, separators=(",", ":")),
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


def _float_string(value: float) -> str:
    return format(value, ".15g")


def _iso_z(value: object) -> str:
    if isinstance(value, datetime):
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _issue(
    code: BrAnaObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
