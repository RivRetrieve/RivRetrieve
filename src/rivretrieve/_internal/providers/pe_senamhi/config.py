"""SENAMHI products and source request partitions."""

from rivretrieve._internal.engine import (
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    SourceCoordinates,
    Unit,
    UnknownTemporalSupport,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.pe_senamhi.fetch import SenamhiSourceCoordinates, window_declaration
from rivretrieve._internal.providers.pe_senamhi.series import MONTHLY_LEVEL_FIELDS

_COORDINATES = {
    ProductId(f"phisis_{resolution.lower()}_{variable.lower()}{suffix}"): SenamhiSourceCoordinates(
        "phisis", resolution, variable, unit
    )
    for resolution in ("DAILY", "HOURLY")
    for variable, unit, suffix in (
        ("FLOW", "m3/s", ""),
        ("LEVEL", "m", ""),
        ("LEVEL", "m.s.n.m", "_above_sea_level"),
    )
} | {
    ProductId(f"monthly_archive_{field.lower()}"): SenamhiSourceCoordinates("monthly_archive", None, field, "m")
    for field in sorted(MONTHLY_LEVEL_FIELDS)
}
_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        product: ProductConfig(
            SourceCoordinates(route),
            Unit.M3_S if route.variable == "FLOW" else Unit.M,
            UnknownTemporalSupport(),
        )
        for product, route in _COORDINATES.items()
    },
)
_WINDOWS = ProductWindowDeclarations({product: window_declaration(route) for product, route in _COORDINATES.items()})


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
