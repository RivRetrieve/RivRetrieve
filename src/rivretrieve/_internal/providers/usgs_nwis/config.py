"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import re
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
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId


@dataclass(frozen=True, slots=True)
class UsgsNwisSourceCoordinates:
    endpoint: Literal["daily", "continuous"]
    parameter_code: str
    statistic_code: str | None
    monitoring_location_id: str | None = None

    def __post_init__(self) -> None:
        if self.monitoring_location_id is not None and (
            not isinstance(self.monitoring_location_id, str) or not self.monitoring_location_id.strip()
        ):
            raise ValueError("monitoring location identity must be a nonempty source string")
        if not isinstance(self.endpoint, str):
            raise TypeError("endpoint must be a string")
        if self.endpoint not in ("daily", "continuous"):
            raise ValueError("endpoint must be 'daily' or 'continuous'")
        if not isinstance(self.parameter_code, str):
            raise TypeError("parameter code must be a string")
        if re.fullmatch(r"[0-9]{5}", self.parameter_code) is None:
            raise ValueError("parameter code must be exactly five ASCII digits")
        if self.statistic_code is not None and not isinstance(self.statistic_code, str):
            raise TypeError("statistic code must be a string or None")
        if self.endpoint == "daily":
            if self.statistic_code is None or re.fullmatch(r"[0-9]{5}", self.statistic_code) is None:
                raise ValueError("Daily statistic code must be exactly five ASCII digits")
        elif self.statistic_code is not None:
            raise ValueError("Continuous statistic code must be None")


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("daily", "00060", "00003")),
            unit=Unit.FT3_S,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_instantaneous"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("continuous", "00060", None)),
            unit=Unit.FT3_S,
            semantics=Instant(),
        ),
        ProductId("stage_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("daily", "00065", "00003")),
            unit=Unit.FT,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_max"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("daily", "00065", "00001")),
            unit=Unit.FT,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_min"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("daily", "00065", "00002")),
            unit=Unit.FT,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_instantaneous"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("continuous", "00065", None)),
            unit=Unit.FT,
            semantics=Instant(),
        ),
    },
    cache=None,
)

_DATE_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("date"),
    rendering=WindowRenderingVocabulary.DATE,
    stop_convention=StopConvention.INCLUSIVE,
)
_CONTINUOUS_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("capped-span"),
    size=1100,
    rendering=WindowRenderingVocabulary.ISO_INSTANT,
    stop_convention=StopConvention.INCLUSIVE,
)
_WINDOW_DECLARATIONS = ProductWindowDeclarations(
    products={
        product: _CONTINUOUS_WINDOW
        if isinstance(definition.coordinates.value, UsgsNwisSourceCoordinates)
        and definition.coordinates.value.endpoint == "continuous"
        else _DATE_WINDOW
        for product, definition in _CONFIG.products.items()
    }
)


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOW_DECLARATIONS
