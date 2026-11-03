"""BoM KiWIS series identity and per-series physical evidence."""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.source_series import (
    ClippingAxis,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

# Shared with generate_catalogue.py (maintainer-tier): this dataclass and tuple live
# here, not there, because declaration.py's runtime import graph (series.py <- parse.py
# <- declaration.py) must never reach generate_catalogue.py, a MAINTAINER_ROLES module
# (tests/test_provider_architecture_contracts.py). generate_catalogue.py imports these
# from series.py instead.


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    quantity: str
    frequency: str
    statistic: str
    canonical_unit: str
    native_id: str
    timeseries_list_kind: str


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        "discharge_hourly_mean",
        "discharge",
        "discharge",
        "hourly",
        "mean",
        "m3/s",
        "DMQaQc.Merged.HourlyMean.HR",
        "timeseries_list_discharge_HourlyMean_HR",
    ),
    ProductDefinition(
        "discharge_daily_mean_24hr",
        "discharge",
        "discharge",
        "daily",
        "mean",
        "m3/s",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_discharge_DailyMean_24HR",
    ),
    ProductDefinition(
        "discharge_daily_mean_09hr",
        "discharge",
        "discharge",
        "daily",
        "mean",
        "m3/s",
        "DMQaQc.Merged.DailyMean.09HR",
        "timeseries_list_discharge_DailyMean_09HR",
    ),
    ProductDefinition(
        "discharge_daily_max",
        "discharge",
        "discharge",
        "daily",
        "max",
        "m3/s",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_discharge_DailyMax_24HR",
    ),
    ProductDefinition(
        "discharge_daily_min",
        "discharge",
        "discharge",
        "daily",
        "min",
        "m3/s",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_discharge_DailyMin_24HR",
    ),
    ProductDefinition(
        "discharge_monthly_mean",
        "discharge",
        "discharge",
        "monthly",
        "mean",
        "m3/s",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_discharge_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "discharge_yearly_mean",
        "discharge",
        "discharge",
        "yearly",
        "mean",
        "m3/s",
        "DMQaQc.Merged.YearlyMean.CalYear",
        "timeseries_list_discharge_YearlyMean_CalYear",
    ),
    ProductDefinition(
        "stage_hourly_mean",
        "stage",
        "stage",
        "hourly",
        "mean",
        "m",
        "DMQaQc.Merged.HourlyMean.HR",
        "timeseries_list_stage_HourlyMean_HR",
    ),
    ProductDefinition(
        "stage_daily_mean",
        "stage",
        "stage",
        "daily",
        "mean",
        "m",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_stage_DailyMean_24HR",
    ),
    ProductDefinition(
        "stage_daily_max",
        "stage",
        "stage",
        "daily",
        "max",
        "m",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_stage_DailyMax_24HR",
    ),
    ProductDefinition(
        "stage_daily_min",
        "stage",
        "stage",
        "daily",
        "min",
        "m",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_stage_DailyMin_24HR",
    ),
    ProductDefinition(
        "stage_monthly_mean",
        "stage",
        "stage",
        "monthly",
        "mean",
        "m",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_stage_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "stage_yearly_mean",
        "stage",
        "stage",
        "yearly",
        "mean",
        "m",
        "DMQaQc.Merged.YearlyMean.CalYear",
        "timeseries_list_stage_YearlyMean_CalYear",
    ),
    ProductDefinition(
        "water_temperature_daily_mean",
        "water_temperature",
        "temperature",
        "daily",
        "mean",
        "degC",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_temperature_DailyMean_24HR",
    ),
    ProductDefinition(
        "water_temperature_daily_max",
        "water_temperature",
        "temperature",
        "daily",
        "max",
        "degC",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_temperature_DailyMax_24HR",
    ),
    ProductDefinition(
        "water_temperature_daily_min",
        "water_temperature",
        "temperature",
        "daily",
        "min",
        "degC",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_temperature_DailyMin_24HR",
    ),
    ProductDefinition(
        "water_temperature_monthly_mean",
        "water_temperature",
        "temperature",
        "monthly",
        "mean",
        "degC",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_temperature_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "water_temperature_yearly_mean",
        "water_temperature",
        "temperature",
        "yearly",
        "mean",
        "degC",
        "DMQaQc.Merged.YearlyMean.CalYear",
        "timeseries_list_temperature_YearlyMean_CalYear",
    ),
)

EVIDENCE = (
    "BoM KiWIS getTimeseriesList (ts_unitname/ts_unitsymbol) and getTimeseriesValues "
    "(timestamp labels, Quality Code); confirmed live 2026-11-03"
)

_BY_PRODUCT_ID = {d.product_id: d for d in PRODUCT_DEFINITIONS}

# BoM's native unit symbols (ts_unitsymbol), mapped to RivRetrieve's recognised
# normalized spellings. "cumec" is not itself a recognised spelling; "m" and
# "°C" already are.
_NORMALIZED_UNITS = {"cumec": "m3/s", "m": "m", "°C": "degC"}

# Confirmed live 2026-11-03 (planning/visions/2026-11-03-au-bom-series-identity-and-physical-meaning.md):
# every DailyMax/DailyMin/Monthly/Yearly timestamp checked is a period-start label
# (00:00+10:00), never the clock time of the actual extreme -- unlike at_ehyd's
# Monatsmaxima. day_definition and timestamp_anchor stay unestablished EvidenceFacts
# here, matching every other provider in this codebase; none currently populates
# either field, and this does not introduce a new, unreviewed vocabulary for them.


def describe_series(
    station_no: str,
    ts_id: str,
    product_id: str,
    source_unit_symbol: str,
    *,
    origin: Literal["catalogue", "response", "mapping"] = "response",
) -> SourceSeries:
    """Build the one concrete source identity for a station's ts_id under one product.

    Two distinct ts_id can exist for the same station and product (confirmed
    live 2026-11-03: 74 discharge, 79 stage and 4 water-temperature stations
    each carry a second ts_id for an admitted series, with no field
    distinguishing them). series_id is derived from ts_id, following
    usgs_nwis's precedent for the same situation, so both surface as separate
    series under the same product_id rather than one being picked. variant
    stays None: BoM names no distinction between them.
    """
    if product_id not in _BY_PRODUCT_ID:
        raise ValueError(f"au_bom series description requires an admitted product_id: {product_id!r}")
    definition = _BY_PRODUCT_ID[product_id]
    series_id = stable_id("au_bom", station_no, "KiWIS.ts_id", ts_id)
    facts = PhysicalFacts(
        facts_id=series_id,
        quantity=known(definition.quantity, EVIDENCE),
        source_unit=known(source_unit_symbol, EVIDENCE),
        normalized_unit=_NORMALIZED_UNITS.get(source_unit_symbol),
        frequency=known(definition.frequency, EVIDENCE),
        statistic=known(definition.statistic, EVIDENCE),
        time_zone=known("+10:00", EVIDENCE + "; every timestamp checked carries +10:00 explicitly"),
        # CALENDAR_DATE clipping is only valid for established daily frequency
        # (enforced by PhysicalFacts itself); monthly/yearly use SOURCE_TIMESTAMP too.
        clipping_axis=ClippingAxis.CALENDAR_DATE if definition.frequency == "daily" else ClippingAxis.SOURCE_TIMESTAMP,
    )
    return SourceSeries(
        series_id=series_id,
        provider_id="au_bom",
        station_id=station_no,
        product_id=product_id,
        identity=SourceIdentity(namespace="KiWIS.ts_id", published_id=ts_id, origin=origin, evidence=(EVIDENCE,)),
        variant=None,
        facts=(facts,),
    )
