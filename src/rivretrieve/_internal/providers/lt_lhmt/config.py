"""lt_lhmt config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
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
class LtLhmtSourceCoordinates:
    native_field: Literal["waterDischarge", "waterLevel"]

    def __post_init__(self) -> None:
        if self.native_field not in ("waterDischarge", "waterLevel"):
            raise ValueError("native_field must name a Meteo.lt observation field")


_CONFIG = ProviderConfig(
    zone=ZoneValue("+00:00"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(LtLhmtSourceCoordinates("waterDischarge")),
            unit=Unit.M3_S,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(LtLhmtSourceCoordinates("waterLevel")),
            unit=Unit.CM,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
    },
    cache=None,
)
_MONTH = WindowDeclaration(
    granularity=WindowGranularity("year-month"),
    rendering=WindowRenderingVocabulary.YEAR_MONTH,
    stop_convention=StopConvention.INCLUSIVE,
)
_WINDOWS = ProductWindowDeclarations(products=dict.fromkeys(_CONFIG.products, _MONTH))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS


_HISTORICAL_EVIDENCE = (
    "https://api.meteo.lt/: Stoties istoriniai hidrologiniai duomenys; waterLevel/waterDischarge Vidurkis per parą and observationDateUtc",
    "tests/test_data/lt_lhmt_terms_licence.html: full publisher API documentation captured 2026-08-21",
)

SERIES_MAPPINGS = {
    "discharge_daily_mean": SeriesMapping(
        "lt_lhmt/waterDischarge",
        "discharge",
        "m3/s",
        "m3/s",
        "daily",
        "mean",
        None,
        "+00:00",
        evidence=_HISTORICAL_EVIDENCE,
        temporal_support="interval",
        label_time="00:00",
    ),
    "stage_daily_mean": SeriesMapping(
        "lt_lhmt/waterLevel",
        "stage",
        "cm",
        "cm",
        "daily",
        "mean",
        None,
        "+00:00",
        evidence=_HISTORICAL_EVIDENCE,
        temporal_support="interval",
        label_time="00:00",
    ),
}
