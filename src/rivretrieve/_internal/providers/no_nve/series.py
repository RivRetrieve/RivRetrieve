"""HydAPI series version identity and per-resolution physical evidence."""

from typing import Literal

from rivretrieve._internal.source_series import (
    ClippingAxis,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

NVE_EVIDENCE = "HydAPI station seriesList/versionNo/resolutionList and observation series metadata"
PARAMETERS = {1000: ("stage", "stage"), 1001: ("discharge", "discharge"), 1003: ("temperature", "water_temperature")}
UNITS = {"m": "m", "m³/s": "m3/s", "°C": "degC"}


def describe_series(
    station: str,
    parameter: int,
    version: int,
    resolution: int,
    method: str | None,
    source_unit: str | None,
    *,
    origin: Literal["catalogue", "response", "mapping"] = "response",
) -> SourceSeries:
    quantity, prefix = PARAMETERS[parameter]
    statistic = {"Mean": "mean", "Instantaneous": "instantaneous"}.get(method or "")
    frequency = {60: "hourly", 1440: "daily"}.get(resolution)
    # Product is an access coordinate, not authority for statistic or conversion.
    product = prefix + ("_instantaneous" if resolution == 0 else "_hourly_mean" if resolution == 60 else "_daily_mean")
    identity = stable_id("no_nve", station, "HydAPI.version", str(parameter), str(version), str(resolution))
    facts_kwargs = {}
    if frequency is not None:
        facts_kwargs["frequency"] = known(frequency, NVE_EVIDENCE + "; resTime=" + str(resolution))
    if statistic is not None:
        facts_kwargs["statistic"] = known(statistic, NVE_EVIDENCE + "; method=" + str(method))
    if source_unit is not None:
        facts_kwargs["source_unit"] = known(source_unit, NVE_EVIDENCE + "; unit")
    facts = PhysicalFacts(
        facts_id=stable_id(identity, method, source_unit),
        quantity=known(quantity, NVE_EVIDENCE + "; parameter=" + str(parameter)),
        normalized_unit=UNITS.get(source_unit or ""),
        time_zone=known("+00:00", NVE_EVIDENCE + "; explicit Z timestamp labels"),
        clipping_axis=ClippingAxis.CALENDAR_DATE if resolution == 1440 else ClippingAxis.SOURCE_TIMESTAMP,
        **facts_kwargs,
    )
    return SourceSeries(
        series_id=identity,
        provider_id="no_nve",
        station_id=station,
        product_id=product,
        identity=SourceIdentity(
            namespace="HydAPI.version", published_id=str(version), origin=origin, evidence=(NVE_EVIDENCE,)
        ),
        variant=str(version),
        facts=(facts,),
    )
