"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DayDefinition,
    Instant,
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
class FrHubeauSourceCoordinates:
    family: Literal["daily", "temperature", "hydroportail"]
    field: str
    entity_kind: Literal["station", "site"]


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_instantaneous"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("hydroportail", "Q", "site")), Unit.L_S, Instant()
        ),
        ProductId("stage_instantaneous"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("hydroportail", "H", "station")), Unit.MM, Instant()
        ),
        ProductId("discharge_daily_mean"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "QmnJ", "station")),
            Unit.L_S,
            Daily(DayDefinition("unknown")),
        ),
        ProductId("discharge_daily_max"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "QIXnJ", "station")),
            Unit.L_S,
            Daily(DayDefinition("unknown")),
        ),
        ProductId("stage_daily_max"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "HIXnJ", "station")),
            Unit.MM,
            Daily(DayDefinition("unknown")),
        ),
        ProductId("water_temperature_instantaneous"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("temperature", "resultat", "station")), Unit.DEG_C, Instant()
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
