"""CL DGA declaration : ProviderConfig."""

from dataclasses import dataclass
from typing import Final

from rivretrieve._internal.engine import (
    CacheConfig,
    Daily,
    DailyLabelTime,
    DayDefinition,
    ObservationStoreConfig,
    ProductConfig,
    ProviderConfig,
    SourceCoordinates,
    Unit,
    UnknownTemporalSupport,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId


@dataclass(frozen=True, slots=True)
class ClDgaSourceCoordinates:
    """The publisher historical CSV ZIP archive and value column compiled for one product."""

    archive_filename: str
    value_column: str


DAILY_HEADER: Final[tuple[str, ...]] = (
    "CODIGO ESTACION",
    "NOMBRE ESTACION",
    "COD_REGION",
    "REGION",
    "COMUNA",
    "LAT",
    "LONG",
    "UTM_ESTE",
    "UTM_NORTE",
    "ALTITUD",
    "FECHA",
    "Caudal_diario",
    "Unidad",
)

MONTHLY_HEADER: Final[tuple[str, ...]] = (
    "CODIGO ESTACION",
    "NOMBRE ESTACION",
    "COD_REGION",
    "REGION",
    "COMUNA",
    "LAT",
    "LONG",
    "UTM_ESTE",
    "UTM_NORTE",
    "ALTITUD",
    "Año",
    "Mes",
    "Caudal_Medio_mensual",
    "Unidad",
)


config: Final[ProviderConfig] = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_daily"): ProductConfig(
            coordinates=SourceCoordinates(
                ClDgaSourceCoordinates(
                    archive_filename="caudal_diario_historico.zip",
                    value_column="Caudal_diario",
                )
            ),
            unit=Unit.M3_S,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_monthly_mean"): ProductConfig(
            coordinates=SourceCoordinates(
                ClDgaSourceCoordinates(
                    archive_filename="caudal_medio_mensual_historico.zip",
                    value_column="Caudal_Medio_mensual",
                )
            ),
            unit=Unit.M3_S,
            semantics=UnknownTemporalSupport(),
        ),
    },
    cache=CacheConfig(store=ObservationStoreConfig(format_version=12)),
)
