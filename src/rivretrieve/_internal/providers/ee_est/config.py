"""Estonia (`ee_est`) product config, native source coordinates, and window declarations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, cast

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
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ee_est.series import EM_KEY_TO_PRODUCT, FH_AEGRIDA_TO_PRODUCT, PRODUCT_SPECS


@dataclass(frozen=True, slots=True)
class EstModelCoordinates:
    """EstModel daily measurement endpoint coordinates (estmodel.envir.ee)."""

    parameter: Literal["Q", "H", "T"]
    aggregation_type: Literal["MEAN", "MAXIMUM", "MINIMUM"]
    product_id: str

    def __post_init__(self) -> None:
        spec = EM_KEY_TO_PRODUCT.get((self.parameter, self.aggregation_type))
        if spec is None or spec.product_id != self.product_id:
            raise FatalContractError(
                f"Invalid ee_est EstModel coordinates: parameter={self.parameter!r}, "
                f"aggregation_type={self.aggregation_type!r}, product_id={self.product_id!r}"
            )


@dataclass(frozen=True, slots=True)
class FHydroseireCoordinates:
    """Keskkonnaandmed PostgREST hourly `f_hydroseire` coordinates."""

    aegrida_nimi: Literal[
        "Äravool avg",
        "Äravool max",
        "Äravool min",
        "WL avg",
        "WL max",
        "WL min",
        "WT avg",
        "WT max",
        "WT min",
    ]
    product_id: str
    jaam_kood: int | None = None

    def __post_init__(self) -> None:
        spec = FH_AEGRIDA_TO_PRODUCT.get(self.aegrida_nimi)
        if spec is None or spec.product_id != self.product_id:
            raise FatalContractError(
                f"Invalid ee_est f_hydroseire coordinates: aegrida_nimi={self.aegrida_nimi!r}, "
                f"product_id={self.product_id!r}"
            )
        if self.jaam_kood is not None and (type(self.jaam_kood) is not int or self.jaam_kood <= 0):
            raise FatalContractError(f"ee_est jaam_kood must be a positive integer or None: {self.jaam_kood!r}")


_UNITS: dict[str, Unit] = {
    "m3/s": Unit.M3_S,
    "m": Unit.M,
    "cm": Unit.CM,
    "degC": Unit.DEG_C,
}


def _product_config(spec_index: int) -> ProductConfig:
    spec = PRODUCT_SPECS[spec_index]
    if spec.source_api == "estmodel":
        assert spec.em_parameter is not None and spec.em_type is not None
        coords: EstModelCoordinates | FHydroseireCoordinates = EstModelCoordinates(
            parameter=cast('Literal["Q", "H", "T"]', spec.em_parameter),
            aggregation_type=cast('Literal["MEAN", "MAXIMUM", "MINIMUM"]', spec.em_type),
            product_id=spec.product_id,
        )
        semantics: Daily | Hourly = Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))
    else:
        assert spec.fh_aegrida_nimi is not None
        coords = FHydroseireCoordinates(
            aegrida_nimi=cast(
                'Literal["Äravool avg", "Äravool max", "Äravool min", "WL avg", "WL max", "WL min", "WT avg", "WT max", "WT min"]',
                spec.fh_aegrida_nimi,
            ),
            product_id=spec.product_id,
        )
        semantics = Hourly(IntervalDefinition("unknown"))
    return ProductConfig(
        coordinates=SourceCoordinates(coords),
        unit=_UNITS[spec.source_unit],
        semantics=semantics,
    )


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={ProductId(spec.product_id): _product_config(index) for index, spec in enumerate(PRODUCT_SPECS)},
)

# EstModel daily series span up to 160 years (1867..present) and query whole
# calendar years via integer start-year/end-year without timezone drift.
_EM_WINDOW = WindowDeclaration(
    WindowGranularity("n-year-chunk"),
    WindowRenderingVocabulary.YEAR,
    StopConvention.INCLUSIVE,
    25,
    fetch_padding=timedelta(0),
)

# Keskkonnaandmed f_hydroseire publishes a 20,000-row response cap and queries
# UTC timeline_ts_utc directly; 365-day spans keep single-series responses <= 8,784 rows.
_FH_WINDOW = WindowDeclaration(
    WindowGranularity("capped-span"),
    WindowRenderingVocabulary.ISO_INSTANT,
    StopConvention.INCLUSIVE,
    365,
    fetch_padding=timedelta(0),
)

_WINDOW_DECLARATIONS = ProductWindowDeclarations(
    {ProductId(spec.product_id): _EM_WINDOW if spec.source_api == "estmodel" else _FH_WINDOW for spec in PRODUCT_SPECS}
)


def config() -> ProviderConfig:
    """Return Estonia (`ee_est`) configured observation products."""
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    """Return per-product windowing contracts for EstModel and `f_hydroseire`."""
    return _WINDOW_DECLARATIONS
