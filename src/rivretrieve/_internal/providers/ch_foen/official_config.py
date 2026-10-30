"""Official API route coordinates and request window declarations."""

from dataclasses import dataclass
from datetime import timedelta

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
from rivretrieve._internal.providers.ch_foen.official_series import ARCHIVE_ROUTES, PARAMETERS, product_id


@dataclass(frozen=True, slots=True)
class OfficialRoute:
    route: str
    parameter: str

    def __post_init__(self) -> None:
        product_id(self.route, self.parameter)


# Genuine adjacent-boundary controls establish this request-filter granularity.
# It does not describe observation cadence or claim finer filters are unsupported.
TIMESTAMP_PRECISION = timedelta(milliseconds=1)


def config() -> ProviderConfig:
    return ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId(product_id(route, parameter)): ProductConfig(
                SourceCoordinates(OfficialRoute(route, parameter)),
                {"Q": Unit.M3_S, "W": Unit.M, "WT": Unit.DEG_C}[parameter],
                UnknownTemporalSupport(),
            )
            for route in (*ARCHIVE_ROUTES, "data_live")
            for parameter in PARAMETERS
        },
    )


def window_declarations() -> ProductWindowDeclarations:
    declaration = WindowDeclaration(
        WindowGranularity("iso-instant"),
        WindowRenderingVocabulary.ISO_INSTANT,
        StopConvention.EXCLUSIVE,
        timestamp_precision=TIMESTAMP_PRECISION,
    )
    return ProductWindowDeclarations(dict.fromkeys(config().products, declaration))
