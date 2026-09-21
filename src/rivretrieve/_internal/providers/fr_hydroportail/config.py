"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
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
from rivretrieve._internal.provider_series import SeriesMapping
from rivretrieve._internal.source_series import SourceUnitCodeDefinition


@dataclass(frozen=True, slots=True)
class FrHydroportailSourceCoordinates:
    field: Literal["Q", "H"]


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_instantaneous"): ProductConfig(
            SourceCoordinates(FrHydroportailSourceCoordinates("Q")), Unit.L_S, Instant()
        ),
        ProductId("stage_instantaneous"): ProductConfig(
            SourceCoordinates(FrHydroportailSourceCoordinates("H")), Unit.MM, Instant()
        ),
    },
)
_DMY = WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE_DMY, StopConvention.INCLUSIVE)
_WINDOWS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _DMY))


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOWS


# Explicit source access and physical mapping; not a completeness assertion.

SERIES_MAPPINGS = {
    "discharge_instantaneous": SeriesMapping(
        "fr_hydroportail/Q",
        "discharge",
        "l",
        "l/s",
        None,
        "instantaneous",
        "raw",
        "+00:00",
        temporal_support="instantaneous",
        evidence=(
            "tests/test_data/fr_hydroportail_station_Q_padded.recording.json: series.title=Débit instantané; station series.metric=Q, statuses=raw, timezone=UTC; source t labels end in Z",
        ),
        source_unit_definition=SourceUnitCodeDefinition(
            provider_id="fr_hydroportail",
            namespace="fr_hydroportail/Q",
            code="l",
            unit="l/s",
            evidence=(
                "https://hydro.eaufrance.fr/build/4210.e6896d9b.js "
                "sha256:72571d0bd095d5cf616a1378e799aa5e8f6818330fcca2f5691891463a92cda6 "
                "HydroPortail Q unit selector: code=l, label=unit.q.l",
                "https://hydro.eaufrance.fr/build/5621.4ab47ec9.js "
                "sha256:ab41e52a4af9b0cec642de98c68cd445f4a9b269f705da45dc43bd5664494823 "
                "HydroPortail common.unit.q.l=l/s",
            ),
        ),
    ),
    "stage_instantaneous": SeriesMapping(
        "fr_hydroportail/H",
        "stage",
        "mm",
        "mm",
        None,
        "instantaneous",
        "raw",
        "+00:00",
        temporal_support="instantaneous",
        evidence=(
            "tests/test_data/fr_hydroportail_H_padded.recording.json: series.title=Hauteur instantanée; station series.metric=H, unit=mm, statuses=raw, timezone=UTC; source t labels end in Z",
        ),
    ),
}
