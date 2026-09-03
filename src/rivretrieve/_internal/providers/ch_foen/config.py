"""ch_foen config : () → ProviderConfig × RestWindowDeclarations × FluxWindowDeclarations.

Contributed by: Nicolas Lazaro
"""

from __future__ import annotations

from dataclasses import dataclass

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
class NativeField:
    name: str
    unit: Unit


@dataclass(frozen=True, slots=True)
class ChFoenSourceCoordinates:
    fields: tuple[NativeField, ...]


@dataclass(frozen=True, slots=True)
class ChFoenRequestCoordinates:
    fields: tuple[str, ...]


_CONFIG = ProviderConfig(
    zone=ZoneValue("+00:00"),
    products={
        ProductId("discharge_reported"): ProductConfig(
            SourceCoordinates(ChFoenSourceCoordinates((NativeField("flow", Unit.M3_S),))),
            Unit.M3_S,
            UnknownTemporalSupport(),
        ),
        ProductId("stage_reported"): ProductConfig(
            SourceCoordinates(
                ChFoenSourceCoordinates((NativeField("height_abs", Unit.M), NativeField("height", Unit.M)))
            ),
            Unit.M,
            UnknownTemporalSupport(),
        ),
        ProductId("water_temperature_reported"): ProductConfig(
            SourceCoordinates(ChFoenSourceCoordinates((NativeField("temperature", Unit.DEG_C),))),
            Unit.DEG_C,
            UnknownTemporalSupport(),
        ),
    },
)
_WINDOW = WindowDeclaration(
    WindowGranularity("iso-instant"), WindowRenderingVocabulary.ISO_INSTANT, StopConvention.INCLUSIVE
)
_WINDOWS = ProductWindowDeclarations(products=dict.fromkeys(_CONFIG.products, _WINDOW))
_FLUX_WINDOW = WindowDeclaration(
    WindowGranularity("iso-instant"), WindowRenderingVocabulary.ISO_INSTANT, StopConvention.EXCLUSIVE
)
_FLUX_WINDOWS = ProductWindowDeclarations(products=dict.fromkeys(_CONFIG.products, _FLUX_WINDOW))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS


def flux_window_declarations() -> ProductWindowDeclarations:
    return _FLUX_WINDOWS
