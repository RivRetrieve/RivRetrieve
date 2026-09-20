"""Physical cell definitions shared by IMGW catalogue and archive compilation."""

from functools import cache

from rivretrieve._internal.catalogues.source_series import SourceDescription
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

FORMAT_DEFINITION = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/CODZ_publiczne_format.txt"
)

METHOD_DEFINITION = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/Roczniki/"
    "Rocznik%20hydrologiczny/Rocznik%20Hydrologiczny%202025.pdf pp. 7-9; "
    "station-dependent level/discharge statistics; timed temperature in selected yearbook scope; "
    "CODZ station-era applicability not established"
)


@cache
def describe_product(product: str) -> SourceDescription:
    """Describe one published physical column without creating a station identity."""
    coordinate, quantity, unit = {
        "discharge_daily": ("flow_m3s", "discharge", "m3/s"),
        "stage_daily": ("level_cm", "stage", "cm"),
        "water_temperature_daily": ("temperature_c", "temperature", "degC"),
    }[product]
    namespace = f"imgw:{coordinate}"
    facts = PhysicalFacts(
        facts_id=product,
        quantity=known(quantity, FORMAT_DEFINITION),
        source_unit=known(unit, FORMAT_DEFINITION),
        normalized_unit=unit,
        frequency=known("daily", FORMAT_DEFINITION),
        statistic=EvidenceFact(evidence=(METHOD_DEFINITION,)),
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_time="00:00",
    )
    facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
    return SourceDescription(
        product_id=product,
        native_coordinate={"flow_m3s": "COPRZP", "level_cm": "COSTAN", "temperature_c": "COPTMP"}[coordinate],
        identity_key=(namespace, None),
        identity=SourceIdentity(namespace=namespace, origin="mapping", evidence=(FORMAT_DEFINITION,)),
        facts=(facts,),
    )


@cache
def source_series(station: str, product: str) -> SourceSeries:
    description = describe_product(product)
    return SourceSeries(
        series_id=stable_id("pl_imgw", station, description.identity.namespace, None),
        provider_id="pl_imgw",
        station_id=station,
        product_id=product,
        identity=description.identity,
        facts=description.facts,
    )
