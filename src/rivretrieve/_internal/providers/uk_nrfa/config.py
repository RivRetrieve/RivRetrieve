"""NRFA source coordinates, window declarations, and shared peak-metadata policy."""

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
    UnknownTemporalSupport,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.uk_nrfa.series import PEAK_REJECTED_PERIOD_PRODUCTS, PRODUCT_IDS

_STAGE_PRODUCTS: frozenset[str] = frozenset({"gauging-stage", "amax-stage", "pot-stage"})
_DAILY_PRODUCTS: frozenset[str] = frozenset({"gdf", "ndf"})
_MONTHLY_PRODUCTS: frozenset[str] = frozenset({"gmf", "nmf"})


@dataclass(frozen=True, slots=True)
class UkNrfaPeakMetadataCoordinates:
    """Shared per-station ``/station-info`` peak-flow rejection metadata prerequisite."""


@dataclass(frozen=True, slots=True)
class UkNrfaSourceCoordinates:
    """NRFA ``/time-series`` route coordinates for one advertised data type."""

    data_type: str
    peak_metadata_content: bytes | None = None

    def __post_init__(self) -> None:
        if self.data_type not in PRODUCT_IDS:
            raise FatalContractError(f"Unsupported uk_nrfa data-type: {self.data_type!r}")
        if self.peak_metadata_content is not None and (
            self.data_type not in PEAK_REJECTED_PERIOD_PRODUCTS or not isinstance(self.peak_metadata_content, bytes)
        ):
            raise FatalContractError(
                f"uk_nrfa peak_metadata_content is only valid for peak products with bytes: {self.data_type!r}"
            )


def _product_semantics(product_id: str) -> Daily | UnknownTemporalSupport:
    # Daily products use calendar-date selection with unknown water-day definition.
    if product_id in _DAILY_PRODUCTS:
        return Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))
    return UnknownTemporalSupport()


# NRFA Terms clause 3.5 bounds client caching to <= 30 days separately from source availability.
_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId(pid): ProductConfig(
            coordinates=SourceCoordinates(UkNrfaSourceCoordinates(data_type=pid)),
            unit=Unit.M if pid in _STAGE_PRODUCTS else Unit.M3_S,
            semantics=_product_semantics(pid),
        )
        for pid in PRODUCT_IDS
    },
    cache=None,
)

# Inclusive YYYY-MM-DD covers intraday events and avoids HTTP 400 on microsecond ISO timestamps.
_DATE_WINDOW = WindowDeclaration(
    WindowGranularity("date"),
    WindowRenderingVocabulary.DATE,
    StopConvention.INCLUSIVE,
)
# Monthly /time-series compares bounds against month-end and silently drops partial trailing months.
_UNWINDOWED_MONTHLY = WindowDeclaration(
    WindowGranularity("none"),
    WindowRenderingVocabulary.NONE,
    StopConvention.INCLUSIVE,
)

_WINDOW_DECLARATIONS = ProductWindowDeclarations(
    {ProductId(pid): (_UNWINDOWED_MONTHLY if pid in _MONTHLY_PRODUCTS else _DATE_WINDOW) for pid in PRODUCT_IDS}
)

# Deduplicate the shared station-info peak-flow-metadata lookup across co-requested peak products.
SHARED_ACQUISITION_PRODUCTS: tuple[frozenset[ProductId], ...] = (
    frozenset(ProductId(pid) for pid in PEAK_REJECTED_PERIOD_PRODUCTS),
)


def config() -> ProviderConfig:
    """Return the ``uk_nrfa`` provider configuration across all ten API products."""
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    """Return evidence-backed request window declarations for ``uk_nrfa`` products."""
    return _WINDOW_DECLARATIONS


__all__ = (
    "SHARED_ACQUISITION_PRODUCTS",
    "UkNrfaPeakMetadataCoordinates",
    "UkNrfaSourceCoordinates",
    "config",
    "window_declarations",
)
