"""za_dws config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

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

type ZaDwsDataType = Literal["Daily", "Point"]
type ZaDwsColumn = Literal["D AVG F/R", "COR.LEVEL", "COR.FLOW"]

_COLUMNS_BY_DATA_TYPE: dict[str, frozenset[str]] = {
    "Daily": frozenset({"D AVG F/R"}),
    "Point": frozenset({"COR.LEVEL", "COR.FLOW"}),
}


@dataclass(frozen=True, slots=True)
class ZaDwsSourceCoordinates:
    """One HyData.aspx DataType and the header label of the column parse reads from it."""

    data_type: ZaDwsDataType
    column: ZaDwsColumn

    def __post_init__(self) -> None:
        if self.data_type not in _COLUMNS_BY_DATA_TYPE:
            raise ValueError("data_type must be a DWS HyData DataType: Daily or Point")
        if self.column not in _COLUMNS_BY_DATA_TYPE[self.data_type]:
            raise ValueError(f"column {self.column!r} is not published by DataType={self.data_type}")


# The source publishes bare wall-clock dates and times and states no time standard on the
# HyData.aspx page or in its format legend, so every row carries an unknown zone (ADR 0007).
_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(ZaDwsSourceCoordinates("Daily", "D AVG F/R")),
            unit=Unit.M3_S,
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_instantaneous"): ProductConfig(
            coordinates=SourceCoordinates(ZaDwsSourceCoordinates("Point", "COR.FLOW")),
            unit=Unit.M3_S,
            semantics=Instant(),
        ),
        ProductId("stage_instantaneous"): ProductConfig(
            coordinates=SourceCoordinates(ZaDwsSourceCoordinates("Point", "COR.LEVEL")),
            unit=Unit.M,
            semantics=Instant(),
        ),
    },
    cache=None,
)

# The two real 2020 responses kept as legacy reference both end one day before their EndDT
# (EndDT=2020-01-31 → last daily row 20200130; EndDT=2020-01-03 → last point row 20200102),
# so the rendered stop is declared exclusive. The chunk sizes restate the retired port's
# unverified claims (Daily ≈ 20 years, Point ≈ 1 year per request); see the port notes.
_DAILY_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("n-year-chunk"),
    rendering=WindowRenderingVocabulary.DATE,
    stop_convention=StopConvention.EXCLUSIVE,
    size=20,
)
_POINT_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("n-year-chunk"),
    rendering=WindowRenderingVocabulary.DATE,
    stop_convention=StopConvention.EXCLUSIVE,
    size=1,
)
_WINDOWS = ProductWindowDeclarations(
    products={
        ProductId("discharge_daily_mean"): _DAILY_WINDOW,
        ProductId("discharge_instantaneous"): _POINT_WINDOW,
        ProductId("stage_instantaneous"): _POINT_WINDOW,
    }
)


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
