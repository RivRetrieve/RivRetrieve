"""Colombia IDEAM S3 route coordinates, source-fixed windows, and stage bindings."""

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
from rivretrieve._internal.providers.co_ideam.series import SERIES_SPECS, association_product


@dataclass(frozen=True, slots=True)
class CoIdeamS3CsvCoordinates:
    """Deterministic IDEAM S3 ``observaciones/historicos/csv`` object route."""

    etiqueta: str
    product_id: str

    def __post_init__(self) -> None:
        expected_product = association_product(self.etiqueta)
        if expected_product != self.product_id:
            raise FatalContractError(
                f"Invalid co_ideam S3 route coordinates: etiqueta={self.etiqueta!r}, product_id={self.product_id!r}"
            )


_NATIVE_UNITS: dict[str, Unit] = {
    "m3/s": Unit.M3_S,
    "cm": Unit.CM,
}

_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId(spec.product_id): ProductConfig(
            coordinates=SourceCoordinates(CoIdeamS3CsvCoordinates(etiqueta=spec.etiqueta, product_id=spec.product_id)),
            unit=_NATIVE_UNITS[spec.source_unit],
            semantics=UnknownTemporalSupport(),
        )
        for spec in SERIES_SPECS
    },
)

_SOURCE_FIXED_WINDOW = WindowDeclaration(
    WindowGranularity("none"),
    WindowRenderingVocabulary.NONE,
    StopConvention.INCLUSIVE,
)

_WINDOW_DECLARATIONS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _SOURCE_FIXED_WINDOW))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOW_DECLARATIONS
