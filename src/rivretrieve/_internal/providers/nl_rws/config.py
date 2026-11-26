"""Provider configuration, request coordinates, and window declarations for `nl_rws`."""

from __future__ import annotations

from dataclasses import dataclass

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
from rivretrieve._internal.providers.nl_rws.series import PRODUCT_BY_ID, PRODUCT_DEFINITIONS

_OBSERVED_PROPERTY_UNIT: dict[str, Unit] = {
    "discharge": Unit.M3_S,
    "stage": Unit.M,
    "water_temperature": Unit.DEG_C,
}

# Empirically validated 2026-11-26 across 5 gauges:
# - NVT at 90 days: 2.3–4.4 s, 3.8–7.9 MB (even with parallel F216+F230 series).
# - GEM24H at 3,650 days (~10 years): 0.6–1.1 s, 0.7–1.3 MB.
NVT_WINDOW_DAYS = 90
GEM24H_WINDOW_DAYS = 3650

SHARED_ACQUISITION_PRODUCTS: tuple[frozenset[ProductId], ...] = (
    frozenset({ProductId("discharge_m3s_nvt"), ProductId("discharge_m3s_gem24h")}),
    frozenset({ProductId("stage_nap_nvt"), ProductId("stage_nap_gem24h")}),
    frozenset({ProductId("water_temperature_nvt"), ProductId("water_temperature_gem24h")}),
)


@dataclass(frozen=True, slots=True)
class NlRwsProductCoordinates:
    """DDAPI 2.0 AquoMetadata query coordinates for one admitted nl_rws product."""

    product_id: str
    grootheid: str
    eenheid: str
    hoedanigheid: str
    waarde_bewerkings_methode: str

    def __post_init__(self) -> None:
        if self.product_id not in PRODUCT_BY_ID:
            raise FatalContractError(f"Unsupported nl_rws product_id: {self.product_id!r}")

    @property
    def shared_group_key(self) -> tuple[str, str, str]:
        return (self.grootheid, self.eenheid, self.hoedanigheid)


def config() -> ProviderConfig:
    """Build the ``nl_rws`` ``ProviderConfig`` for DDAPI 2.0 observation retrieval."""
    return ProviderConfig(
        zone=ZoneValue("+01:00"),
        products={
            ProductId(d.product_id): ProductConfig(
                SourceCoordinates(
                    NlRwsProductCoordinates(
                        product_id=d.product_id,
                        grootheid=d.grootheid,
                        eenheid=d.eenheid,
                        hoedanigheid=d.hoedanigheid,
                        waarde_bewerkings_methode=d.waarde_bewerkings_methode,
                    )
                ),
                _OBSERVED_PROPERTY_UNIT[d.observed_property],
                UnknownTemporalSupport(),
            )
            for d in PRODUCT_DEFINITIONS
        },
    )


def window_declarations() -> ProductWindowDeclarations:
    """Declare capped-span inclusive ISO-instant windows per nl_rws product."""
    nvt_declaration = WindowDeclaration(
        WindowGranularity("capped-span"),
        WindowRenderingVocabulary.ISO_INSTANT,
        StopConvention.INCLUSIVE,
        size=NVT_WINDOW_DAYS,
    )
    gem24h_declaration = WindowDeclaration(
        WindowGranularity("capped-span"),
        WindowRenderingVocabulary.ISO_INSTANT,
        StopConvention.INCLUSIVE,
        size=GEM24H_WINDOW_DAYS,
    )
    return ProductWindowDeclarations(
        {
            ProductId(d.product_id): gem24h_declaration if d.waarde_bewerkings_methode == "GEM24H" else nvt_declaration
            for d in PRODUCT_DEFINITIONS
        }
    )
