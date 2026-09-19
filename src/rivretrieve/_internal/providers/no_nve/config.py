"""no_nve config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    Hourly,
    Instant,
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

_PARAMETERS = ("1000", "1001", "1003")
_RESOLUTION_TIMES = ("0", "60", "1440")
_METHODS = ("Mean", "Instantaneous")
# HydAPI publishes the unit string of each series; the canonical unit is fixed beside it.
_SOURCE_UNITS = {"m": Unit.M, "m³/s": Unit.M3_S, "°C": Unit.DEG_C}


@dataclass(frozen=True, slots=True)
class NoNveSourceCoordinates:
    """How HydAPI names one series: parameter, resolution, aggregation method and unit."""

    parameter: Literal["1000", "1001", "1003"]
    resolution_time: Literal["0", "60", "1440"]
    method: Literal["Mean", "Instantaneous"]
    source_unit: Literal["m", "m³/s", "°C"]
    version_number: int | None = None

    def __post_init__(self) -> None:
        if self.version_number is not None and type(self.version_number) is not int:
            raise TypeError("version_number must be an integer source selector or None")
        if self.parameter not in _PARAMETERS:
            raise ValueError("parameter must be a HydAPI observation parameter number")
        if self.resolution_time not in _RESOLUTION_TIMES:
            raise ValueError("resolution_time must be a HydAPI resolution time in minutes")
        if self.method not in _METHODS:
            raise ValueError("method must be a HydAPI series aggregation method")
        if self.source_unit not in _SOURCE_UNITS:
            raise ValueError("source_unit must be a HydAPI published unit")

    @property
    def unit(self) -> Unit:
        """Return the canonical unit this source unit denotes."""
        return _SOURCE_UNITS[self.source_unit]


def _product(
    parameter: Literal["1000", "1001", "1003"],
    resolution_time: Literal["0", "60", "1440"],
    method: Literal["Mean", "Instantaneous"],
    source_unit: Literal["m", "m³/s", "°C"],
) -> ProductConfig:
    coordinates = NoNveSourceCoordinates(parameter, resolution_time, method, source_unit)
    if resolution_time == "1440":
        # HydAPI stamps a day series 11:00Z; its day definition is contradicted by the
        # documentation itself and therefore stays unknown.
        semantics: Daily | Hourly | Instant = Daily(DayDefinition("unknown"), DailyLabelTime("11:00"))
    elif resolution_time == "60":
        semantics = Hourly(IntervalDefinition("unknown"))
    else:
        semantics = Instant()
    return ProductConfig(
        coordinates=SourceCoordinates(coordinates),
        unit=coordinates.unit,
        semantics=semantics,
    )


_CONFIG = ProviderConfig(
    zone=ZoneValue("+00:00"),
    products={
        ProductId("discharge_daily_mean"): _product("1001", "1440", "Mean", "m³/s"),
        ProductId("discharge_hourly_mean"): _product("1001", "60", "Mean", "m³/s"),
        ProductId("discharge_instantaneous"): _product("1001", "0", "Instantaneous", "m³/s"),
        ProductId("stage_daily_mean"): _product("1000", "1440", "Mean", "m"),
        ProductId("stage_hourly_mean"): _product("1000", "60", "Mean", "m"),
        ProductId("stage_instantaneous"): _product("1000", "0", "Instantaneous", "m"),
        ProductId("water_temperature_daily_mean"): _product("1003", "1440", "Mean", "°C"),
        ProductId("water_temperature_hourly_mean"): _product("1003", "60", "Mean", "°C"),
        ProductId("water_temperature_instantaneous"): _product("1003", "0", "Instantaneous", "°C"),
    },
    cache=None,
)

# ReferenceTime is one ISO-8601 interval whose two instants are both returned:
# ".../2023-03-27" ends at 2023-03-27T00:00:00Z and a day value stamped 11:00Z that
# date is absent, while ".../2023-03-27T23:59:59Z" returns it.
_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("iso-instant"),
    rendering=WindowRenderingVocabulary.ISO_INSTANT,
    stop_convention=StopConvention.INCLUSIVE,
)
_WINDOWS = ProductWindowDeclarations(products=dict.fromkeys(_CONFIG.products, _WINDOW))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
