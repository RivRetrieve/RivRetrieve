"""Ireland OPW Hydro-Data (``ie_opw``) source coordinates, config, and window declarations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    Instant,
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
from rivretrieve._internal.providers.ie_opw.series import (
    COMPLETE_ZIP_BY_PARAM,
    PRODUCT_SPECS,
    YEAR_JSON_BY_PARAM_SHORTNAME,
)

_DAILY_SEMANTICS = Daily(DayDefinition("00:00"), DailyLabelTime("00:00"))
_INSTANT_SEMANTICS = Instant()
_UNITS: dict[str, Unit] = {
    "cumec": Unit.M3_S,
    "m": Unit.M,
    "°C": Unit.DEG_C,
}


@dataclass(frozen=True, slots=True)
class OpwDailyYearJsonCoordinates:
    """Native OPW Hydro-Data ``{param}/year.json`` series selector."""

    parameter: Literal["Q", "S", "TWater"]
    ts_shortname: str
    product_id: str

    def __post_init__(self) -> None:
        spec = YEAR_JSON_BY_PARAM_SHORTNAME.get((self.parameter, self.ts_shortname))
        if spec is None or spec.product_id != self.product_id:
            raise FatalContractError(
                "Invalid ie_opw year.json coordinates: "
                f"parameter={self.parameter!r}, ts_shortname={self.ts_shortname!r}, product_id={self.product_id!r}"
            )


@dataclass(frozen=True, slots=True)
class OpwDailyYearJsonEndpointCoordinates:
    """Shared ``{param}/year.json`` endpoint payload spanning multiple daily statistics."""

    parameter: Literal["Q", "S", "TWater"]

    def __post_init__(self) -> None:
        if self.parameter not in ("Q", "S", "TWater"):
            raise FatalContractError(f"Invalid ie_opw year.json parameter: {self.parameter!r}")


@dataclass(frozen=True, slots=True)
class OpwCompleteZipCoordinates:
    """Native OPW Hydro-Data ``{param}/*_complete.zip`` archive selector."""

    parameter: Literal["Q", "S", "TWater"]
    route: Literal["Discharge_complete.zip", "Waterlevel_complete.zip", "WaterTemperature_complete.zip"]
    ts_shortname: str
    product_id: str

    def __post_init__(self) -> None:
        spec = COMPLETE_ZIP_BY_PARAM.get(self.parameter)
        if (
            spec is None
            or spec.route != self.route
            or spec.ts_shortname != self.ts_shortname
            or spec.product_id != self.product_id
        ):
            raise FatalContractError(
                "Invalid ie_opw complete.zip coordinates: "
                f"parameter={self.parameter!r}, route={self.route!r}, "
                f"ts_shortname={self.ts_shortname!r}, product_id={self.product_id!r}"
            )


def _product_config(spec_index: int) -> ProductConfig:
    spec = PRODUCT_SPECS[spec_index]
    if spec.route == "year.json":
        coords: OpwDailyYearJsonCoordinates | OpwCompleteZipCoordinates = OpwDailyYearJsonCoordinates(
            parameter=spec.parameter,
            ts_shortname=spec.ts_shortname,
            product_id=spec.product_id,
        )
        semantics: Daily | Instant = _DAILY_SEMANTICS
    else:
        coords = OpwCompleteZipCoordinates(
            parameter=spec.parameter,
            route=spec.route,
            ts_shortname=spec.ts_shortname,
            product_id=spec.product_id,
        )
        semantics = _INSTANT_SEMANTICS
    return ProductConfig(
        coordinates=SourceCoordinates(coords),
        unit=_UNITS[spec.source_unit],
        semantics=semantics,
    )


_CONFIG = ProviderConfig(
    zone=ZoneValue("+00:00"),
    products={ProductId(spec.product_id): _product_config(index) for index, spec in enumerate(PRODUCT_SPECS)},
)

_SOURCE_FIXED_WINDOW = WindowDeclaration(
    WindowGranularity("none"),
    WindowRenderingVocabulary.NONE,
    StopConvention.INCLUSIVE,
    fetch_padding=timedelta(0),
)
_WINDOW_DECLARATIONS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _SOURCE_FIXED_WINDOW))


def config() -> ProviderConfig:
    """Return Ireland OPW (`ie_opw`) configured observation products."""
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    """Return source-fixed ``WindowGranularity('none')`` contracts for all 12 products."""
    return _WINDOW_DECLARATIONS
