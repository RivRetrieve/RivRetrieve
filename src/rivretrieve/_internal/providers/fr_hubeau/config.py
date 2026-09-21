"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
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
from rivretrieve._internal.provider_series import SeriesMapping


@dataclass(frozen=True, slots=True)
class FrHubeauSourceCoordinates:
    family: Literal["daily", "temperature"]
    field: str


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "QmnJ")),
            Unit.L_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("discharge_daily_max"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "QIXnJ")),
            Unit.L_S,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("stage_daily_max"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("daily", "HIXnJ")),
            Unit.MM,
            Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
        ),
        ProductId("water_temperature_reported"): ProductConfig(
            SourceCoordinates(FrHubeauSourceCoordinates("temperature", "resultat")),
            Unit.DEG_C,
            UnknownTemporalSupport(),
        ),
    },
)
_DATE = WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)
_WINDOWS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _DATE))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS


# Explicit source access and physical mapping; not a completeness assertion.

SERIES_MAPPINGS = {
    "discharge_daily_mean": SeriesMapping(
        "fr_hubeau/daily/QmnJ",
        "discharge",
        "l/s",
        "l/s",
        "daily",
        "mean",
        None,
        None,
        temporal_support="interval",
        label_time="00:00",
        evidence=(
            "tests/test_data/fr_hubeau_openapi_v2.json: obs_elab grandeur_hydro_elab=QmnJ definition",
            "tests/test_data/fr_hubeau_hydrometrie.html: Unités des observations: mm pour les hauteurs, l/s pour les débits",
            "tests/test_data/fr_hubeau_1011000101_QmnJ_padded.recording.json: date_obs_elab date-only labels represented at midnight",
        ),
    ),
    "discharge_daily_max": SeriesMapping(
        "fr_hubeau/daily/QIXnJ",
        "discharge",
        "l/s",
        "l/s",
        "daily",
        "max",
        None,
        None,
        label_time="00:00",
        evidence=(
            "tests/test_data/fr_hubeau_openapi_v2.json: obs_elab grandeur_hydro_elab=QIXnJ definition",
            "tests/test_data/fr_hubeau_hydrometrie.html: Unités des observations: mm pour les hauteurs, l/s pour les débits",
            "tests/test_data/fr_hubeau_1011000101_QIXnJ_padded.recording.json: date_obs_elab date-only labels represented at midnight",
        ),
    ),
    "stage_daily_max": SeriesMapping(
        "fr_hubeau/daily/HIXnJ",
        "stage",
        "mm",
        "mm",
        "daily",
        "max",
        None,
        None,
        label_time="00:00",
        evidence=(
            "tests/test_data/fr_hubeau_openapi_v2.json: obs_elab grandeur_hydro_elab=HIXnJ definition",
            "tests/test_data/fr_hubeau_hydrometrie.html: Unités des observations: mm pour les hauteurs, l/s pour les débits",
            "tests/test_data/fr_hubeau_1011000101_HIXnJ_padded.recording.json: date_obs_elab date-only labels represented at midnight",
        ),
    ),
    "water_temperature_reported": SeriesMapping(
        "fr_hubeau/temperature/resultat",
        "temperature",
        "°C",
        "degC",
        None,
        None,
        None,
        None,
        evidence=(
            "tests/test_data/fr_hubeau_01001336_temp_padded_p1.recording.json: libelle_parametre=Température de l'Eau, symbole_unite=°C, code_unite=27",
            "tests/test_data/fr_hubeau_01001336_temp_padded_p1.recording.json: separate source date_mesure_temp/heure_mesure_temp without zone",
        ),
    ),
}
