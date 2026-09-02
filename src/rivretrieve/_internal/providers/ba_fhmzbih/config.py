"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
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


@dataclass(frozen=True, slots=True)
class BaFhmzbihSourceCoordinates:
    code: Literal["Q", "H", "WT"]
    workbook: Literal["Q_1Y.xlsx", "H_1Y.xlsx", "Tvode_1Y.xlsx"]
    source_parameter: str
    source_unit: str


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_reported"): ProductConfig(
            SourceCoordinates(BaFhmzbihSourceCoordinates("Q", "Q_1Y.xlsx", "Proticaj", "m³/s")),
            Unit.M3_S,
            UnknownTemporalSupport(),
        ),
        ProductId("stage_reported"): ProductConfig(
            SourceCoordinates(BaFhmzbihSourceCoordinates("H", "H_1Y.xlsx", "Vodostaj", "cm")),
            Unit.CM,
            UnknownTemporalSupport(),
        ),
        ProductId("water_temperature_reported"): ProductConfig(
            SourceCoordinates(BaFhmzbihSourceCoordinates("WT", "Tvode_1Y.xlsx", "Temperatura vode", "°C")),
            Unit.DEG_C,
            UnknownTemporalSupport(),
        ),
    },
)
_SOURCE_FIXED = WindowDeclaration(WindowGranularity("none"), WindowRenderingVocabulary.NONE, StopConvention.INCLUSIVE)
_WINDOWS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _SOURCE_FIXED))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
