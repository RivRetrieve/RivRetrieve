"""BoM KiWIS series identity and per-series physical evidence."""

from typing import Literal

from rivretrieve._internal.providers.au_bom.generate_catalogue import PRODUCT_DEFINITIONS
from rivretrieve._internal.source_series import (
    ClippingAxis,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
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
