"""Belgium - Wallonia (`be_wal`) KiWIS route coordinates and window declarations."""

from __future__ import annotations

from dataclasses import dataclass

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
    UnknownTemporalSupport,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.be_wal.series import PRODUCT_BY_ID, PRODUCT_SPECS, ProductSpec, validate_ts_id


@dataclass(frozen=True, slots=True)
class BeWalTimeseriesListCoordinates:
    """Uncatalogued KiWIS ``getTimeseriesList`` lookup coordinates for one native ``ts_name``."""

    product_id: str
    native_id: str

    def __post_init__(self) -> None:
        spec = PRODUCT_BY_ID.get(self.product_id)
        if spec is None or spec.native_id != self.native_id:
            raise FatalContractError(
                f"Invalid be_wal getTimeseriesList coordinates: product_id={self.product_id!r}, native_id={self.native_id!r}"
            )


@dataclass(frozen=True, slots=True)
class BeWalTimeseriesValuesCoordinates:
    """KiWIS ``getTimeseriesValues`` coordinates for one admitted SPW product and optional ``ts_id``."""

    product_id: str
    ts_id: str | None = None

    def __post_init__(self) -> None:
        if self.product_id not in PRODUCT_BY_ID:
            raise FatalContractError(f"Unsupported be_wal product_id: {self.product_id!r}")
        if self.ts_id is not None:
            validate_ts_id(self.ts_id)


_UNITS: dict[str, Unit] = {
    "m3/s": Unit.M3_S,
    "m": Unit.M,
    "degC": Unit.DEG_C,
}


def _semantics(spec: ProductSpec) -> Daily | Hourly | UnknownTemporalSupport:
    """Return engine temporal semantics matching SPW fixed CET (+01:00) start-anchored series."""
    if spec.frequency == "daily":
        return Daily(DayDefinition("00:00"), DailyLabelTime("00:00:00"))
    if spec.frequency == "hourly":
        return Hourly(IntervalDefinition("unknown"))
    return UnknownTemporalSupport()


def _window_declaration(spec: ProductSpec) -> WindowDeclaration:
    """Return bounded chunking rules for KiWIS ``getTimeseriesValues`` UTC range filters.

    - ``05-*.Complet`` (down to 5-min ~105k rows/yr) chunks at 365 days because multi-decade
      requests fail with HTTP 500 ``DatasourceError``.
    - ``10/11/12-*.1h.*`` hourly series chunk at 3650 days (10 years).
    - ``20/21/22`` daily, ``40/41/42`` monthly, and ``50/51/52`` yearly series use unbounded
      single ``iso-instant`` inclusive spans.
    """
    if spec.frequency is None:
        return WindowDeclaration(
            granularity=WindowGranularity("capped-span"),
            rendering=WindowRenderingVocabulary.ISO_INSTANT,
            stop_convention=StopConvention.INCLUSIVE,
            size=365,
        )
    if spec.frequency == "hourly":
        return WindowDeclaration(
            granularity=WindowGranularity("capped-span"),
            rendering=WindowRenderingVocabulary.ISO_INSTANT,
            stop_convention=StopConvention.INCLUSIVE,
            size=3650,
        )
    return WindowDeclaration(
        granularity=WindowGranularity("iso-instant"),
        rendering=WindowRenderingVocabulary.ISO_INSTANT,
        stop_convention=StopConvention.INCLUSIVE,
    )


_CONFIG = ProviderConfig(
    zone=ZoneValue("+01:00"),
    products={
        ProductId(spec.product_id): ProductConfig(
            coordinates=SourceCoordinates(BeWalTimeseriesValuesCoordinates(spec.product_id)),
            unit=_UNITS[spec.normalized_unit],
            semantics=_semantics(spec),
        )
        for spec in PRODUCT_SPECS
    },
)

_WINDOW_DECLARATIONS = ProductWindowDeclarations(
    {ProductId(spec.product_id): _window_declaration(spec) for spec in PRODUCT_SPECS}
)


def config() -> ProviderConfig:
    """Return Belgium - Wallonia (`be_wal`) configured observation products."""
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    """Return per-product KiWIS request windowing contracts for all 62 products."""
    return _WINDOW_DECLARATIONS


__all__ = [
    "BeWalTimeseriesListCoordinates",
    "BeWalTimeseriesValuesCoordinates",
    "config",
    "window_declarations",
]
