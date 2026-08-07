"""CA ECCC declaration : ProviderConfig × ProductWindowDeclarations."""

from dataclasses import dataclass
from typing import Final

from rivretrieve._internal.engine import (
    CacheConfig,
    Daily,
    DayDefinition,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    SourceCoordinates,
    StopConvention,
    Unit,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
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
            semantics=Daily(DayDefinition("unknown")),
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
            semantics=Daily(DayDefinition("unknown")),
        ),
    },
    cache=CacheConfig(),
)

_YEAR_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("year"),
    rendering=WindowRenderingVocabulary.YEAR,
    stop_convention=StopConvention.INCLUSIVE,
)
window_declarations: Final[ProductWindowDeclarations] = ProductWindowDeclarations(
    products=dict.fromkeys(config.products, _YEAR_WINDOW)
)
