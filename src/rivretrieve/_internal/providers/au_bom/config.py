"""BoM KiWIS route coordinates, request windows and shared-acquisition grouping."""

from __future__ import annotations

from dataclasses import dataclass

from rivretrieve._internal.engine import (
    Hourly,
    IntervalDefinition,
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
from rivretrieve._internal.providers.au_bom.series import PRODUCT_DEFINITIONS

# ts_unitsymbol per quantity, confirmed live and stable across every admitted
# series checked (research/au-bom-source-access.md, 2026-11-03 retrieval pass).
# The reverse of series.py's _NORMALIZED_UNITS keys.
NATIVE_UNIT_SYMBOLS: dict[str, str] = {"discharge": "cumec", "stage": "m", "temperature": "°C"}

# ts_name alone is ambiguous: confirmed live, 2026-11-03, that station 410730's
# "DMQaQc.Merged.DailyMean.24HR" ts_name is shared by discharge, stage, pH,
# turbidity, conductivity and water temperature series alike, distinguished
# only by parametertype_name (the step-1 vision's original warning that
# lookups must filter on parametertype_name *and* ts_name, confirmed concretely
# against the prerequisite station-scoped list call this step introduces).
PARAMETERTYPE_NAMES: dict[str, str] = {
    "discharge": "Water Course Discharge",
    "stage": "Water Course Level",
    "temperature": "Water Temperature",
}


@dataclass(frozen=True, slots=True)
class AuBomTimeseriesListCoordinates:
    """Per-station ``getTimeseriesList`` prerequisite lookup resolving live ``ts_id`` values."""


@dataclass(frozen=True, slots=True)
class AuBomTimeseriesValuesCoordinates:
    """``getTimeseriesValues`` route for one product, identified by its native ``(ts_name, parametertype_name)``."""

    native_id: str
    parametertype_name: str


def _semantics(frequency: str) -> Hourly | UnknownTemporalSupport:
    """Product-level temporal semantics for au_bom.

    BoM's default getTimeseriesValues response serializes every timestamp in
    +10:00 while daily, monthly and yearly aggregations remain anchored to the
    contributing agency's local standard time (+08:00 in WA, +09:30 in SA/NT,
    +10:00 in eastern states; #1082). Under +10:00, 24HR daily rows therefore
    arrive at 00:00, 00:30 or 02:00 and 09HR rows at 09:00, 09:30 or 11:00, and
    two series at the same station can use different anchors (e.g. SA station
    A5131021). Daily products therefore cannot declare a single provider-wide
    DailyLabelTime and use UnknownTemporalSupport, while parse.py establishes
    each series's exact label_time on PhysicalFacts at response time. Hourly
    series have no established interval-label convention beyond "unknown".
    """
    if frequency == "PT1H":
        return Hourly(IntervalDefinition("unknown"))
    return UnknownTemporalSupport()


_CONFIG = ProviderConfig(
    zone=ZoneValue("+10:00"),
    products={
        ProductId(d.product_id): ProductConfig(
            coordinates=SourceCoordinates(
                AuBomTimeseriesValuesCoordinates(
                    native_id=d.native_id, parametertype_name=PARAMETERTYPE_NAMES[d.quantity]
                )
            ),
            unit=Unit(d.canonical_unit),
            semantics=_semantics(d.frequency),
        )
        for d in PRODUCT_DEFINITIONS
    },
)

# KiWIS getTimeseriesValues takes an inclusive from/to range; confirmed live,
# 2026-11-03, that both bounds are inclusive (a 3-row window from=X&to=X+2days
# returns X, X+1, X+2) and that a UTC "Z" instant is interpreted correctly
# against the source's own +10:00 labels (a 3-hour UTC window lands on the
# correct absolute local hours, not a naively-shifted one).
_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("iso-instant"),
    rendering=WindowRenderingVocabulary.ISO_INSTANT,
    stop_convention=StopConvention.INCLUSIVE,
)
_WINDOW_DECLARATIONS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _WINDOW))

# One getTimeseriesList call per station resolves every admitted product's
# live ts_id at once (confirmed live: a station-scoped list call with no
# parametertype_name filter returns all of that station's series in one
# response); sharing all 18 products avoids repeating it per product.
SHARED_ACQUISITION_PRODUCTS: tuple[frozenset[ProductId], ...] = (frozenset(_CONFIG.products),)


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOW_DECLARATIONS
