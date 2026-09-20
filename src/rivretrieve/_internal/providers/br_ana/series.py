"""ANA consistency and adopted-field identities with established physical facts."""

from typing import Literal

from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, BrAnaSourceCoordinates
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

_DAILY_EVIDENCE = "ANA Hidro1.4 dictionary pp21-24 and current API correspondence; daily-definitions-report"
_TELEMETRY_EVIDENCE = "ANA API manual page11 Cota_Adotada(cm), Vazao_Adotada(m3/s), Data_Hora_Medicao"


def describe_series(
    station: str,
    product: str,
    coordinates: BrAnaSourceCoordinates | BrAnaDailySourceCoordinates,
    *,
    origin: Literal["catalogue", "response", "mapping"] = "mapping",
) -> SourceSeries:
    daily = isinstance(coordinates, BrAnaDailySourceCoordinates)
    field = coordinates.field_prefix if daily else coordinates.field
    quantity = "discharge" if field.startswith("Vazao") else "stage"
    source_unit = "m3/s" if quantity == "discharge" else "cm"
    evidence = _DAILY_EVIDENCE if daily else _TELEMETRY_EVIDENCE
    native_id = coordinates.consistency if daily else coordinates.field
    namespace = "ANA.Hidro.NivelConsistencia" if daily else "ANA.telemetry.field"
    identity = stable_id("br_ana", station, namespace, field, native_id)
    definition = PhysicalFacts(
        facts_id=stable_id(identity, source_unit, "daily_mean" if daily else "measurement_time"),
        quantity=known(quantity, evidence),
        source_unit=known(source_unit, evidence),
        normalized_unit=source_unit,
        frequency=known("daily", evidence) if daily else EvidenceFact(),
        statistic=known("mean", evidence) if daily else EvidenceFact(),
        timestamp_anchor=EvidenceFact() if daily else known("measurement_time", evidence),
        clipping_axis=ClippingAxis.CALENDAR_DATE if daily else ClippingAxis.SOURCE_TIMESTAMP,
        label_time="00:00" if daily else None,
    )
    return SourceSeries(
        series_id=identity,
        provider_id="br_ana",
        station_id=station,
        product_id=product,
        identity=SourceIdentity(
            namespace=namespace,
            published_id=native_id,
            description=("Bruto" if native_id == "1" else "Consistido") if daily else None,
            origin=origin,
            evidence=(evidence,),
        ),
        variant=("bruto" if native_id == "1" else "consistido") if daily else native_id,
        facts=(definition,),
    )
