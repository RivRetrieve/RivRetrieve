"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    Instant,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownTemporalSupport,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import SeriesMapping


@dataclass(frozen=True, slots=True)
class FrHubeauSourceCoordinates:
    family: Literal["daily", "temperature", "hydroportail"]
    field: str


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_instantaneous"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("hydroportail", "Q")), Unit.L_S, Instant()
        ),
        ProductId("stage_instantaneous"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("hydroportail", "H")), Unit.MM, Instant()
        ),
        ProductId("discharge_daily_mean"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "QmnJ")),
            Unit.L_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_daily_max"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "QIXnJ")),
            Unit.L_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_max"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "HIXnJ")),
            Unit.MM,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("water_temperature_reported"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("temperature", "resultat")),
            Unit.DEG_C,
            UnknownTemporalSupport(),
        ),
    },
)
_DATE = WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)
_DMY = WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE_DMY, StopConvention.INCLUSIVE)
_WINDOWS = ProductWindowDeclarations(
    {
        product: (
            _DMY if product in {ProductId("discharge_instantaneous"), ProductId("stage_instantaneous")} else _DATE
        )
        for product in _CONFIG.products
    }
)


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS


# Explicit source access and physical mapping; not a completeness assertion.

SERIES_MAPPINGS = {
    "discharge_instantaneous": SeriesMapping(
        "fr_hubeau/hydroportail/Q", "discharge", "l", "l/s", "irregular", "instantaneous", "raw", "+00:00"
    ),
    "stage_instantaneous": SeriesMapping(
        "fr_hubeau/hydroportail/H", "stage", "mm", "mm", "irregular", "instantaneous", "raw", "+00:00"
    ),
    "discharge_daily_mean": SeriesMapping(
        "fr_hubeau/daily/QmnJ", "discharge", "l/s", "l/s", "daily", "mean", None, None
    ),
    "discharge_daily_max": SeriesMapping(
        "fr_hubeau/daily/QIXnJ", "discharge", "l/s", "l/s", "daily", "max", None, None
    ),
    "stage_daily_max": SeriesMapping("fr_hubeau/daily/HIXnJ", "stage", "mm", "mm", "daily", "max", None, None),
    "water_temperature_reported": SeriesMapping(
        "fr_hubeau/temperature/resultat", "temperature", "degC", "degC", None, None, None, None
    ),
}
