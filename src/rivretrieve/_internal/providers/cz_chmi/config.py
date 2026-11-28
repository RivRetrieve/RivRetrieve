"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    Hourly,
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
from rivretrieve._internal.provider_series import SeriesMapping


@dataclass(frozen=True, slots=True)
class CzChmiRequestCoordinates:
    """The annual file and selected native series represented by one source call."""

    file_code: str
    ts_con_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.file_code not in ("DQ", "HQ"):
            raise ValueError("CHMI request file code must be DQ or HQ")
        if not self.ts_con_ids or len(self.ts_con_ids) != len(set(self.ts_con_ids)):
            raise ValueError("CHMI request native series must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class CzChmiSourceCoordinates:
    file_code: Literal["DQ", "HQ"]
    ts_con_id: Literal["HD", "QD", "TD", "HH", "QH"]

    def __post_init__(self) -> None:
        if self.file_code not in ("DQ", "HQ"):
            raise ValueError("CHMI file code must be DQ or HQ")
        allowed = {"DQ": {"HD", "QD", "TD"}, "HQ": {"HH", "QH"}}
        if self.ts_con_id not in allowed[self.file_code]:
            raise ValueError("CHMI time-series id does not belong to its file code")


_CONFIG = ProviderConfig(
    zone=ZoneValue("+00:00"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("DQ", "QD")),
            Unit.M3_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("DQ", "HD")),
            Unit.CM,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("water_temperature_daily_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("DQ", "TD")),
            Unit.DEG_C,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_hourly_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("HQ", "QH")), Unit.M3_S, Hourly(IntervalDefinition("unknown"))
        ),
        ProductId("stage_hourly_mean"): ProductConfig(
            SourceCoordinates(CzChmiSourceCoordinates("HQ", "HH")), Unit.CM, Hourly(IntervalDefinition("unknown"))
        ),
    },
)

_ANNUAL = WindowDeclaration(WindowGranularity("year"), WindowRenderingVocabulary.YEAR, StopConvention.INCLUSIVE)
_WINDOWS = ProductWindowDeclarations(products=dict.fromkeys(_CONFIG.products, _ANNUAL))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS


# Publisher dictionary defines means and units; response labels explicitly carry UTC.
def _evidence(code: str, family: str) -> tuple[str, ...]:
    return (
        f"https://opendata.chmi.cz/hydrology/historical/metadata/meta2.json: {code} TSCON_DS, UNIT_ID, UNIT_DS",
        "tests/test_data/cz_meta2.json",
        f"tests/test_data/cz_chmi_0-203-1-000400_{family}_2023.recording.json: tsConID, unit and DT UTC Z labels",
    )


SERIES_MAPPINGS = {
    "discharge_daily_mean": SeriesMapping(
        "cz_chmi/QD",
        "discharge",
        "M3_S",
        "m3/s",
        "P1D",
        "mean",
        "QD",
        "+00:00",
        evidence=_evidence("QD", "DQ"),
        temporal_support="interval",
        label_time="00:00",
    ),
    "stage_daily_mean": SeriesMapping(
        "cz_chmi/HD",
        "stage",
        "CM",
        "cm",
        "P1D",
        "mean",
        "HD",
        "+00:00",
        evidence=_evidence("HD", "DQ"),
        temporal_support="interval",
        label_time="00:00",
    ),
    "water_temperature_daily_mean": SeriesMapping(
        "cz_chmi/TD",
        "temperature",
        "0C",
        "degC",
        "P1D",
        "mean",
        "TD",
        "+00:00",
        evidence=_evidence("TD", "DQ"),
        temporal_support="interval",
        label_time="00:00",
    ),
    "discharge_hourly_mean": SeriesMapping(
        "cz_chmi/QH",
        "discharge",
        "M3_S",
        "m3/s",
        "PT1H",
        "mean",
        "QH",
        "+00:00",
        evidence=_evidence("QH", "HQ"),
        temporal_support="interval",
    ),
    "stage_hourly_mean": SeriesMapping(
        "cz_chmi/HH",
        "stage",
        "CM",
        "cm",
        "PT1H",
        "mean",
        "HH",
        "+00:00",
        evidence=_evidence("HH", "HQ"),
        temporal_support="interval",
    ),
}
