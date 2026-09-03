"""CA ECCC declaration : ProviderConfig × ProductWindowDeclarations.

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
class HydatSourceCoordinates:
    table_name: str
    value_prefix: str
    symbol_prefix: str


config: Final[ProviderConfig] = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(
                HydatSourceCoordinates(
                    table_name="DLY_FLOWS",
                    value_prefix="FLOW",
                    symbol_prefix="FLOW_SYMBOL",
                )
            ),
            unit=Unit.M3_S,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(
                HydatSourceCoordinates(
                    table_name="DLY_LEVELS",
                    value_prefix="LEVEL",
                    symbol_prefix="LEVEL_SYMBOL",
                )
            ),
            unit=Unit.M,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
    },
    cache=CacheConfig(store=ObservationStoreConfig(format_version=2)),
)
