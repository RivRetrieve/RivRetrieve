"""Publisher series identities and physical facts shared by metadata and observations."""

from __future__ import annotations

from collections.abc import Mapping

from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

NAMESPACE = "USGS.WaterData.time_series_id"
EVIDENCE = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/time-series-metadata"
_STATISTICS = {"00003": "mean", "00001": "max", "00002": "min", "00011": "instantaneous"}
_QUANTITIES = {"00060": "discharge", "00065": "stage"}
_UNITS = {"00060": {"ft^3/s": "ft3/s", "m^3/s": "m3/s"}, "00065": {"ft": "ft", "m": "m"}}


def required_string(properties: Mapping[str, object], name: str) -> str:
    value = properties.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or malformed {name}")
    return value


def source_series(
    properties: Mapping[str, object],
    station_id: str,
    product_id: str,
    coordinates: UsgsNwisSourceCoordinates,
    *,
    metadata: bool,
    monitoring_location_id: str,
    known_series: tuple[SourceSeries, ...] = (),
) -> SourceSeries:
    """Validate returned source coordinates without inferring facts from route names."""
    identifier = required_string(properties, "id" if metadata else "time_series_id")
    if required_string(properties, "monitoring_location_id") != monitoring_location_id:
        raise ValueError("Returned monitoring location contradicts requested coordinates")
    parameter = required_string(properties, "parameter_code")
    if parameter != coordinates.parameter_code or parameter not in _QUANTITIES:
        raise ValueError("Returned parameter contradicts requested coordinates")
    if "statistic_id" not in properties:
        raise ValueError("Missing mandatory statistic_id")
    statistic = properties["statistic_id"]
    daily = coordinates.endpoint == "daily"
    if daily and statistic != coordinates.statistic_code:
        raise ValueError("Returned statistic contradicts requested daily coordinates")
    if not daily and statistic not in ("00011", None):
        raise ValueError("Returned statistic contradicts continuous coordinates")
    unit = required_string(properties, "unit_of_measure")
    normalized_unit = _UNITS[parameter].get(unit)
    if normalized_unit is None:
        raise ValueError("Returned unit is unsupported or contradicts the returned physical quantity")
    if metadata:
        period = required_string(properties, "computation_period_identifier")
        computation = required_string(properties, "computation_identifier")
        if daily and period != "Daily":
            raise ValueError("Metadata computation period contradicts daily coordinates")
        if daily and computation != {"00003": "Mean", "00001": "Max", "00002": "Min"}.get(
            coordinates.statistic_code or ""
        ):
            raise ValueError("Metadata computation contradicts published daily statistic")
        if not daily and period != "Points":
            raise ValueError("Metadata computation period contradicts continuous coordinates")
        if not daily and (
            (statistic == "00011" and computation != "Instantaneous")
            or (statistic is None and computation != "Unknown")
        ):
            raise ValueError("Metadata computation contradicts published statistic")
        for field in ("web_description", "sublocation_identifier"):
            if field not in properties or (properties[field] is not None and not isinstance(properties[field], str)):
                raise ValueError(f"Missing or malformed {field}")
    silent = EvidenceFact(state=EvidenceState.SOURCE_SILENT, evidence=(EVIDENCE,))
    stat_value = _STATISTICS.get(statistic) if isinstance(statistic, str) else None
    facts = PhysicalFacts(
        facts_id="pending",
        quantity=known(_QUANTITIES[parameter], EVIDENCE),
        source_unit=known(unit, EVIDENCE),
        normalized_unit=normalized_unit,
        frequency=known("daily", EVIDENCE) if daily else silent,
        statistic=known(stat_value, EVIDENCE) if stat_value else silent,
        temporal_support=known("interval", EVIDENCE)
        if daily
        else (known("instantaneous", EVIDENCE) if statistic == "00011" else silent),
        day_definition=silent,
        timestamp_anchor=silent,
        time_zone=silent,
        clipping_axis=ClippingAxis.CALENDAR_DATE if daily else ClippingAxis.SOURCE_TIMESTAMP,
        label_time="00:00" if daily else None,
    )
    facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
    sid = stable_id("usgs_nwis", station_id, NAMESPACE, identifier)
    existing = next((item for item in known_series if item.series_id == sid), None)
    description = properties.get("web_description") if metadata else None
    if description is not None and not isinstance(description, str):
        raise ValueError("Malformed web_description")
    identity = SourceIdentity(
        namespace=NAMESPACE,
        published_id=identifier,
        description=description,
        origin="catalogue" if metadata else "response",
        evidence=(EVIDENCE,),
    )
    if not metadata and existing is not None:
        identity = existing.identity
    return SourceSeries(
        series_id=sid,
        provider_id="usgs_nwis",
        station_id=station_id,
        product_id=product_id,
        identity=identity,
        variant=identifier,
        facts=(facts,),
    )
