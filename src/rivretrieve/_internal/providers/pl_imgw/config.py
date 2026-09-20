"""PL IMGW declaration : ProviderConfig.

Contributed by: Thiago von Däniken
"""

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
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(ImgwSourceCoordinates("level_cm")),
            unit=Unit.CM,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("water_temperature_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(ImgwSourceCoordinates("temperature_c")),
            unit=Unit.DEG_C,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
    },
    cache=CacheConfig(store=ObservationStoreConfig(format_version=5)),
)
