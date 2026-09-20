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
from rivretrieve._internal.provider_series import SeriesMapping


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


_GRAPH_EVIDENCE = (
    "https://www.thaiwater.net/dist/js/app.chunk.js: waterlevel_graph station_type=tele_waterlevel components and unit translations",
    "tests/test_data/th_thaiwater_official_app.chunk-2026-09-02.js",
    "tests/test_data/th_thaiwater_official_evidence_manifest-2026-09-02.json",
)

SERIES_MAPPINGS = {
    "discharge_reported": SeriesMapping(
        "th_thaiwater/discharge",
        "discharge",
        "m3/s",
        "m3/s",
        evidence=(*_GRAPH_EVIDENCE, "graph_data.discharge: ปริมาณน้ำท่า (ม.3/วิ.) / m3/second"),
    ),
    "stage_reported": SeriesMapping(
        "th_thaiwater/value",
        "stage",
        "m",
        "m",
        evidence=(*_GRAPH_EVIDENCE, "graph_data.value: ระดับน้ำ (ม.รทก) / Water Level (m MSL)"),
        vertical_reference="above_sea_level",
    ),
}
