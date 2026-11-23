"""Published Ireland OPW Hydro-Data series mappings and established Step 3 physical facts.

OPW Hydro-Data daily ``year.json`` routes publish UTC ``[00:00Z, 24:00Z]`` calendar-day
summaries (``temporal_support="calendar_day"``, ``day_definition="+00:00"``,
``timestamp_anchor="start"``, ``time_zone="+00:00"``, ``label_time="00:00"``). Instantaneous
``*_complete.zip`` routes publish time-stamped measurements (``temporal_support="instantaneous"``,
``statistic="instantaneous"``, ``timestamp_anchor="measurement_time"``, ``time_zone="+00:00"``)
with ``frequency`` left ``not_established`` because native cadences mix 15-min ``Q``/``S``
and 1-hour ``TWater`` (plus variable historical intervals). Stage (``S``) heights are measured
above Ordnance Datum (``vertical_reference="above_sea_level"``), keeping ``vertical_datum``
``not_established`` because the station table mixes ``Malin Head OSGM15``, ``Poolbeg``, and
``Malin Head`` datums.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.provider_series import SeriesMapping
from rivretrieve._internal.source_series import SourceIdentity, SourceUnitCodeDefinition

Q_NAMESPACE = "ie_opw.hydro_data.Q"
S_NAMESPACE = "ie_opw.hydro_data.S"
TWATER_NAMESPACE = "ie_opw.hydro_data.TWater"

_ASSOCIATION_EVIDENCE = ("catalogue:ie_opw:source.station_product.associations",)
_FIELD_EVIDENCE = ("catalogue:ie_opw:source.series.fields",)
_UNIT_EVIDENCE = ("catalogue:ie_opw:source.product.unit_definitions",)
_TEMPORAL_EVIDENCE = "catalogue:ie_opw:source.series.temporal_semantics"
_STAGE_VERTICAL_EVIDENCE = "catalogue:ie_opw:source.series.stage_vertical_reference"

UNIT_CUMEC_DEFINITION = SourceUnitCodeDefinition(
    provider_id="ie_opw",
    namespace=Q_NAMESPACE,
    code="cumec",
    unit="m3/s",
    evidence=_UNIT_EVIDENCE,
)


@dataclass(frozen=True, slots=True)
class ProductSpec:
    """Native source mapping for one Ireland OPW Hydro-Data observation product."""

    product_id: str
    parameter: Literal["Q", "S", "TWater"]
    route: Literal["year.json", "Discharge_complete.zip", "Waterlevel_complete.zip", "WaterTemperature_complete.zip"]
    ts_shortname: str
    quantity: Literal["discharge", "stage", "temperature"]
    source_unit: Literal["cumec", "m", "°C"]
    normalized_unit: Literal["m3/s", "m", "degC"]
    frequency: Literal["daily"] | None
    statistic: Literal["mean", "min", "max", "instantaneous"]
    temporal_support: Literal["calendar_day", "instantaneous"]
    day_definition: Literal["+00:00"] | None
    timestamp_anchor: Literal["start", "measurement_time"]
    time_zone: Literal["+00:00"]
    label_time: Literal["00:00"] | None

    @property
    def namespace(self) -> str:
        if self.parameter == "Q":
            return Q_NAMESPACE
        if self.parameter == "S":
            return S_NAMESPACE
        return TWATER_NAMESPACE

    @property
    def native_coordinate(self) -> str:
        return f"{self.parameter}/{self.route}:{self.ts_shortname}"

    def series_mapping(self) -> SeriesMapping:
        """Build verified Step 3 physical mapping for this OPW Hydro-Data route."""
        evidence: list[str] = [*_ASSOCIATION_EVIDENCE, _TEMPORAL_EVIDENCE]
        if self.quantity == "stage":
            evidence.append(_STAGE_VERTICAL_EVIDENCE)
        return SeriesMapping(
            namespace=self.namespace,
            published_id=self.ts_shortname,
            quantity=self.quantity,
            source_unit=self.source_unit,
            normalized_unit=self.normalized_unit,
            frequency=self.frequency,
            statistic=self.statistic,
            time_zone=self.time_zone,
            source_unit_definition=UNIT_CUMEC_DEFINITION if self.parameter == "Q" else None,
            evidence=tuple(evidence),
            identity_evidence=_FIELD_EVIDENCE,
            temporal_support=self.temporal_support,
            day_definition=self.day_definition,
            timestamp_anchor=self.timestamp_anchor,
            vertical_reference="above_sea_level" if self.quantity == "stage" else None,
            vertical_datum=None,
            label_time=self.label_time,
        )


PRODUCT_SPECS: tuple[ProductSpec, ...] = (
    # Discharge (Q: cumec -> m3/s)
    ProductSpec(
        "discharge_daily_mean",
        "Q",
        "year.json",
        "WEB.Day.Mean",
        "discharge",
        "cumec",
        "m3/s",
        "daily",
        "mean",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "discharge_daily_min",
        "Q",
        "year.json",
        "WEB.Day.Min",
        "discharge",
        "cumec",
        "m3/s",
        "daily",
        "min",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "discharge_daily_max",
        "Q",
        "year.json",
        "WEB.Day.Max",
        "discharge",
        "cumec",
        "m3/s",
        "daily",
        "max",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "discharge_instantaneous",
        "Q",
        "Discharge_complete.zip",
        "WEB.Cmd.Runoff",
        "discharge",
        "cumec",
        "m3/s",
        None,
        "instantaneous",
        "instantaneous",
        None,
        "measurement_time",
        "+00:00",
        None,
    ),
    # Stage (S: m -> m, Ordnance Datum)
    ProductSpec(
        "stage_daily_mean",
        "S",
        "year.json",
        "WEB.Day.Mean",
        "stage",
        "m",
        "m",
        "daily",
        "mean",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "stage_daily_min",
        "S",
        "year.json",
        "WEB.Day.Min",
        "stage",
        "m",
        "m",
        "daily",
        "min",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "stage_daily_max",
        "S",
        "year.json",
        "WEB.Day.Max",
        "stage",
        "m",
        "m",
        "daily",
        "max",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "stage_instantaneous",
        "S",
        "Waterlevel_complete.zip",
        "WEB.Cmd.P-Continuous.Absolute",
        "stage",
        "m",
        "m",
        None,
        "instantaneous",
        "instantaneous",
        None,
        "measurement_time",
        "+00:00",
        None,
    ),
    # Water Temperature (TWater: °C -> degC)
    ProductSpec(
        "water_temperature_daily_mean",
        "TWater",
        "year.json",
        "WEB.Day.Mean-Water-Temp",
        "temperature",
        "°C",
        "degC",
        "daily",
        "mean",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "water_temperature_daily_min",
        "TWater",
        "year.json",
        "WEB.Day.Min-Water-Temp",
        "temperature",
        "°C",
        "degC",
        "daily",
        "min",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "water_temperature_daily_max",
        "TWater",
        "year.json",
        "WEB.Day.Max-Water-Temp",
        "temperature",
        "°C",
        "degC",
        "daily",
        "max",
        "calendar_day",
        "+00:00",
        "start",
        "+00:00",
        "00:00",
    ),
    ProductSpec(
        "water_temperature_instantaneous",
        "TWater",
        "WaterTemperature_complete.zip",
        "WEB.Cmd.P-Water-Temp",
        "temperature",
        "°C",
        "degC",
        None,
        "instantaneous",
        "instantaneous",
        None,
        "measurement_time",
        "+00:00",
        None,
    ),
)

PRODUCT_BY_ID: dict[str, ProductSpec] = {spec.product_id: spec for spec in PRODUCT_SPECS}
YEAR_JSON_BY_PARAM_SHORTNAME: dict[tuple[str, str], ProductSpec] = {
    (spec.parameter, spec.ts_shortname): spec for spec in PRODUCT_SPECS if spec.route == "year.json"
}
COMPLETE_ZIP_BY_PARAM: dict[str, ProductSpec] = {
    spec.parameter: spec for spec in PRODUCT_SPECS if spec.route.endswith("_complete.zip")
}


def catalogue_product_rows() -> list[dict[str, object]]:
    """Build deterministic product catalogue rows matching `PRODUCT_CATALOG_SCHEMA`."""
    return [
        product_row(
            provider_id="ie_opw",
            product_id=spec.product_id,
            native_id=spec.native_coordinate,
            facts=spec.series_mapping().physical_facts(),
        )
        for spec in sorted(PRODUCT_SPECS, key=lambda item: item.product_id)
    ]


def describe_associations() -> SourceDescriptions:
    """Emit product-scoped source descriptions applied to all available and unknown pairs."""
    descriptions: list[SourceDescription] = []
    for spec in sorted(PRODUCT_SPECS, key=lambda item: item.product_id):
        mapping = spec.series_mapping()
        identity = SourceIdentity(
            namespace=mapping.namespace,
            published_id=spec.ts_shortname,
            origin="mapping",
            evidence=_FIELD_EVIDENCE,
        )
        descriptions.append(
            SourceDescription(
                product_id=spec.product_id,
                native_coordinate=spec.native_coordinate,
                identity=identity,
                facts=(mapping.physical_facts(),),
            )
        )
    return SourceDescriptions(provider_id="ie_opw", descriptions=tuple(descriptions))
