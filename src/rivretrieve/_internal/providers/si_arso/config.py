"""Official Slovenia ARSO (``si_arso``) runtime product config and window declarations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

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
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.si_arso.series import (
    PRODUCT_SPECS,
    SPECS_BY_AMP_ROUTE,
    SPECS_BY_ARCHIVE_COLUMN,
    SPECS_BY_EKS_PREFIX,
    SiArsoProductSpec,
)

_UNITS: dict[str, Unit] = {
    "m3/s": Unit.M3_S,
    "cm": Unit.CM,
    "degC": Unit.DEG_C,
}


@dataclass(frozen=True, slots=True)
class SiArsoArchiveCoordinates:
    """Product-level route coordinates inside ``pov_arhiv_tab.php`` CSV exports."""

    stream: Literal["archive_daily", "archive_monthly_extremes"]
    b_flag: Literal["b_oddo_CSV", "b_eks_CSV"]
    field_name: str

    def __post_init__(self) -> None:
        if self.stream == "archive_daily":
            if self.b_flag != "b_oddo_CSV" or self.field_name not in SPECS_BY_ARCHIVE_COLUMN:
                raise ValueError(f"Unsupported si_arso archive_daily coordinates: {self.b_flag!r}, {self.field_name!r}")
            return
        if self.stream == "archive_monthly_extremes":
            if self.b_flag != "b_eks_CSV" or self.field_name not in SPECS_BY_EKS_PREFIX:
                raise ValueError(
                    f"Unsupported si_arso archive_monthly_extremes coordinates: {self.b_flag!r}, {self.field_name!r}"
                )
            return
        raise ValueError(f"Unsupported si_arso archive stream: {self.stream!r}")


@dataclass(frozen=True, slots=True)
class SiArsoAmpCoordinates:
    """Product-level route coordinates inside ``/vode/podatki/amp/H{sifra}_t_{1,7,30}.html``."""

    amp_cadence: Literal["t_1", "t_7", "t_30"]
    amp_column: str

    def __post_init__(self) -> None:
        if (self.amp_cadence, self.amp_column) not in SPECS_BY_AMP_ROUTE:
            raise ValueError(f"Unsupported si_arso amp coordinates: {(self.amp_cadence, self.amp_column)!r}")


type SiArsoSourceCoordinates = SiArsoArchiveCoordinates | SiArsoAmpCoordinates


def _product_coordinates(spec: SiArsoProductSpec) -> SiArsoSourceCoordinates:
    if spec.stream == "archive_daily":
        assert spec.archive_column is not None
        return SiArsoArchiveCoordinates("archive_daily", "b_oddo_CSV", spec.archive_column)
    if spec.stream == "archive_monthly_extremes":
        assert spec.eks_prefix is not None
        return SiArsoArchiveCoordinates("archive_monthly_extremes", "b_eks_CSV", spec.eks_prefix)
    assert spec.amp_cadence is not None and spec.amp_column is not None
    return SiArsoAmpCoordinates(spec.amp_cadence, spec.amp_column)


def _product_semantics(spec: SiArsoProductSpec) -> Daily | Hourly | UnknownTemporalSupport:
    if spec.stream == "archive_daily":
        return Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))
    if spec.frequency == "PT1H":
        return Hourly(IntervalDefinition("unknown"))
    return UnknownTemporalSupport()


# Use date granularity with zero padding so single-year requests hit only the requested
# calendar years rather than padding adjacent years into pov_arhiv_tab.php queries.
_ARCHIVE_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("date"),
    rendering=WindowRenderingVocabulary.DATE,
    stop_convention=StopConvention.INCLUSIVE,
    fetch_padding=timedelta(0),
)
_AMP_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("none"),
    rendering=WindowRenderingVocabulary.NONE,
    stop_convention=StopConvention.INCLUSIVE,
)

SHARED_ACQUISITION_PRODUCTS: tuple[frozenset[ProductId], ...] = (
    frozenset(ProductId(spec.product_id) for spec in PRODUCT_SPECS if spec.stream == "archive_daily"),
    frozenset(ProductId(spec.product_id) for spec in PRODUCT_SPECS if spec.stream == "archive_monthly_extremes"),
    frozenset(
        ProductId(spec.product_id) for spec in PRODUCT_SPECS if spec.stream == "amp" and spec.amp_cadence == "t_1"
    ),
    frozenset(
        ProductId(spec.product_id) for spec in PRODUCT_SPECS if spec.stream == "amp" and spec.amp_cadence == "t_7"
    ),
    frozenset(
        ProductId(spec.product_id) for spec in PRODUCT_SPECS if spec.stream == "amp" and spec.amp_cadence == "t_30"
    ),
)

_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId(spec.product_id): ProductConfig(
            coordinates=SourceCoordinates(_product_coordinates(spec)),
            unit=_UNITS[spec.normalized_unit],
            semantics=_product_semantics(spec),
        )
        for spec in PRODUCT_SPECS
    },
    cache=None,
)

_WINDOWS = ProductWindowDeclarations(
    products={
        ProductId(spec.product_id): _AMP_WINDOW if spec.stream == "amp" else _ARCHIVE_WINDOW for spec in PRODUCT_SPECS
    }
)


def config() -> ProviderConfig:
    """Return immutable ``si_arso`` provider configuration."""
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    """Return ``si_arso`` window declarations for archive and operational streams."""
    return _WINDOWS
