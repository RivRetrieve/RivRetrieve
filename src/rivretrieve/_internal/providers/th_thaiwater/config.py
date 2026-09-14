"""th_thaiwater config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

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
class ThThaiWaterSourceCoordinates:
    native_field: Literal["discharge", "value"]

    def __post_init__(self) -> None:
        if self.native_field not in ("discharge", "value"):
            raise ValueError("native_field must name a ThaiWater graph field")


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_reported"): ProductConfig(
            coordinates=SourceCoordinates(ThThaiWaterSourceCoordinates("discharge")),
            unit=Unit.M3_S,
            semantics=UnknownTemporalSupport(),
        ),
        ProductId("stage_reported"): ProductConfig(
            coordinates=SourceCoordinates(ThThaiWaterSourceCoordinates("value")),
            unit=Unit.M,
            semantics=UnknownTemporalSupport(),
        ),
    },
    cache=None,
)
# Complete normal and leap-containing captures honour 365 inclusive SOURCE dates.
# This conservative working size is not a measured source maximum. The engine pads
# the user request before planning; the provider never adds or splits dates.
_GRAPH_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("capped-span"),
    rendering=WindowRenderingVocabulary.DATE,
    stop_convention=StopConvention.INCLUSIVE,
    size=365,
)
_WINDOWS = ProductWindowDeclarations(products=dict.fromkeys(_CONFIG.products, _GRAPH_WINDOW))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
