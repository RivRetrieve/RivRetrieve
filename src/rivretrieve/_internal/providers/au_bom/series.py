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
        "PT1H",
        "mean",
        "m3/s",
        "DMQaQc.Merged.HourlyMean.HR",
        "timeseries_list_discharge_HourlyMean_HR",
    ),
    ProductDefinition(
        "discharge_daily_mean_24hr",
        "discharge",
        "discharge",
        "P1D",
        "mean",
        "m3/s",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_discharge_DailyMean_24HR",
    ),
    ProductDefinition(
        "discharge_daily_mean_09hr",
        "discharge",
        "discharge",
        "P1D",
        "mean",
        "m3/s",
        "DMQaQc.Merged.DailyMean.09HR",
        "timeseries_list_discharge_DailyMean_09HR",
    ),
    ProductDefinition(
        "discharge_daily_max",
        "discharge",
        "discharge",
        "P1D",
        "max",
        "m3/s",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_discharge_DailyMax_24HR",
    ),
    ProductDefinition(
        "discharge_daily_min",
        "discharge",
        "discharge",
        "P1D",
        "min",
        "m3/s",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_discharge_DailyMin_24HR",
    ),
    ProductDefinition(
        "discharge_monthly_mean",
        "discharge",
        "discharge",
        "P1M",
        "mean",
        "m3/s",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_discharge_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "discharge_yearly_mean",
        "discharge",
        "discharge",
        "P1Y",
        "mean",
        "m3/s",
        "DMQaQc.Merged.YearlyMean.CalYear",
        "timeseries_list_discharge_YearlyMean_CalYear",
    ),
    ProductDefinition(
        "stage_hourly_mean",
        "stage",
        "stage",
        "PT1H",
        "mean",
        "m",
        "DMQaQc.Merged.HourlyMean.HR",
        "timeseries_list_stage_HourlyMean_HR",
    ),
    ProductDefinition(
        "stage_daily_mean",
        "stage",
        "stage",
        "P1D",
        "mean",
        "m",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_stage_DailyMean_24HR",
    ),
    ProductDefinition(
        "stage_daily_max",
        "stage",
        "stage",
        "P1D",
        "max",
        "m",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_stage_DailyMax_24HR",
    ),
    ProductDefinition(
        "stage_daily_min",
        "stage",
        "stage",
        "P1D",
        "min",
        "m",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_stage_DailyMin_24HR",
    ),
    ProductDefinition(
        "stage_monthly_mean",
        "stage",
        "stage",
        "P1M",
        "mean",
        "m",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_stage_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "stage_yearly_mean",
        "stage",
        "stage",
        "P1Y",
        "mean",
        "m",
        "DMQaQc.Merged.YearlyMean.CalYear",
        "timeseries_list_stage_YearlyMean_CalYear",
    ),
    ProductDefinition(
        "water_temperature_daily_mean",
        "water_temperature",
        "temperature",
        "P1D",
        "mean",
        "degC",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_temperature_DailyMean_24HR",
    ),
    ProductDefinition(
        "water_temperature_daily_max",
        "water_temperature",
        "temperature",
        "P1D",
        "max",
        "degC",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_temperature_DailyMax_24HR",
    ),
    ProductDefinition(
        "water_temperature_daily_min",
        "water_temperature",
        "temperature",
        "P1D",
        "min",
        "degC",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_temperature_DailyMin_24HR",
    ),
    ProductDefinition(
        "water_temperature_monthly_mean",
        "water_temperature",
        "temperature",
        "P1M",
        "mean",
        "degC",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_temperature_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "water_temperature_yearly_mean",
        "water_temperature",
        "temperature",
        "P1Y",
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

# Confirmed live 2026-11-03 and 2026-11-26 (#1082):
# Every DailyMax/DailyMin/Monthly/Yearly timestamp checked is a period-start
# label, never the clock time of the actual extreme -- unlike at_ehyd's
# Monatsmaxima. timestamp_anchor stays an unestablished EvidenceFact, matching
# every other provider in this codebase; none currently populates it.
#
# BoM's default getTimeseriesValues response serializes every timestamp in
# +10:00 while daily, monthly and yearly aggregations remain anchored to the
# contributing agency's local standard time (+08:00 in WA, +09:30 in SA/NT,
# +10:00 in eastern states; no DST shifts). Under +10:00, each non-empty series
# has a single constant wall-clock anchor in ALLOWED_24HR_LABEL_TIMES
# (24HR/CalMonth/CalYear) or ALLOWED_09HR_LABEL_TIMES (09HR), established per
# series at parse time and validated against every row by conversion.py. Two
# series at the same station can carry different anchors (e.g. SA station
# A5131021: discharge at 00:00+10:00, water temperature at 00:30+10:00).
# Hourly products and empty responses leave label_time=None. day_definition
# stays unestablished.
ALLOWED_24HR_LABEL_TIMES: frozenset[str] = frozenset({"00:00", "00:30", "02:00"})
ALLOWED_09HR_LABEL_TIMES: frozenset[str] = frozenset({"09:00", "09:30", "11:00"})


def allowed_label_times(product_id: str) -> frozenset[str] | None:
    """Return the valid +10:00 wall-clock anchors for ``product_id``, or ``None`` for hourly."""
    if product_id not in _BY_PRODUCT_ID:
        raise ValueError(f"au_bom product_id is not admitted: {product_id!r}")
    definition = _BY_PRODUCT_ID[product_id]
    if definition.frequency == "PT1H":
        return None
    return ALLOWED_09HR_LABEL_TIMES if definition.native_id.endswith(".09HR") else ALLOWED_24HR_LABEL_TIMES


def _variant(definition: ProductDefinition) -> str | None:
    """ "24hr"/"09hr" for discharge's two daily means, BoM's own named alternative.

    Every other au_bom product is already unambiguous under quantity,
    frequency and statistic alone and keeps variant unset, matching
    br_ana's own precedent for exactly this situation (bruto/consistido):
    a named alternative selectable via rr.pick(selection, variant=...),
    documented generically in usage.md's "When an agency publishes more
    than one version".
    """
    if definition.product_id == "discharge_daily_mean_24hr":
        return "24hr"
    if definition.product_id == "discharge_daily_mean_09hr":
        return "09hr"
    return None


def describe_series(
    station_no: str,
    ts_id: str,
    product_id: str,
    source_unit_symbol: str,
    *,
    label_time: str | None = None,
    origin: Literal["catalogue", "response", "mapping"] = "response",
) -> SourceSeries:
    """Build the one concrete source identity for a station's ts_id under one product.

    Two distinct ts_id can exist for the same station and product (confirmed
    live 2026-11-03: 74 discharge, 79 stage and 4 water-temperature stations
    each carry a second ts_id for an admitted series, with no field
    distinguishing them). series_id is derived from ts_id, following
    usgs_nwis's precedent for the same situation, so both surface as separate
    series under the same product_id rather than one being picked. variant
    stays None for this ts_id-level duplication: BoM names no distinction
    between the two. Separately, _variant() above resolves discharge's two
    daily-mean products (24hr/09hr) to a named variant, a different kind of
    ambiguity BoM does name.

    ``label_time`` records the per-series +10:00 wall-clock anchor observed in
    the response (one of ``00:00``/``00:30``/``02:00`` for 24HR/CalMonth/CalYear
    or ``09:00``/``09:30``/``11:00`` for 09HR), or ``None`` for hourly products
    and empty/list-only descriptions. ``facts_id`` incorporates ``label_time``
    so empty and populated responses for the same ``ts_id`` never collide.
    """
    if product_id not in _BY_PRODUCT_ID:
        raise ValueError(f"au_bom series description requires an admitted product_id: {product_id!r}")
    allowed = allowed_label_times(product_id)
    if label_time is not None:
        if allowed is None:
            raise ValueError(f"au_bom hourly product {product_id!r} does not accept label_time={label_time!r}")
        if label_time not in allowed:
            raise ValueError(f"au_bom product {product_id!r} label_time {label_time!r} is not in {sorted(allowed)}")
    definition = _BY_PRODUCT_ID[product_id]
    series_id = stable_id("au_bom", station_no, "KiWIS.ts_id", ts_id)
    facts_id = stable_id(series_id, label_time) if label_time is not None else stable_id(series_id, "unset")
    facts = PhysicalFacts(
        facts_id=facts_id,
        quantity=known(definition.quantity, EVIDENCE),
        source_unit=known(source_unit_symbol, EVIDENCE),
        normalized_unit=_NORMALIZED_UNITS.get(source_unit_symbol),
        frequency=known(definition.frequency, EVIDENCE),
        statistic=known(definition.statistic, EVIDENCE),
        time_zone=known("+10:00", EVIDENCE + "; every timestamp checked carries +10:00 explicitly"),
        # CALENDAR_DATE clipping is only valid for established daily frequency
        # (enforced by PhysicalFacts itself); monthly/yearly use SOURCE_TIMESTAMP too.
        clipping_axis=ClippingAxis.CALENDAR_DATE if definition.frequency == "P1D" else ClippingAxis.SOURCE_TIMESTAMP,
        label_time=label_time,
    )
    return SourceSeries(
        series_id=series_id,
        provider_id="au_bom",
        station_id=station_no,
        product_id=product_id,
        identity=SourceIdentity(namespace="KiWIS.ts_id", published_id=ts_id, origin=origin, evidence=(EVIDENCE,)),
        variant=_variant(definition),
        facts=(facts,),
    )
