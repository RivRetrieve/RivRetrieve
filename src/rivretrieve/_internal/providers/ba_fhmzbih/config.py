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
from rivretrieve._internal.provider_series import SeriesMapping


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


# Explicit source access and physical mapping; not a completeness assertion.

SERIES_MAPPINGS = {
    "discharge_reported": SeriesMapping(
        "ba_fhmzbih/Q",
        "discharge",
        "m³/s",
        "m3/s",
        None,
        None,
        "81 Web Kontinuirani",
        None,
        evidence=(
            "tests/test_data/ba_fhmzbih_4024_Q_1Y.recording.json: workbook #Station Parameter Name=Proticaj, #Unit Symbol=m³/s, #Timeseries Name=81 Web Kontinuirani",
        ),
    ),
    "stage_reported": SeriesMapping(
        "ba_fhmzbih/H",
        "stage",
        "cm",
        "cm",
        None,
        None,
        "81 Web Kontinuirani",
        None,
        evidence=(
            "tests/test_data/ba_fhmzbih_4024_H_1Y.recording.json: workbook #Station Parameter Name=Vodostaj, #Unit Symbol=cm, #Timeseries Name=81 Web Kontinuirani",
        ),
    ),
    "water_temperature_reported": SeriesMapping(
        "ba_fhmzbih/WT",
        "temperature",
        "°C",
        "degC",
        None,
        None,
        "81 Web Kontinuirani",
        None,
        evidence=(
            "tests/test_data/ba_fhmzbih_4110_Tvode_1Y.recording.json: workbook #Station Parameter Name=Temperatura vode, #Unit Symbol=°C, #Timeseries Name=81 Web Kontinuirani",
        ),
    ),
}
