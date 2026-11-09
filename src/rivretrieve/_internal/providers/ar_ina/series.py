"""Official Argentina INA Alerta5 source-series identity, physical facts, and payload validation.

Kept free of network, filesystem, and runtime configuration I/O so offline
catalogue generation and future observation parsing share one verified contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    admission,
    known,
    stable_id,
)

NAMESPACE = "INA.Alerta5.series_id"
OBSERVATIONAL_PROCEDURES: frozenset[int] = frozenset({1, 2})
EXCLUDED_PROCEDURES: frozenset[int] = frozenset({3, 4, 5, 6, 7, 8, 9})

UNITS: dict[str, str] = {
    "m^3/s": "m3/s",
    "m": "m",
}

# Publisher operational availability codes documented in a5-portal-home.
# Recorded as source vocabulary only; never used to rank series quality or drop rows.
DATA_AVAILABILITY_CODES: dict[str, str] = {
    "H": "Historical series",
    "C": "Current operational series",
    "RT": "Real-time series",
    "NRT": "Near-real-time series",
    "S": "Simulated series",
    "H+S": "Historical and simulated series",
    "C+S": "Current and simulated series",
    "RT+S": "Real-time and simulated series",
    "NRT+S": "Near-real-time and simulated series",
    "N": "No observations available",
}

CATALOGUE_IDENTITY_EVIDENCE = "catalogue:ar_ina:source.station_product.series_associations"
CATALOGUE_VARIABLE_EVIDENCE = "catalogue:ar_ina:source.product.variables_unidades_procedimientos"
CATALOGUE_TEMPORAL_EVIDENCE = "catalogue:ar_ina:source.product.observation_temporal_semantics"
CATALOGUE_STAGE_REFERENCE_EVIDENCE = "catalogue:ar_ina:source.station.cero_ign_definition"

_ZERO_DURATION: dict[str, int] = {
    "years": 0,
    "months": 0,
    "days": 0,
    "hours": 0,
    "minutes": 0,
    "seconds": 0,
    "milliseconds": 0,
}


def _duration(**overrides: int) -> dict[str, int]:
    return {**_ZERO_DURATION, **overrides}


@dataclass(frozen=True, slots=True)
class SeriesProductSpec:
    """Verified INA Alerta5 observational series coordinate, unit, and temporal contract."""

    var_id: int
    proc_id: int
    var_code: str
    product_id: str
    observed_property: Literal["discharge", "stage"]
    expected_unit_id: int
    expected_unit_abrev: str
    canonical_unit: str
    expected_datatype: Literal["Average", "Continuous", "Minimum", "Maximum"]
    expected_time_support: dict[str, int]
    requires_midnight_cutoff: bool
    frequency: str | None
    statistic: str | None
    temporal_support: str | None
    timestamp_anchor: Literal["start", "measurement_time"]

    @property
    def native_id(self) -> str:
        return f"var_id={self.var_id};proc_id={self.proc_id}"

    @property
    def is_instantaneous(self) -> bool:
        return self.expected_time_support == _ZERO_DURATION


IN_SCOPE_SERIES_SPECS: tuple[SeriesProductSpec, ...] = (
    SeriesProductSpec(
        var_id=40,
        proc_id=1,
        var_code="Qmd",
        product_id="discharge_daily_mean",
        observed_property="discharge",
        expected_unit_id=10,
        expected_unit_abrev="m^3/s",
        canonical_unit="m3/s",
        expected_datatype="Average",
        expected_time_support=_duration(days=1),
        requires_midnight_cutoff=True,
        frequency="daily",
        statistic="mean",
        temporal_support="calendar_day",
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=4,
        proc_id=2,
        var_code="Q",
        product_id="discharge_instantaneous",
        observed_property="discharge",
        expected_unit_id=10,
        expected_unit_abrev="m^3/s",
        canonical_unit="m3/s",
        expected_datatype="Continuous",
        expected_time_support=_duration(),
        requires_midnight_cutoff=False,
        frequency=None,
        statistic="instantaneous",
        temporal_support="instantaneous",
        timestamp_anchor="measurement_time",
    ),
    SeriesProductSpec(
        var_id=48,
        proc_id=1,
        var_code="Qmm",
        product_id="discharge_monthly_mean",
        observed_property="discharge",
        expected_unit_id=10,
        expected_unit_abrev="m^3/s",
        canonical_unit="m3/s",
        expected_datatype="Average",
        expected_time_support=_duration(months=1),
        requires_midnight_cutoff=True,
        frequency="monthly",
        statistic="mean",
        temporal_support="calendar_month",
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=51,
        proc_id=1,
        var_code="Qmmin",
        product_id="discharge_monthly_min",
        observed_property="discharge",
        expected_unit_id=10,
        expected_unit_abrev="m^3/s",
        canonical_unit="m3/s",
        expected_datatype="Minimum",
        expected_time_support=_duration(months=1),
        requires_midnight_cutoff=True,
        frequency="monthly",
        statistic="min",
        temporal_support="calendar_month",
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=52,
        proc_id=1,
        var_code="Qmmax",
        product_id="discharge_monthly_max",
        observed_property="discharge",
        expected_unit_id=10,
        expected_unit_abrev="m^3/s",
        canonical_unit="m3/s",
        expected_datatype="Maximum",
        expected_time_support=_duration(months=1),
        requires_midnight_cutoff=True,
        frequency="monthly",
        statistic="max",
        temporal_support="calendar_month",
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=39,
        proc_id=1,
        var_code="Hmd",
        product_id="stage_daily_mean",
        observed_property="stage",
        expected_unit_id=11,
        expected_unit_abrev="m",
        canonical_unit="m",
        expected_datatype="Average",
        expected_time_support=_duration(days=1),
        requires_midnight_cutoff=True,
        frequency="daily",
        statistic="mean",
        temporal_support="calendar_day",
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=2,
        proc_id=1,
        var_code="H",
        product_id="stage_instantaneous",
        observed_property="stage",
        expected_unit_id=11,
        expected_unit_abrev="m",
        canonical_unit="m",
        expected_datatype="Continuous",
        expected_time_support=_duration(),
        requires_midnight_cutoff=False,
        frequency=None,
        statistic="instantaneous",
        temporal_support="instantaneous",
        timestamp_anchor="measurement_time",
    ),
    SeriesProductSpec(
        var_id=85,
        proc_id=1,
        var_code="H1h",
        product_id="stage_hourly",
        observed_property="stage",
        expected_unit_id=11,
        expected_unit_abrev="m",
        canonical_unit="m",
        expected_datatype="Continuous",
        expected_time_support=_duration(hours=1),
        requires_midnight_cutoff=False,
        frequency="hourly",
        statistic=None,
        temporal_support=None,
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=101,
        proc_id=1,
        var_code="Hm4h",
        product_id="stage_4hourly",
        observed_property="stage",
        expected_unit_id=11,
        expected_unit_abrev="m",
        canonical_unit="m",
        expected_datatype="Continuous",
        expected_time_support=_duration(hours=4),
        requires_midnight_cutoff=False,
        frequency=None,
        statistic=None,
        temporal_support=None,
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=67,
        proc_id=1,
        var_code="Hms",
        product_id="stage_weekly_mean",
        observed_property="stage",
        expected_unit_id=11,
        expected_unit_abrev="m",
        canonical_unit="m",
        expected_datatype="Average",
        expected_time_support=_duration(days=7),
        requires_midnight_cutoff=True,
        frequency=None,
        statistic="mean",
        temporal_support="interval",
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=33,
        proc_id=1,
        var_code="Hmm",
        product_id="stage_monthly_mean",
        observed_property="stage",
        expected_unit_id=11,
        expected_unit_abrev="m",
        canonical_unit="m",
        expected_datatype="Average",
        expected_time_support=_duration(months=1),
        requires_midnight_cutoff=True,
        frequency="monthly",
        statistic="mean",
        temporal_support="calendar_month",
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=49,
        proc_id=1,
        var_code="Hmmin",
        product_id="stage_monthly_min",
        observed_property="stage",
        expected_unit_id=11,
        expected_unit_abrev="m",
        canonical_unit="m",
        expected_datatype="Minimum",
        expected_time_support=_duration(months=1),
        requires_midnight_cutoff=True,
        frequency="monthly",
        statistic="min",
        temporal_support="calendar_month",
        timestamp_anchor="start",
    ),
    SeriesProductSpec(
        var_id=50,
        proc_id=1,
        var_code="Hmmax",
        product_id="stage_monthly_max",
        observed_property="stage",
        expected_unit_id=11,
        expected_unit_abrev="m",
        canonical_unit="m",
        expected_datatype="Maximum",
        expected_time_support=_duration(months=1),
        requires_midnight_cutoff=True,
        frequency="monthly",
        statistic="max",
        temporal_support="calendar_month",
        timestamp_anchor="start",
    ),
)

SPECS_BY_VAR_ID: dict[int, SeriesProductSpec] = {spec.var_id: spec for spec in IN_SCOPE_SERIES_SPECS}
SPECS_BY_PRODUCT_ID: dict[str, SeriesProductSpec] = {spec.product_id: spec for spec in IN_SCOPE_SERIES_SPECS}


def _as_json_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, object]", value)


def _extract_rows_list(payload: object, label: str) -> list[dict[str, object]]:
    obj = _as_json_object(payload)
    raw_rows = obj["rows"] if obj is not None and "rows" in obj else payload
    if not isinstance(raw_rows, list) or not raw_rows:
        raise FatalContractError(f"INA {label} dictionary must contain a non-empty JSON rows array")
    if any(not isinstance(item, dict) for item in raw_rows):
        raise FatalContractError(f"INA {label} dictionary entries must be JSON objects")
    return cast("list[dict[str, object]]", raw_rows)


def _normalize_series_id(published_series_id: int | str) -> str:
    if isinstance(published_series_id, bool):
        raise FatalContractError("INA published series_id cannot be a boolean")
    if isinstance(published_series_id, int):
        if published_series_id <= 0:
            raise FatalContractError("INA published series_id must be a positive integer")
        return str(published_series_id)
    if isinstance(published_series_id, str):
        stripped = published_series_id.strip()
        if not stripped or not stripped.isascii() or not stripped.isdigit():
            raise FatalContractError(
                f"INA published series_id must be a positive integer string: {published_series_id!r}"
            )
        numeric = int(stripped)
        if numeric <= 0 or str(numeric) != stripped:
            raise FatalContractError(
                f"INA published series_id must be canonical positive digits: {published_series_id!r}"
            )
        return stripped
    raise FatalContractError(f"Unsupported INA published series_id type: {type(published_series_id).__name__}")


def product_physical_facts(
    product_id: str,
    *,
    source_unit: str | None = None,
    variable_evidence: str = CATALOGUE_VARIABLE_EVIDENCE,
    temporal_evidence: str = CATALOGUE_TEMPORAL_EVIDENCE,
    stage_reference_evidence: str = CATALOGUE_STAGE_REFERENCE_EVIDENCE,
) -> PhysicalFacts:
    """Build established physical and temporal facts for one INA Alerta5 product route.

    Pre-2009 Argentina Daylight Saving Time shifts civil midnight in
    ``America/Argentina/Buenos_Aires`` between ``03:00:00.000Z`` (``UTC-03:00``)
    and ``02:00:00.000Z`` (``UTC-02:00``), producing ``23 h`` spring-forward and
    ``25 h`` fall-back intervals. Accordingly, ``time_zone`` is ``"UTC"`` with
    ``ClippingAxis.SOURCE_TIMESTAMP`` while ``day_definition`` remains
    ``not_established`` rather than asserting a false fixed UTC offset.
    """
    spec = SPECS_BY_PRODUCT_ID.get(product_id)
    if spec is None:
        raise FatalContractError(f"Unsupported INA Alerta5 product_id: {product_id!r}")
    resolved_unit = spec.expected_unit_abrev if source_unit is None else source_unit.strip()
    normalized = UNITS.get(resolved_unit)
    if resolved_unit != spec.expected_unit_abrev or normalized != spec.canonical_unit:
        raise FatalContractError(
            f"Unsupported INA Alerta5 unit {source_unit!r} for {product_id}; expected {spec.expected_unit_abrev!r}"
        )

    facts = PhysicalFacts(
        facts_id="pending",
        quantity=known(spec.observed_property, variable_evidence),
        source_unit=known(resolved_unit, variable_evidence),
        normalized_unit=normalized,
        frequency=known(spec.frequency, temporal_evidence) if spec.frequency is not None else EvidenceFact(),
        statistic=known(spec.statistic, temporal_evidence) if spec.statistic is not None else EvidenceFact(),
        temporal_support=(
            known(spec.temporal_support, temporal_evidence) if spec.temporal_support is not None else EvidenceFact()
        ),
        day_definition=EvidenceFact(),
        timestamp_anchor=known(spec.timestamp_anchor, temporal_evidence),
        time_zone=known("UTC", temporal_evidence),
        vertical_reference=(
            known("gauge_zero", stage_reference_evidence) if spec.observed_property == "stage" else EvidenceFact()
        ),
        vertical_datum=EvidenceFact(),
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    )
    facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
    decision = admission(facts)
    if decision.status != "supported":
        raise FatalContractError(f"INA Alerta5 product {product_id} failed dimensional admission: {decision.reason}")
    return facts


def route_product_facts(product_id: str) -> PhysicalFacts:
    """Return canonical route-level physical facts for ``products.parquet`` projection."""
    return product_physical_facts(product_id)


def source_series(
    station_id: str,
    product_id: str,
    *,
    published_series_id: int | str,
    source_unit: str | None = None,
    origin: Literal["catalogue", "response"] = "catalogue",
    identity_evidence: str = CATALOGUE_IDENTITY_EVIDENCE,
    variable_evidence: str = CATALOGUE_VARIABLE_EVIDENCE,
    temporal_evidence: str = CATALOGUE_TEMPORAL_EVIDENCE,
    stage_reference_evidence: str = CATALOGUE_STAGE_REFERENCE_EVIDENCE,
) -> SourceSeries:
    """Construct one concrete INA Alerta5 ``SourceSeries`` identified by ``Serie.id``."""
    clean_station = station_id.strip()
    if not clean_station or clean_station != station_id:
        raise FatalContractError(f"INA station_id must be a nonblank canonical string: {station_id!r}")
    if not identity_evidence:
        raise FatalContractError("INA source_series requires nonblank identity_evidence")
    pub_id = _normalize_series_id(published_series_id)
    facts = product_physical_facts(
        product_id,
        source_unit=source_unit,
        variable_evidence=variable_evidence,
        temporal_evidence=temporal_evidence,
        stage_reference_evidence=stage_reference_evidence,
    )
    return SourceSeries(
        series_id=stable_id("ar_ina", clean_station, NAMESPACE, pub_id),
        provider_id="ar_ina",
        station_id=clean_station,
        product_id=product_id,
        identity=SourceIdentity(
            namespace=NAMESPACE,
            published_id=pub_id,
            origin=origin,
            evidence=(identity_evidence,),
        ),
        variant=pub_id,
        facts=(facts,),
    )


def validate_unidades_dictionary(payload: object) -> None:
    """Verify INA Alerta5 ``/obs/unidades`` unit definitions for discharge and stage."""
    rows = _extract_rows_list(payload, "unidades")
    by_id: dict[int, dict[str, object]] = {}
    for row in rows:
        uid = row.get("id")
        if isinstance(uid, int) and not isinstance(uid, bool):
            by_id[uid] = row
    expected = {
        10: ("m^3/s", "Flow"),
        11: ("m", "Length"),
    }
    for uid, (abrev, units_type) in expected.items():
        entry = by_id.get(uid)
        if entry is None:
            raise FatalContractError(f"INA unidades dictionary lacks required unit_id={uid}")
        if entry.get("abrev") != abrev or entry.get("UnitsType") != units_type:
            raise FatalContractError(f"INA unidades entry for unit_id={uid} drifted: {entry!r}")


def validate_procedimientos_dictionary(payload: object) -> None:
    """Verify INA Alerta5 ``/obs/procedimientos`` observational versus simulated procedures."""
    rows = _extract_rows_list(payload, "procedimientos")
    by_id: dict[int, dict[str, object]] = {}
    for row in rows:
        pid = row.get("id")
        if isinstance(pid, int) and not isinstance(pid, bool):
            by_id[pid] = row
    if by_id.get(1, {}).get("abrev") != "medicion" or by_id.get(2, {}).get("abrev") != "curva":
        raise FatalContractError("INA procedimientos dictionary drifted on observational procedures 1 or 2")
    missing_excluded = EXCLUDED_PROCEDURES - set(by_id)
    if missing_excluded:
        raise FatalContractError(
            f"INA procedimientos dictionary lacks expected non-observational IDs: {sorted(missing_excluded)}"
        )


def validate_variables_dictionary(payload: object) -> None:
    """Verify all 13 in-scope INA Alerta5 variables against ``/obs/variables``."""
    rows = _extract_rows_list(payload, "variables")
    by_id: dict[int, dict[str, object]] = {}
    for row in rows:
        vid = row.get("id")
        if isinstance(vid, int) and not isinstance(vid, bool):
            by_id[vid] = row
    for spec in IN_SCOPE_SERIES_SPECS:
        entry = by_id.get(spec.var_id)
        if entry is None:
            raise FatalContractError(f"INA variables dictionary lacks in-scope var_id={spec.var_id}")
        if entry.get("var") != spec.var_code:
            raise FatalContractError(
                f"INA var_id={spec.var_id} code drifted: expected {spec.var_code!r}, got {entry.get('var')!r}"
            )
        if entry.get("datatype") != spec.expected_datatype:
            raise FatalContractError(
                f"INA var_id={spec.var_id} datatype drifted: expected {spec.expected_datatype!r}, got {entry.get('datatype')!r}"
            )
        if entry.get("timeSupport") != spec.expected_time_support:
            raise FatalContractError(
                f"INA var_id={spec.var_id} timeSupport drifted: expected {spec.expected_time_support!r}, got {entry.get('timeSupport')!r}"
            )
        if str(entry.get("def_unit_id")) != str(spec.expected_unit_id):
            raise FatalContractError(
                f"INA var_id={spec.var_id} def_unit_id drifted: expected {spec.expected_unit_id}, got {entry.get('def_unit_id')!r}"
            )
        if entry.get("SampleMedium") != "Surface Water" or entry.get("GeneralCategory") != "Hydrology":
            raise FatalContractError(f"INA var_id={spec.var_id} hydrology medium drifted: {entry!r}")


def validate_series_record_metadata(
    raw_series: Mapping[str, object],
    spec: SeriesProductSpec,
    *,
    series_id: int,
    proc_id: int,
) -> str:
    """Validate embedded ``var``, ``procedimiento``, ``unidades``, and ``data_availability`` on one series row."""
    if proc_id != spec.proc_id:
        raise FatalContractError(
            f"Unexpected observational procedure {proc_id} on INA var_id={spec.var_id} (series {series_id})"
        )
    var_obj = _as_json_object(raw_series.get("var"))
    if var_obj is None or var_obj.get("id") != spec.var_id:
        raise FatalContractError(f"INA series {series_id} disagrees with requested var_id={spec.var_id}")
    if "datatype" in var_obj and var_obj.get("datatype") != spec.expected_datatype:
        raise FatalContractError(
            f"INA series {series_id} datatype {var_obj.get('datatype')!r} contradicts {spec.expected_datatype!r}"
        )
    if "timeSupport" in var_obj and var_obj.get("timeSupport") != spec.expected_time_support:
        raise FatalContractError(
            f"INA series {series_id} timeSupport {var_obj.get('timeSupport')!r} contradicts {spec.expected_time_support!r}"
        )
    if "def_hora_corte" in var_obj:
        cutoff = var_obj.get("def_hora_corte")
        expected_cutoff = _ZERO_DURATION if spec.requires_midnight_cutoff else None
        if cutoff != expected_cutoff:
            raise FatalContractError(
                f"INA series {series_id} def_hora_corte {cutoff!r} contradicts expected {expected_cutoff!r}"
            )

    unit_obj = _as_json_object(raw_series.get("unidades"))
    if unit_obj is None:
        raise FatalContractError(f"INA series {series_id} lacks unidades object")
    unit_id = unit_obj.get("id")
    unit_abrev = unit_obj.get("abrev")
    if unit_id != spec.expected_unit_id or unit_abrev != spec.expected_unit_abrev:
        raise FatalContractError(
            f"Unsupported INA unit ({unit_id!r}, {unit_abrev!r}) on series {series_id} for var_id={spec.var_id}"
        )

    date_range = _as_json_object(raw_series.get("date_range"))
    if (
        date_range is not None
        and (avail := date_range.get("data_availability")) is not None
        and (not isinstance(avail, str) or avail not in DATA_AVAILABILITY_CODES)
    ):
        raise FatalContractError(f"Unrecognized INA data_availability code {avail!r} on series {series_id}")
    return str(unit_abrev)


def _parse_utc_instant(raw: object, field_name: str, *, series_id: int) -> datetime:
    if not isinstance(raw, str) or not raw.endswith("Z"):
        raise FatalContractError(
            f"INA series {series_id} observation {field_name} must be an explicit UTC (...Z) string"
        )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FatalContractError(
            f"INA series {series_id} observation {field_name} is invalid ISO-8601: {raw!r}"
        ) from exc
    if parsed.tzinfo != UTC:
        raise FatalContractError(f"INA series {series_id} observation {field_name} is not UTC: {raw!r}")
    return parsed


def validate_observation_row(
    raw_row: object,
    spec: SeriesProductSpec,
    *,
    expected_series_id: int,
) -> tuple[datetime, datetime, float | None]:
    """Validate one ``/obs/puntual/series/{series_id}/observaciones`` JSON row.

    Preserves ``valor: null`` interval gaps as ``None``, preserves negative
    gauge-zero stage and ``0.0`` discharge as finite floats, and rejects series
    identity mismatches, server-converted ``unit_id`` overrides, non-UTC
    timestamps, or reversed interval bounds.
    """
    row = _as_json_object(raw_row)
    if row is None:
        raise FatalContractError(f"INA observation row on series {expected_series_id} must be a JSON object")
    row_series_id = row.get("series_id")
    if isinstance(row_series_id, bool) or row_series_id != expected_series_id:
        raise FatalContractError(
            f"INA observation row series_id {row_series_id!r} disagrees with requested series {expected_series_id}"
        )
    row_unit_id = row.get("unit_id")
    if row_unit_id is not None and (isinstance(row_unit_id, bool) or row_unit_id != spec.expected_unit_id):
        raise FatalContractError(
            f"INA observation row unit_id {row_unit_id!r} contradicts native unit_id={spec.expected_unit_id}"
        )

    start = _parse_utc_instant(row.get("timestart"), "timestart", series_id=expected_series_id)
    end = _parse_utc_instant(row.get("timeend"), "timeend", series_id=expected_series_id)
    if spec.is_instantaneous:
        if start != end:
            raise FatalContractError(
                f"INA instantaneous series {expected_series_id} (var_id={spec.var_id}) requires timestart == timeend"
            )
    elif start >= end:
        raise FatalContractError(
            f"INA interval series {expected_series_id} (var_id={spec.var_id}) requires timestart < timeend"
        )

    raw_valor = row.get("valor")
    if raw_valor is None:
        return start, end, None
    if isinstance(raw_valor, bool) or not isinstance(raw_valor, int | float):
        raise FatalContractError(
            f"INA observation valor on series {expected_series_id} must be a finite number or null: {raw_valor!r}"
        )
    try:
        numeric = float(raw_valor)
    except OverflowError as error:
        raise FatalContractError(
            f"INA observation valor on series {expected_series_id} overflows Float64: {raw_valor!r}"
        ) from error
    if not math.isfinite(numeric):
        raise FatalContractError(f"INA observation valor on series {expected_series_id} is non-finite: {raw_valor!r}")
    return start, end, numeric
