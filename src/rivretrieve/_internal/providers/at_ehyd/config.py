"""Austria eHYD route coordinates, source-fixed windows, and stage bindings."""

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
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.at_ehyd.series import IN_SCOPE_OWF_FTYPES, association_product


@dataclass(frozen=True, slots=True)
class AtEhydInfoCoordinates:
    """Per-station ``Messstellen/info`` manifest lookup for ``owf`` file numbers."""


@dataclass(frozen=True, slots=True)
class AtEhydOwfCoordinates:
    """Validated ``Geprüfte Daten`` CSV route resolved via ``Messstellen/info``."""

    ftyp: str
    file_prefix: str

    def __post_init__(self) -> None:
        expected = IN_SCOPE_OWF_FTYPES.get(self.ftyp)
        if expected is None or expected[0] != self.file_prefix:
            raise FatalContractError(
                f"Invalid eHYD owf route coordinates: ftyp={self.ftyp!r}, file_prefix={self.file_prefix!r}"
            )


@dataclass(frozen=True, slots=True)
class AtEhydPegelCoordinates:
    """Unvalidated ``Pegel Aktuell`` JSON route (``pegelBgis`` or ``pegelLongterm``)."""

    subsystem: Literal["pegel_bgis", "pegel_longterm"]
    parameter: Literal["Abfluss", "Wasserstand"]

    def __post_init__(self) -> None:
        association_product(self.subsystem, self.parameter)


@dataclass(frozen=True, slots=True)
class AtEhydPegelEndpointCoordinates:
    """Shared ``Pegel Aktuell`` endpoint payload before per-parameter projection."""

    subsystem: Literal["pegel_bgis", "pegel_longterm"]

    def __post_init__(self) -> None:
        if self.subsystem not in ("pegel_bgis", "pegel_longterm"):
            raise FatalContractError(f"Invalid eHYD Pegel Aktuell subsystem: {self.subsystem!r}")


_NATIVE_UNITS: dict[str, Unit] = {
    "m³/s": Unit.M3_S,
    "cm": Unit.CM,
    "°C": Unit.DEG_C,
}

_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        **{
            ProductId(ftyp): ProductConfig(
                coordinates=SourceCoordinates(AtEhydOwfCoordinates(ftyp=ftyp, file_prefix=prefix)),
                unit=_NATIVE_UNITS[native_unit],
                semantics=UnknownTemporalSupport(),
            )
            for ftyp, (prefix, native_unit) in IN_SCOPE_OWF_FTYPES.items()
        },
        ProductId("pegel_bgis_abfluss"): ProductConfig(
            coordinates=SourceCoordinates(AtEhydPegelCoordinates("pegel_bgis", "Abfluss")),
            unit=Unit.M3_S,
            semantics=UnknownTemporalSupport(),
        ),
        ProductId("pegel_bgis_wasserstand"): ProductConfig(
            coordinates=SourceCoordinates(AtEhydPegelCoordinates("pegel_bgis", "Wasserstand")),
            unit=Unit.CM,
            semantics=UnknownTemporalSupport(),
        ),
        ProductId("pegel_longterm_abfluss"): ProductConfig(
            coordinates=SourceCoordinates(AtEhydPegelCoordinates("pegel_longterm", "Abfluss")),
            unit=Unit.M3_S,
            semantics=UnknownTemporalSupport(),
        ),
        ProductId("pegel_longterm_wasserstand"): ProductConfig(
            coordinates=SourceCoordinates(AtEhydPegelCoordinates("pegel_longterm", "Wasserstand")),
            unit=Unit.CM,
            semantics=UnknownTemporalSupport(),
        ),
    },
)

_SOURCE_FIXED_WINDOW = WindowDeclaration(
    WindowGranularity("none"),
    WindowRenderingVocabulary.NONE,
    StopConvention.INCLUSIVE,
)

_WINDOW_DECLARATIONS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _SOURCE_FIXED_WINDOW))

# Deduplicate Messstellen/info per station across owf products without coupling
# cached yearbook history to live Pegel Aktuell telemetry requests.
SHARED_ACQUISITION_PRODUCTS: tuple[frozenset[ProductId], ...] = (
    frozenset(ProductId(ftyp) for ftyp in IN_SCOPE_OWF_FTYPES),
    frozenset({ProductId("pegel_bgis_abfluss"), ProductId("pegel_bgis_wasserstand")}),
    frozenset({ProductId("pegel_longterm_abfluss"), ProductId("pegel_longterm_wasserstand")}),
)


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOW_DECLARATIONS
