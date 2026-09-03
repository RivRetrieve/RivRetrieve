"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    Hourly,
    IntervalDefinition,
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
class CzChmiSourceCoordinates:
    file_code: Literal["DQ", "HQ"]
    ts_con_id: Literal["HD", "QD", "TD", "HH", "QH"]

    def __post_init__(self) -> None:
        if self.file_code not in ("DQ", "HQ"):
            raise ValueError("CHMI file code must be DQ or HQ")
        allowed = {"DQ": {"HD", "QD", "TD"}, "HQ": {"HH", "QH"}}
        if self.ts_con_id not in allowed[self.file_code]:
            raise ValueError("CHMI time-series id does not belong to its file code")


_CONFIG = ProviderConfig(
    zone=ZoneValue("+00:00"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("DQ", "QD")),
            Unit.M3_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("DQ", "HD")),
            Unit.CM,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("water_temperature_daily_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("DQ", "TD")),
            Unit.DEG_C,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_hourly_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("HQ", "QH")), Unit.M3_S, Hourly(IntervalDefinition("unknown"))
        ),
        ProductId("stage_hourly_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("HQ", "HH")), Unit.CM, Hourly(IntervalDefinition("unknown"))
        ),
    },
)

_ANNUAL = WindowDeclaration(WindowGranularity("year"), WindowRenderingVocabulary.YEAR, StopConvention.INCLUSIVE)
_WINDOWS = ProductWindowDeclarations(products=dict.fromkeys(_CONFIG.products, _ANNUAL))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
