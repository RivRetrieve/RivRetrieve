"""ANA source product declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

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
from rivretrieve._internal.primitives import ProductId


@dataclass(frozen=True, slots=True)
class BrAnaSourceCoordinates:
    """The adopted telemetry field published by ANA, not a quality classification."""

    field: Literal["Cota_Adotada", "Vazao_Adotada"]

    def __post_init__(self) -> None:
        if self.field not in ("Cota_Adotada", "Vazao_Adotada"):
            raise ValueError("ANA adopted telemetry field must be Cota_Adotada or Vazao_Adotada")


@dataclass(frozen=True, slots=True)
class BrAnaDailySourceCoordinates:
    """An explicitly selected Hidro daily-mean source variant, without preference."""

    endpoint: Literal["HidroSerieCotas", "HidroSerieVazao"]
    field_prefix: Literal["Cota", "Vazao"]
    consistency: Literal["1", "2"]

    def __post_init__(self) -> None:
        if (self.endpoint, self.field_prefix) not in (
            ("HidroSerieCotas", "Cota"),
            ("HidroSerieVazao", "Vazao"),
        ):
            raise ValueError("ANA daily endpoint and day-slot field must correspond")
        if self.consistency not in ("1", "2"):
            raise ValueError("ANA consistency must be 1 (Bruto) or 2 (Consistido)")


@dataclass(frozen=True, slots=True)
class BrAnaSharedEndpointCoordinates:
    """One ANA endpoint response shared across co-published source products."""

    endpoint: Literal["HidroinfoanaSerieTelemetricaAdotada", "HidroSerieCotas", "HidroSerieVazao"]

    def __post_init__(self) -> None:
        if self.endpoint not in (
            "HidroinfoanaSerieTelemetricaAdotada",
            "HidroSerieCotas",
            "HidroSerieVazao",
        ):
            raise ValueError(
                "ANA shared endpoint must be HidroinfoanaSerieTelemetricaAdotada, HidroSerieCotas, or HidroSerieVazao"
            )


SHARED_ACQUISITION_PRODUCTS: tuple[frozenset[ProductId], ...] = (
    frozenset((ProductId("discharge_instantaneous"), ProductId("stage_instantaneous"))),
    frozenset((ProductId("discharge_daily_mean_bruto"), ProductId("discharge_daily_mean_consistido"))),
    frozenset((ProductId("stage_daily_mean_bruto"), ProductId("stage_daily_mean_consistido"))),
)


# ANA manual PDF page 11: Cota_Adotada (cm), Vazao_Adotada (m3/s),
# Data_Hora_Medicao = measurement/collection time. No source zone is established.
_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_instantaneous"): ProductConfig(
            SourceCoordinates(BrAnaSourceCoordinates("Vazao_Adotada")),
            Unit.M3_S,
            Instant(),
        ),
        ProductId("stage_instantaneous"): ProductConfig(
            SourceCoordinates(BrAnaSourceCoordinates("Cota_Adotada")),
            Unit.CM,
            Instant(),
        ),
        # Hidro1.4 dictionary pp21–24: MediaDiaria1; Bruto1/Consistido2.
        # Source calendar/header and ordinal SQL establish midnight labels, NOT
        # the daily support interval or a zone. These remain unknown.
        ProductId("discharge_daily_mean_bruto"): ProductConfig(
            SourceCoordinates(BrAnaDailySourceCoordinates("HidroSerieVazao", "Vazao", "1")),
            Unit.M3_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_daily_mean_consistido"): ProductConfig(
            SourceCoordinates(BrAnaDailySourceCoordinates("HidroSerieVazao", "Vazao", "2")),
            Unit.M3_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_mean_bruto"): ProductConfig(
            SourceCoordinates(BrAnaDailySourceCoordinates("HidroSerieCotas", "Cota", "1")),
            Unit.CM,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_mean_consistido"): ProductConfig(
            SourceCoordinates(BrAnaDailySourceCoordinates("HidroSerieCotas", "Cota", "2")),
            Unit.CM,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
    },
)
# Current OpenAPI permits DIAS_30. Real overlapping requests establish exact
# whole-day backward ranges on the native wall-clock axis INCLUDING the anchor
# date, with zero timezone drift; fetch_padding=0 keeps 30-day spans in one call.
_WINDOW = WindowDeclaration(
    WindowGranularity("fixed-backward-span"),
    WindowRenderingVocabulary.DATE,
    StopConvention.INCLUSIVE,
    30,
    fetch_padding=timedelta(0),
)
# Conventional daily endpoints store monthly records keyed on YYYY-MM-01 and
# enforce a documented 366-day cap. Whole-month spans of at most 12 calendar
# months always start on day 01 (never dropping the opening month) and remain
# <= 366 inclusive days even across leap years.
_DAILY_WINDOW = WindowDeclaration(
    WindowGranularity("capped-month-span"),
    WindowRenderingVocabulary.DATE,
    StopConvention.INCLUSIVE,
    12,
    fetch_padding=timedelta(0),
)
_WINDOWS = ProductWindowDeclarations(
    {
        product: _DAILY_WINDOW if isinstance(definition.coordinates.value, BrAnaDailySourceCoordinates) else _WINDOW
        for product, definition in _CONFIG.products.items()
    }
)


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS
