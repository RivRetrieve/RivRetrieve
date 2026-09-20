"""HYDAT daily-table identities and publisher-established physical facts."""

from functools import cache

from rivretrieve._internal.catalogues.source_series import SourceDescription
from rivretrieve._internal.source_series import (
    ClippingAxis,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)


@cache
def source_description(product: str) -> SourceDescription:
    """Identify a native physical-cell stream without inventing a publisher variant."""
    namespace, quantity, unit = {
        "discharge_daily_mean": ("hydat:DLY_FLOWS", "discharge", "m3/s"),
        "stage_daily_mean": ("hydat:DLY_LEVELS", "stage", "m"),
    }[product]
    evidence = (
        "https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/HYDAT_Definition_EN.pdf "
        "pp. 4-5: daily flow (m^3/s), daily water level (m), daily mean symbol definitions"
    )
    facts = PhysicalFacts(
        facts_id=stable_id("ca_eccc", product, unit),
        quantity=known(quantity, evidence),
        source_unit=known(unit, evidence),
        normalized_unit=unit,
        frequency=known("daily", evidence),
        statistic=known("mean", evidence),
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_time="00:00",
    )
    identity = SourceIdentity(namespace=namespace, published_id=None, origin="mapping", evidence=(evidence,))
    return SourceDescription(
        product_id=product,
        native_coordinate=namespace.partition(":")[2],
        identity_key=(namespace, None),
        identity=identity,
        facts=(facts,),
    )


@cache
def source_series(station: str, product: str) -> SourceSeries:
    description = source_description(product)
    return SourceSeries(
        series_id=stable_id("ca_eccc", station, description.identity.namespace, None),
        provider_id="ca_eccc",
        station_id=station,
        product_id=product,
        identity=description.identity,
        facts=description.facts,
    )
