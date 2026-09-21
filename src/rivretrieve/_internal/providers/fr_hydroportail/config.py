"""config/window_declarations : () → ProviderConfig × ProductWindowDeclarations.

Contributed by: Thiago von Däniken
"""

from dataclasses import dataclass, replace
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
from rivretrieve._internal.source_series import SourceSeries, SourceUnitCodeDefinition, stable_id

VARIANTS = ("raw", "validated", "pre_validated_and_validated", "most_valid")


@dataclass(frozen=True, slots=True)
class FrHydroportailSourceCoordinates:
    field: Literal["Q", "H"]
    variant: str = "raw"

    def __post_init__(self) -> None:
        if self.field not in ("Q", "H") or self.variant not in VARIANTS:
            raise ValueError("Unsupported HydroPortail station series selector")


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


def series_mapping(product: str, variant: str) -> SeriesMapping:
    """Resolve a published selector without changing the physical quantity."""
    if variant not in VARIANTS:
        raise ValueError("Unsupported HydroPortail station series selector")
    return replace(
        SERIES_MAPPINGS[product],
        published_id=variant,
        identity_evidence=(
            "tests/test_data/fr_hydroportail_variants/REPORT.md: "
            "2026-09-21 station form and independent Q/H selector captures",
            "https://hydro.eaufrance.fr/stationhydro/1232000101/series: "
            f"hydro_series[statusData]={variant}; source-published station Q/H selector",
        ),
    )


def source_series(station: str, product: str, variant: str) -> SourceSeries:
    """Describe one station-own source selection, including empty histories."""
    mapping = series_mapping(product, variant)
    return SourceSeries(
        series_id=stable_id("fr_hydroportail", station, mapping.namespace, variant),
        provider_id="fr_hydroportail",
        station_id=station,
        product_id=product,
        identity=mapping.identity(),
        variant=variant,
        facts=(mapping.physical_facts(),),
    )
