"""fi_syke config/window_declarations : () -> ProviderConfig x ProductWindowDeclarations."""

from __future__ import annotations

from dataclasses import dataclass

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
from rivretrieve._internal.providers.fi_syke.series import PRODUCT_DEFINITIONS


@dataclass(frozen=True, slots=True)
class FiSykeSourceCoordinates:
    """The one OData entity set that publishes this product's values."""

    native_table: str

    def __post_init__(self) -> None:
        if self.native_table not in ("Virtaama", "Vedenkorkeus", "LampoPintavesi"):
            raise ValueError("fi_syke native table must be Virtaama, Vedenkorkeus or LampoPintavesi")


_CONFIG = ProviderConfig(
    # Aika carries no offset in any response checked, and TauluKuvaus states
    # nothing about it (step 3, #755) -- "unknown" is a valid ZoneValue for
    # exactly this situation, not a default filled in by assumption.
    zone=ZoneValue("unknown"),
    products={
        ProductId(d.product_id): ProductConfig(
            coordinates=SourceCoordinates(FiSykeSourceCoordinates(d.native_id)),
            unit=Unit(d.canonical_unit),
            # Every Aika value checked is midnight-stamped; the daily *statistic*
            # is unknown (step 1/#755), but the label time itself is a plain,
            # confirmed fact -- same shape lt_lhmt/config.py uses for this
            # situation.
            semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00:00")),
        )
        for d in PRODUCT_DEFINITIONS
    },
)

# SYKE's OData service pages at 500 rows via odata.nextLink when $top is
# omitted, and suppresses nextLink entirely when $top is supplied (confirmed
# live, 2026-11-08, on Virtaama/Vedenkorkeus/VedenkTasoTieto alike) -- so one
# logical request can cover an arbitrarily long range; fetch.py's own
# nextLink loop handles it, not engine-level window chunking. Aika ge/le
# bounds are both inclusive, confirmed live across an 11-year span.
_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("iso-instant"),
    rendering=WindowRenderingVocabulary.ISO_INSTANT,
    stop_convention=StopConvention.INCLUSIVE,
)
_WINDOW_DECLARATIONS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _WINDOW))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOW_DECLARATIONS
