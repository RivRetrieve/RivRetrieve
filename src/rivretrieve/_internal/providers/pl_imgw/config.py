"""PL IMGW declaration : ProviderConfig."""

from dataclasses import dataclass
from typing import Final

from rivretrieve._internal.engine import (
    CacheConfig,
    Daily,
    DayDefinition,
    ObservationStoreConfig,
    ProductConfig,
    ProviderConfig,
    SourceCoordinates,
    Unit,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId


@dataclass(frozen=True, slots=True)
class ImgwSourceCoordinates:
    """The publisher CSV value column compiled for one product."""

    column: str


config: Final[ProviderConfig] = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(ImgwSourceCoordinates("flow_m3s")),
            unit=Unit.M3_S,
            semantics=Daily(DayDefinition("unknown")),
        ),
        ProductId("stage_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(ImgwSourceCoordinates("level_cm")),
            unit=Unit.CM,
            semantics=Daily(DayDefinition("unknown")),
        ),
        ProductId("water_temperature_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(ImgwSourceCoordinates("temperature_c")),
            unit=Unit.DEG_C,
            semantics=Daily(DayDefinition("unknown")),
        ),
    },
    cache=CacheConfig(store=ObservationStoreConfig(format_version=1)),
)
