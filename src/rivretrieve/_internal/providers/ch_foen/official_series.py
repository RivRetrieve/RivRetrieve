"""Official Swiss publication identities and independently established physical facts.

Temporal support describes the aggregate window. For minimum/maximum products it
is not the averaging duration of the underlying short-term measurement, which
remains unknown. UTC timestamp serialization is separate from the UTC+1 calendar.
"""

from typing import Literal

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import (
    EvidenceFact,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

ARCHIVE_ROUTES = (
    "data_10min_mean",
    "data_1hour_mean",
    "data_1day_mean",
    "data_1day_min",
    "data_1day_max",
    "data_1month_mean",
    "data_1month_min",
    "data_1month_max",
    "data_1year_mean",
    "data_1year_min",
    "data_1year_max",
)
PARAMETERS = {"Q": ("discharge", "discharge"), "W": ("stage", "stage"), "WT": ("water_temperature", "temperature")}
UNITS = {
    "m³/s": "m3/s",
    "m3/s": "m3/s",
    "l/s": "l/s",
    "m": "m",
    "cm": "cm",
    "°C": "degC",
    "m ü.M.": "m",
    "m a.s.l.": "m",
}


def product_id(route: str, parameter: str) -> str:
    if route not in (*ARCHIVE_ROUTES, "data_live") or parameter not in PARAMETERS:
        raise FatalContractError("Swiss association has an unsupported route or parameter")
    suffix = "recent" if route == "data_live" else route.removeprefix("data_")
    return f"{PARAMETERS[parameter][0]}_{suffix}"


# Publisher vocabulary only: retain the original field and its code/null in rows.
# Status 3 includes corrections and definitive stage-discharge relations. It is
# not a RivRetrieve ranking; unresolved "ersetzt" wording establishes no lineage.
RELEASE_STATUS_FIELDS = {"archive": "releaseState", "recent": "releaseStatus"}
RELEASE_STATUS_MEANINGS = {
    None: "raw",
    0: "raw",
    1: "unreleased/prechecked",
    2: "released/checked",
    3: "released/definitive",
}

# Calendar periods are not fixed elapsed durations. These declarations do not
# implement request bounds or clipping.
_PERIODS = {
    "10min": ("10min", "10_minutes"),
    "1hour": ("hourly", "1_hour"),
    "1day": ("daily", "calendar_day"),
    "1month": ("monthly", "calendar_month"),
    "1year": ("yearly", "calendar_year"),
}


def source_series(
    station: str,
    route: str,
    parameter: str,
    name: str | None,
    *,
    units: tuple[str | None, ...],
    evidence: str,
    temporal_evidence: str,
    origin: Literal["catalogue", "response"],
) -> SourceSeries:
    """Resolve witnessed coordinates and unit bindings without reading source data.

    ``units`` contains archive unit symbols or resolved recent station-page units;
    missing recent bindings remain None. Unit segments do not rename identities.
    Raw names preserve archive variants; recent publications have no raw name.
    Temporal evidence must identify the adopted publisher product definitions.
    Unknown support and datum do not prevent dimensional admission.
    """
    product = product_id(route, parameter)
    temporal = {"time_zone": known("UTC", temporal_evidence)}
    unresolved = station == "7008" and route == "data_1day_mean" and name == "MonatsMittel_Orbe_flex"
    if route == "data_live":
        temporal["timestamp_anchor"] = known("end", temporal_evidence)
    elif not unresolved:
        period, statistic = route.removeprefix("data_").rsplit("_", 1)
        frequency, support = _PERIODS[period]
        temporal.update(
            frequency=known(frequency, temporal_evidence),
            statistic=known(statistic, temporal_evidence),
            temporal_support=known(support, temporal_evidence),
            timestamp_anchor=known("start", temporal_evidence),
        )
        if period in {"1day", "1month", "1year"}:
            temporal["day_definition"] = known("UTC+01:00", temporal_evidence)
    facts = []
    for unit in sorted(set(units), key=lambda unit: unit or ""):
        fact = PhysicalFacts(
            facts_id="unidentified",
            quantity=known(PARAMETERS[parameter][1], evidence),
            source_unit=known(unit, evidence) if unit else EvidenceFact(),
            normalized_unit=UNITS.get(unit) if unit is not None else None,
            vertical_reference=known("above_sea_level", evidence)
            if parameter == "W" and unit in {"m ü.M.", "m a.s.l."}
            else EvidenceFact(),
            frequency=temporal.get("frequency", EvidenceFact()),
            statistic=temporal.get("statistic", EvidenceFact()),
            temporal_support=temporal.get("temporal_support", EvidenceFact()),
            timestamp_anchor=temporal.get("timestamp_anchor", EvidenceFact()),
            day_definition=temporal.get("day_definition", EvidenceFact()),
            time_zone=temporal["time_zone"],
        )
        facts.append(fact.model_copy(update={"facts_id": stable_id(fact.model_dump_json(exclude={"facts_id"}))}))
    return SourceSeries(
        series_id=stable_id("ch_foen", station, route, parameter, name),
        provider_id="ch_foen",
        station_id=station,
        product_id=product,
        identity=SourceIdentity(
            namespace=f"foen.{route}.{parameter}",
            published_id=parameter if route == "data_live" else name,
            origin=origin,
            evidence=(evidence,),
        ),
        variant=name,
        facts=tuple(facts),
    )
