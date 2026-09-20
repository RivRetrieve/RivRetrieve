"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass

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
from rivretrieve._internal.provider_series import SeriesMapping


@dataclass(frozen=True, slots=True)
class JpMlitSourceCoordinates:
    kind: int

    def __post_init__(self) -> None:
        if type(self.kind) is not int or self.kind not in (2, 3, 6, 7):
            raise ValueError("MLIT KIND must be 2, 3, 6, or 7")


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("stage_hourly"): ProductConfig(
            SourceCoordinates(JpMlitSourceCoordinates(2)), Unit.M, Hourly(IntervalDefinition("unknown"))
        ),
        ProductId("stage_daily"): ProductConfig(
            SourceCoordinates(JpMlitSourceCoordinates(3)),
            Unit.M,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_hourly"): ProductConfig(
            SourceCoordinates(JpMlitSourceCoordinates(6)), Unit.M3_S, Hourly(IntervalDefinition("unknown"))
        ),
        ProductId("discharge_daily"): ProductConfig(
            SourceCoordinates(JpMlitSourceCoordinates(7)),
            Unit.M3_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
    },
)
_MONTH = WindowDeclaration(WindowGranularity("year-month"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)
_YEAR = WindowDeclaration(WindowGranularity("year"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)
_WINDOWS = ProductWindowDeclarations(
    products={
        ProductId("stage_hourly"): _MONTH,
        ProductId("stage_daily"): _YEAR,
        ProductId("discharge_hourly"): _MONTH,
        ProductId("discharge_daily"): _YEAR,
    }
)


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS


# Explicit source access and physical mapping; not a completeness assertion.

SERIES_MAPPINGS = {
    "stage_hourly": SeriesMapping("jp_mlit/KIND/2", "stage", "m", "m", "hourly", None, None, None),
    "stage_daily": SeriesMapping("jp_mlit/KIND/3", "stage", "m", "m", "daily", None, None, None),
    "discharge_hourly": SeriesMapping("jp_mlit/KIND/6", "discharge", "m3/s", "m3/s", "hourly", None, None, None),
    "discharge_daily": SeriesMapping("jp_mlit/KIND/7", "discharge", "m3/s", "m3/s", "daily", None, None, None),
}
