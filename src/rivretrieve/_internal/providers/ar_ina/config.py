"""Argentina INA Alerta5 provider configuration and window declarations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from rivretrieve._internal.engine import (
    Hourly,
    Instant,
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
from rivretrieve._internal.providers.ar_ina.series import (
    IN_SCOPE_SERIES_SPECS,
    SPECS_BY_VAR_ID,
    SeriesProductSpec,
)

_UNITS: dict[str, Unit] = {
    "m3/s": Unit.M3_S,
    "m": Unit.M,
}


@dataclass(frozen=True, slots=True)
class ArInaSourceCoordinates:
    """INA Alerta5 punctual observation coordinates for one in-scope series route."""

    var_id: int
    proc_id: int
    published_series_id: int | None = None

    def __post_init__(self) -> None:
        if type(self.var_id) is not int or self.var_id not in SPECS_BY_VAR_ID:
            raise ValueError(f"var_id must name an in-scope INA Alerta5 variable: {self.var_id!r}")
        spec = SPECS_BY_VAR_ID[self.var_id]
        if type(self.proc_id) is not int or self.proc_id != spec.proc_id:
            raise ValueError(
                f"proc_id must match the in-scope observational procedure {spec.proc_id} for var_id={self.var_id}"
            )
        if self.published_series_id is not None and (
            type(self.published_series_id) is not int or self.published_series_id <= 0
        ):
            raise ValueError("published_series_id must be a positive integer or None")


@dataclass(frozen=True, slots=True)
class ArInaSeriesLookupCoordinates:
    """Prerequisite /obs/puntual/series lookup coordinates for one station and product."""

    var_id: int
    proc_id: int

    def __post_init__(self) -> None:
        if type(self.var_id) is not int or self.var_id not in SPECS_BY_VAR_ID:
            raise ValueError(f"var_id must name an in-scope INA Alerta5 variable: {self.var_id!r}")
        spec = SPECS_BY_VAR_ID[self.var_id]
        if type(self.proc_id) is not int or self.proc_id != spec.proc_id:
            raise ValueError(
                f"proc_id must match the in-scope observational procedure {spec.proc_id} for var_id={self.var_id}"
            )


def _semantics(spec: SeriesProductSpec) -> Instant | Hourly | UnknownTemporalSupport:
    if spec.is_instantaneous:
        return Instant()
    if spec.var_id == 85:
        return Hourly(IntervalDefinition("unknown"))
    # Daily, 4-hourly, weekly, and monthly interval series use start-anchored UTC
    # timestamps whose civil-midnight clock hour shifts between 03:00Z and 02:00Z
    # across pre-2009 Argentina DST. Concrete PhysicalFacts live in ar_ina.series.
    return UnknownTemporalSupport()


def _window_declaration(spec: SeriesProductSpec) -> WindowDeclaration:
    # INA Alerta5 filters /obs/puntual/series/{id}/observaciones by interval
    # containment: row.timestart >= timestart AND row.timeend <= timeend.
    # Extending rendered stop by the maximum interval duration (including +1h for
    # pre-2009 Argentina DST fall-back on midnight-cutoff periods) ensures every
    # start-anchored interval beginning inside RenderedWindow.bounds is returned.
    if spec.is_instantaneous:
        return WindowDeclaration(
            granularity=WindowGranularity("capped-span"),
            rendering=WindowRenderingVocabulary.ISO_INSTANT,
            stop_convention=StopConvention.INCLUSIVE,
            size=365,
        )
    if spec.var_id == 85:
        return WindowDeclaration(
            granularity=WindowGranularity("capped-span"),
            rendering=WindowRenderingVocabulary.ISO_INSTANT,
            stop_convention=StopConvention.INCLUSIVE,
            size=365,
            stop_extension=timedelta(hours=1),
        )
    if spec.var_id == 101:
        return WindowDeclaration(
            granularity=WindowGranularity("capped-span"),
            rendering=WindowRenderingVocabulary.ISO_INSTANT,
            stop_convention=StopConvention.INCLUSIVE,
            size=365,
            stop_extension=timedelta(hours=4),
        )
    if spec.frequency == "daily":
        return WindowDeclaration(
            granularity=WindowGranularity("capped-span"),
            rendering=WindowRenderingVocabulary.ISO_INSTANT,
            stop_convention=StopConvention.INCLUSIVE,
            size=3650,
            stop_extension=timedelta(hours=25),
        )
    if spec.var_id == 67:
        return WindowDeclaration(
            granularity=WindowGranularity("iso-instant"),
            rendering=WindowRenderingVocabulary.ISO_INSTANT,
            stop_convention=StopConvention.INCLUSIVE,
            stop_extension=timedelta(days=7, hours=1),
        )
    return WindowDeclaration(
        granularity=WindowGranularity("iso-instant"),
        rendering=WindowRenderingVocabulary.ISO_INSTANT,
        stop_convention=StopConvention.INCLUSIVE,
        stop_extension=timedelta(days=31, hours=1),
    )


_CONFIG = ProviderConfig(
    zone=ZoneValue("+00:00"),
    products={
        ProductId(spec.product_id): ProductConfig(
            coordinates=SourceCoordinates(ArInaSourceCoordinates(spec.var_id, spec.proc_id)),
            unit=_UNITS[spec.canonical_unit],
            semantics=_semantics(spec),
        )
        for spec in IN_SCOPE_SERIES_SPECS
    },
    cache=None,
)

_WINDOWS = ProductWindowDeclarations(
    products={ProductId(spec.product_id): _window_declaration(spec) for spec in IN_SCOPE_SERIES_SPECS}
)


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
