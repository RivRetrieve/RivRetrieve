"""NRFA API series identities, evidence-backed physical facts, and payload decoders."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import Literal, cast

import polars as pl

from rivretrieve._internal.engine import RowsSchema
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.uk_nrfa.annotations import (
    AMAX_DOC_URL,
    API_HELP_URL,
    UK_NRFA_AMAX_REJECTION_SCHEMA,
    UK_NRFA_OBSERVATIONS_SCHEMA,
    UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
    UK_NRFA_SERIES_METADATA_SCHEMA,
)
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    ObservationAnnotationTable,
    SeriesAnnotationTable,
)
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

NRFA_IDENTITY_NAMESPACE = "uk_nrfa/data-type"

DERIVED_DATA_URL = "https://nrfa.ceh.ac.uk/data/about-data/daily-flow-data/derived-data-series"
GDF_DOC_URL = "https://nrfa.ceh.ac.uk/data/about-data/daily-flow-data/gauged-daily-flow-data"
GLOSSARY_URL = "https://nrfa.ceh.ac.uk/help/nrfa-glossary"
HYDROMETRIC_INFO_URL = "https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/hydrometric-information"
NDF_DOC_URL = "https://nrfa.ceh.ac.uk/data/about-data/daily-flow-data/naturalised-flow-series"
POT_DOC_URL = "https://nrfa.ceh.ac.uk/data/about-data/peak-flow-data/data-types/peaks-over-threshold-pot"
RATINGS_DATUMS_URL = "https://nrfa.ceh.ac.uk/data/about-data/peak-flow-data/data-types/ratings-datums"

AMAX_PRODUCTS = frozenset({"amax-flow", "amax-stage"})
PEAK_REJECTED_PERIOD_PRODUCTS = frozenset({"amax-flow", "amax-stage", "pot-flow", "pot-stage"})

_YEAR_MONTH_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")
_DATETIME_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T\d{2}:\d{2}:\d{2}$")


@dataclass(frozen=True, slots=True)
class _ProductSpec:
    product_id: str
    data_type_name: str
    parameter: str
    source_unit: str
    measurement_type: str
    source_period: str
    quantity: Literal["discharge", "stage"]
    frequency: str | None
    frequency_evidence: str | None
    statistic: str | None
    statistic_evidence: str | None
    vertical_reference: str | None
    vertical_reference_evidence: str | None
    clipping_axis: ClippingAxis
    label_kind: Literal["date", "year_month", "datetime"]
    identity_evidence: tuple[str, ...]

    @property
    def expected_header(self) -> dict[str, str]:
        return {
            "id": self.product_id,
            "name": self.data_type_name,
            "parameter": self.parameter,
            "units": self.source_unit,
            "measurement-type": self.measurement_type,
            "period": self.source_period,
        }


_PRODUCT_SPECS: tuple[_ProductSpec, ...] = (
    _ProductSpec(
        product_id="gdf",
        data_type_name="Gauged Daily Flow",
        parameter="Flow",
        source_unit="m3/s",
        measurement_type="Mean",
        source_period="P1D",
        quantity="discharge",
        frequency="daily",
        frequency_evidence=GDF_DOC_URL,
        statistic="mean",
        statistic_evidence=GDF_DOC_URL,
        vertical_reference=None,
        vertical_reference_evidence=None,
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_kind="date",
        identity_evidence=(API_HELP_URL, GDF_DOC_URL),
    ),
    _ProductSpec(
        product_id="ndf",
        data_type_name="Naturalised Daily Flow",
        parameter="Flow",
        source_unit="m3/s",
        measurement_type="Mean",
        source_period="P1D",
        quantity="discharge",
        frequency="daily",
        frequency_evidence=NDF_DOC_URL,
        statistic="mean",
        statistic_evidence=NDF_DOC_URL,
        vertical_reference=None,
        vertical_reference_evidence=None,
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_kind="date",
        identity_evidence=(API_HELP_URL, NDF_DOC_URL, GDF_DOC_URL),
    ),
    _ProductSpec(
        product_id="gmf",
        data_type_name="Gauged Monthly Flow",
        parameter="Flow",
        source_unit="m3/s",
        measurement_type="Mean",
        source_period="P1M",
        quantity="discharge",
        frequency="monthly",
        frequency_evidence=DERIVED_DATA_URL,
        statistic="mean",
        statistic_evidence=DERIVED_DATA_URL,
        vertical_reference=None,
        vertical_reference_evidence=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_kind="year_month",
        identity_evidence=(API_HELP_URL, DERIVED_DATA_URL),
    ),
    _ProductSpec(
        product_id="nmf",
        data_type_name="Naturalised Monthly Flow",
        parameter="Flow",
        source_unit="m3/s",
        measurement_type="Mean",
        source_period="P1M",
        quantity="discharge",
        frequency="monthly",
        frequency_evidence=DERIVED_DATA_URL,
        statistic="mean",
        statistic_evidence=DERIVED_DATA_URL,
        vertical_reference=None,
        vertical_reference_evidence=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_kind="year_month",
        identity_evidence=(API_HELP_URL, NDF_DOC_URL, DERIVED_DATA_URL),
    ),
    _ProductSpec(
        product_id="gauging-flow",
        data_type_name="Gauging - Flow",
        parameter="Flow",
        source_unit="m3/s",
        measurement_type="Measured",
        source_period="PT1S",
        quantity="discharge",
        frequency=None,
        frequency_evidence=None,
        statistic=None,
        statistic_evidence=None,
        vertical_reference=None,
        vertical_reference_evidence=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_kind="datetime",
        identity_evidence=(API_HELP_URL, GLOSSARY_URL),
    ),
    _ProductSpec(
        product_id="gauging-stage",
        data_type_name="Gauging - Stage",
        parameter="Stage",
        source_unit="m",
        measurement_type="Measured",
        source_period="PT1S",
        quantity="stage",
        frequency=None,
        frequency_evidence=None,
        statistic=None,
        statistic_evidence=None,
        vertical_reference="gauge_zero",
        vertical_reference_evidence=HYDROMETRIC_INFO_URL,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_kind="datetime",
        identity_evidence=(API_HELP_URL, HYDROMETRIC_INFO_URL, GLOSSARY_URL),
    ),
    _ProductSpec(
        product_id="amax-flow",
        data_type_name="Annual Maxima - Flow",
        parameter="Flow",
        source_unit="m3/s",
        measurement_type="Maximum",
        source_period="PT15M",
        quantity="discharge",
        frequency=None,
        frequency_evidence=None,
        statistic="max",
        statistic_evidence=AMAX_DOC_URL,
        vertical_reference=None,
        vertical_reference_evidence=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_kind="datetime",
        identity_evidence=(API_HELP_URL, AMAX_DOC_URL),
    ),
    _ProductSpec(
        product_id="amax-stage",
        data_type_name="Annual Maxima - Stage",
        parameter="Stage",
        source_unit="m",
        measurement_type="Maximum",
        source_period="PT15M",
        quantity="stage",
        frequency=None,
        frequency_evidence=None,
        statistic=None,
        statistic_evidence=None,
        vertical_reference="gauge_zero",
        vertical_reference_evidence=RATINGS_DATUMS_URL,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_kind="datetime",
        identity_evidence=(API_HELP_URL, AMAX_DOC_URL, RATINGS_DATUMS_URL),
    ),
    _ProductSpec(
        product_id="pot-flow",
        data_type_name="Peaks Over Threshold - Flow",
        parameter="Flow",
        source_unit="m3/s",
        measurement_type="Measured",
        source_period="PT15M",
        quantity="discharge",
        frequency=None,
        frequency_evidence=None,
        statistic=None,
        statistic_evidence=None,
        vertical_reference=None,
        vertical_reference_evidence=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_kind="datetime",
        identity_evidence=(API_HELP_URL, POT_DOC_URL),
    ),
    _ProductSpec(
        product_id="pot-stage",
        data_type_name="Peaks Over Threshold - Stage",
        parameter="Stage",
        source_unit="m",
        measurement_type="Measured",
        source_period="PT15M",
        quantity="stage",
        frequency=None,
        frequency_evidence=None,
        statistic=None,
        statistic_evidence=None,
        vertical_reference="gauge_zero",
        vertical_reference_evidence=RATINGS_DATUMS_URL,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_kind="datetime",
        identity_evidence=(API_HELP_URL, POT_DOC_URL, RATINGS_DATUMS_URL),
    ),
)

_SPECS_BY_ID: dict[str, _ProductSpec] = {spec.product_id: spec for spec in _PRODUCT_SPECS}
PRODUCT_IDS: tuple[str, ...] = tuple(spec.product_id for spec in _PRODUCT_SPECS)


def _require_spec(product_id: str) -> _ProductSpec:
    spec = _SPECS_BY_ID.get(product_id)
    if spec is None:
        raise UnsupportedSourceStructureError(f"Unsupported NRFA data-type id: {product_id!r}")
    return spec


@cache
def product_facts() -> dict[str, PhysicalFacts]:
    """Return immutable, evidence-backed physical facts for all ten NRFA products."""
    resolved: dict[str, PhysicalFacts] = {}
    for spec in _PRODUCT_SPECS:
        preliminary = PhysicalFacts(
            facts_id=spec.product_id,
            quantity=known(spec.quantity, API_HELP_URL),
            source_unit=known(spec.source_unit, API_HELP_URL),
            normalized_unit=spec.source_unit,
            frequency=(
                known(spec.frequency, spec.frequency_evidence)
                if spec.frequency is not None and spec.frequency_evidence is not None
                else EvidenceFact()
            ),
            statistic=(
                known(spec.statistic, spec.statistic_evidence)
                if spec.statistic is not None and spec.statistic_evidence is not None
                else EvidenceFact()
            ),
            vertical_reference=(
                known(spec.vertical_reference, spec.vertical_reference_evidence)
                if spec.vertical_reference is not None and spec.vertical_reference_evidence is not None
                else EvidenceFact()
            ),
            clipping_axis=spec.clipping_axis,
        )
        resolved[spec.product_id] = preliminary.model_copy(
            update={"facts_id": stable_id(preliminary.model_dump_json(exclude={"facts_id"}))}
        )
    return resolved


def series_identity(
    product_id: str,
    *,
    origin: Literal["catalogue", "response", "mapping"] = "mapping",
    description: str | None = None,
) -> SourceIdentity:
    """Build the canonical ``uk_nrfa/data-type`` identity for an NRFA API product."""
    spec = _require_spec(product_id)
    return SourceIdentity(
        namespace=NRFA_IDENTITY_NAMESPACE,
        published_id=product_id,
        origin=origin,
        description=description if description is not None else spec.data_type_name,
        evidence=spec.identity_evidence,
    )


def source_series(
    station_id: str,
    product_id: str,
    *,
    origin: Literal["catalogue", "response", "mapping"] = "response",
) -> SourceSeries:
    """Construct the ``SourceSeries`` definition for an NRFA station and product."""
    if not isinstance(station_id, str) or not station_id:
        raise UnsupportedSourceStructureError("NRFA source_series requires a non-empty station_id")
    _require_spec(product_id)
    facts = product_facts()[product_id]
    return SourceSeries(
        series_id=stable_id("uk_nrfa", station_id, NRFA_IDENTITY_NAMESPACE, product_id),
        provider_id="uk_nrfa",
        station_id=station_id,
        product_id=product_id,
        identity=series_identity(product_id, origin=origin),
        facts=(facts,),
    )


def _parse_label(label: object, label_kind: Literal["date", "year_month", "datetime"], product_id: str) -> datetime:
    if not isinstance(label, str):
        raise UnsupportedSourceStructureError(f"NRFA {product_id!r} label must be a string, got {type(label).__name__}")
    try:
        if label_kind == "year_month":
            if _YEAR_MONTH_RE.fullmatch(label) is None:
                raise UnsupportedSourceStructureError(f"Invalid NRFA monthly label {label!r} for {product_id!r}")
            year_str, month_str = label.split("-", 1)
            return datetime(int(year_str), int(month_str), 1, 0, 0, 0)
        if label_kind == "date":
            if _DATE_RE.fullmatch(label) is None:
                raise UnsupportedSourceStructureError(f"Invalid NRFA daily label {label!r} for {product_id!r}")
            return datetime.strptime(label, "%Y-%m-%d")
        if _DATETIME_RE.fullmatch(label) is None:
            raise UnsupportedSourceStructureError(f"Invalid NRFA timestamp label {label!r} for {product_id!r}")
        return datetime.strptime(label, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise UnsupportedSourceStructureError(f"Invalid NRFA calendar label {label!r} for {product_id!r}") from exc


def _parse_entry(entry: object, product_id: str) -> tuple[float | None, str | None]:
    if isinstance(entry, list):
        if len(entry) != 2 or not isinstance(entry[1], str) or not entry[1]:
            raise UnsupportedSourceStructureError(f"Malformed NRFA flagged data-stream entry for {product_id!r}")
        raw_value, flag = entry[0], entry[1]
    else:
        raw_value, flag = entry, None

    if raw_value is None:
        return None, flag
    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        raise UnsupportedSourceStructureError(f"NRFA {product_id!r} value must be numeric or null")
    numeric = float(raw_value)
    if not math.isfinite(numeric):
        raise UnsupportedSourceStructureError(f"NRFA {product_id!r} value must be finite")
    return numeric, flag


def decode_time_series_response(
    payload: Mapping[str, object],
    *,
    expected_station_id: str | None = None,
    expected_product_id: str | None = None,
) -> tuple[SourceSeries, pl.DataFrame, AnnotationBundle]:
    """Parse one NRFA ``/time-series`` JSON response into rows and annotations."""
    if not isinstance(payload, Mapping):
        raise UnsupportedSourceStructureError("NRFA time-series payload must be a JSON object")
    raw_data_type = payload.get("data-type")
    if not isinstance(raw_data_type, Mapping):
        raise UnsupportedSourceStructureError("NRFA time-series payload requires a data-type object")
    data_type = cast("Mapping[str, object]", raw_data_type)
    product_id = data_type.get("id")
    if not isinstance(product_id, str):
        raise UnsupportedSourceStructureError("NRFA data-type.id must be a string")
    if expected_product_id is not None and product_id != expected_product_id:
        raise UnsupportedSourceStructureError(
            f"NRFA response data-type {product_id!r} differs from expected {expected_product_id!r}"
        )
    spec = _require_spec(product_id)
    if dict(data_type) != spec.expected_header:
        raise UnsupportedSourceStructureError(
            f"NRFA data-type header differs from verified metadata for {product_id!r}"
        )

    raw_station = payload.get("station")
    if not isinstance(raw_station, Mapping):
        raise UnsupportedSourceStructureError("NRFA time-series payload requires non-negative integer station.id")
    station = cast("Mapping[str, object]", raw_station)
    raw_station_id = station.get("id")
    if type(raw_station_id) is not int or raw_station_id < 0:
        raise UnsupportedSourceStructureError("NRFA time-series payload requires non-negative integer station.id")
    station_id = str(raw_station_id)
    if expected_station_id is not None and station_id != expected_station_id:
        raise UnsupportedSourceStructureError(
            f"NRFA response station.id {station_id!r} differs from expected {expected_station_id!r}"
        )

    stream = payload.get("data-stream")
    if not isinstance(stream, list) or len(stream) % 2 != 0:
        raise UnsupportedSourceStructureError("NRFA dates=true data-stream must be an even-length list")

    defined = source_series(station_id, product_id, origin="response")
    facts = defined.facts[0]

    times: list[datetime] = []
    values: list[float | None] = []
    labels: list[str] = []
    flags: list[str | None] = []
    for index in range(0, len(stream), 2):
        raw_label = stream[index]
        raw_entry = stream[index + 1]
        timestamp = _parse_label(raw_label, spec.label_kind, product_id)
        value, flag = _parse_entry(raw_entry, product_id)
        times.append(timestamp)
        values.append(value)
        labels.append(str(raw_label))
        flags.append(flag)

    row_count = len(times)
    rows = pl.DataFrame(
        {
            "station_id": [station_id] * row_count,
            "product_id": [product_id] * row_count,
            "time": times,
            "value": values,
            "time_zone": ["unknown"] * row_count,
            "series_id": [defined.series_id] * row_count,
            "facts_id": [facts.facts_id] * row_count,
            "source_unit": [spec.source_unit] * row_count,
        },
        schema=RowsSchema.polars_schema,
    )

    series_meta_table = SeriesAnnotationTable.from_rows(
        schema=UK_NRFA_SERIES_METADATA_SCHEMA,
        rows=pl.DataFrame(
            {
                "series_id": [defined.series_id],
                "data_type_name": [spec.data_type_name],
                "measurement_type": [spec.measurement_type],
                "source_period": [spec.source_period],
            },
            schema={"series_id": pl.String, **UK_NRFA_SERIES_METADATA_SCHEMA.polars_schema()},
        ),
    )
    observation_tables: dict[str, ObservationAnnotationTable] = {}
    if row_count > 0:
        observation_tables[UK_NRFA_OBSERVATIONS_SCHEMA.schema_id] = ObservationAnnotationTable.from_rows(
            schema=UK_NRFA_OBSERVATIONS_SCHEMA,
            rows=pl.DataFrame(
                {
                    "series_id": [defined.series_id] * row_count,
                    "facts_id": [facts.facts_id] * row_count,
                    "station_id": [station_id] * row_count,
                    "product_id": [product_id] * row_count,
                    "time": times,
                    "time_zone": ["unknown"] * row_count,
                    "measured": [True] * row_count,
                    "source_label": labels,
                    "flag": flags,
                },
                schema={
                    "series_id": pl.String,
                    "facts_id": pl.String,
                    "station_id": pl.String,
                    "product_id": pl.String,
                    "time": pl.Datetime("us"),
                    "time_zone": pl.String,
                    "measured": pl.Boolean,
                    **UK_NRFA_OBSERVATIONS_SCHEMA.polars_schema(),
                },
            ),
            measurement_indices=tuple(range(row_count)),
        )

    bundle = AnnotationBundle(
        observation_tables=observation_tables,
        series_tables={UK_NRFA_SERIES_METADATA_SCHEMA.schema_id: series_meta_table},
    )
    return defined, rows, bundle


def _parse_rejected_amax_years(raw: object, station_id: str) -> list[int] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"excluded-years"}:
        raise UnsupportedSourceStructureError(f"Malformed peak-flow-rejected-amax-years for station {station_id}")
    raw_map = cast("Mapping[str, object]", raw)
    excluded = raw_map["excluded-years"]
    if not isinstance(excluded, list) or any(
        type(item) is not int or not (-(1 << 63) <= item < (1 << 63)) for item in excluded
    ):
        raise UnsupportedSourceStructureError(f"excluded-years must be a list of Int64 integers for {station_id}")
    return cast("list[int]", list(excluded))


def _parse_rejected_periods(raw: object, station_id: str) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"rejected-periods"}:
        raise UnsupportedSourceStructureError(f"Malformed peak-flow-rejected-periods for station {station_id}")
    raw_map = cast("Mapping[str, object]", raw)
    rejected = raw_map["rejected-periods"]
    if not isinstance(rejected, list) or any(not isinstance(item, str) or not item for item in rejected):
        raise UnsupportedSourceStructureError(f"rejected-periods must be non-empty strings for {station_id}")
    return cast("list[str]", list(rejected))


def build_peak_rejection_annotations(
    station_row: Mapping[str, object],
    *,
    series: Sequence[SourceSeries],
) -> dict[str, SeriesAnnotationTable]:
    """Attach station peak-flow rejection lists strictly to applicable NRFA peak series."""
    if not isinstance(station_row, Mapping):
        raise UnsupportedSourceStructureError("NRFA station_row must be a mapping")
    raw_station_id = station_row.get("id")
    if type(raw_station_id) is not int or raw_station_id < 0:
        raise UnsupportedSourceStructureError("NRFA station_row requires non-negative integer id")
    station_id = str(raw_station_id)
    if "peak-flow-rejected-amax-years" not in station_row or "peak-flow-rejected-periods" not in station_row:
        raise UnsupportedSourceStructureError(f"NRFA station_row for {station_id} lacks peak-flow rejection fields")

    excluded_years = _parse_rejected_amax_years(station_row["peak-flow-rejected-amax-years"], station_id)
    rejected_periods = _parse_rejected_periods(station_row["peak-flow-rejected-periods"], station_id)

    unique_series = list(
        {
            item.series_id: item for item in series if item.provider_id == "uk_nrfa" and item.station_id == station_id
        }.values()
    )
    tables: dict[str, SeriesAnnotationTable] = {}

    amax_series = [item for item in unique_series if item.product_id in AMAX_PRODUCTS]
    if amax_series:
        tables[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id] = SeriesAnnotationTable.from_rows(
            schema=UK_NRFA_AMAX_REJECTION_SCHEMA,
            rows=pl.DataFrame(
                {
                    "series_id": [item.series_id for item in amax_series],
                    "rejected_amax_years": [excluded_years] * len(amax_series),
                },
                schema={"series_id": pl.String, **UK_NRFA_AMAX_REJECTION_SCHEMA.polars_schema()},
            ),
        )

    peak_series = [item for item in unique_series if item.product_id in PEAK_REJECTED_PERIOD_PRODUCTS]
    if peak_series:
        tables[UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id] = SeriesAnnotationTable.from_rows(
            schema=UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
            rows=pl.DataFrame(
                {
                    "series_id": [item.series_id for item in peak_series],
                    "rejected_periods": [rejected_periods] * len(peak_series),
                },
                schema={"series_id": pl.String, **UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.polars_schema()},
            ),
        )

    return tables


__all__ = (
    "AMAX_DOC_URL",
    "AMAX_PRODUCTS",
    "API_HELP_URL",
    "DERIVED_DATA_URL",
    "GDF_DOC_URL",
    "GLOSSARY_URL",
    "HYDROMETRIC_INFO_URL",
    "NDF_DOC_URL",
    "NRFA_IDENTITY_NAMESPACE",
    "PEAK_REJECTED_PERIOD_PRODUCTS",
    "POT_DOC_URL",
    "PRODUCT_IDS",
    "RATINGS_DATUMS_URL",
    "build_peak_rejection_annotations",
    "decode_time_series_response",
    "product_facts",
    "series_identity",
    "source_series",
)
