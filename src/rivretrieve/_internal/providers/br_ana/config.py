"""ANA adopted telemetry declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
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
class BrAnaSourceCoordinates:
    """The adopted telemetry field published by ANA, not a quality classification."""

    field: Literal["Cota_Adotada", "Vazao_Adotada"]

    def __post_init__(self) -> None:
        if self.field not in ("Cota_Adotada", "Vazao_Adotada"):
            raise ValueError("ANA adopted telemetry field must be Cota_Adotada or Vazao_Adotada")


# ANA manual PDF page 11: Cota_Adotada (cm), Vazao_Adotada (m3/s),
# Data_Hora_Medicao = measurement/collection time. No source zone is established.
_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_instantaneous"): ProductConfig(
            SourceCoordinates(BrAnaSourceCoordinates("Vazao_Adotada")),
            Unit.M3_S,
            Instant(),
        ),
        ProductId("stage_instantaneous"): ProductConfig(
            SourceCoordinates(BrAnaSourceCoordinates("Cota_Adotada")),
            Unit.CM,
            Instant(),
        ),
    },
)
# Current OpenAPI permits DIAS_30. Real overlapping requests establish a whole-day
# backward range INCLUDING the anchor date. Fixed spans avoid short-tail overlap.
_WINDOW = WindowDeclaration(
    WindowGranularity("fixed-backward-span"),
    WindowRenderingVocabulary.DATE,
    StopConvention.INCLUSIVE,
    30,
)
_WINDOWS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _WINDOW))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
