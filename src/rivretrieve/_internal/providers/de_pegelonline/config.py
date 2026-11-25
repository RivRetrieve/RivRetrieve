"""Provider configuration and request coordinates for PEGELONLINE REST API v2.

`de_pegelonline` has one access route per product (`measurements.json` for one
timeseries `shortname`); the station varies per call and is never baked into
`SourceCoordinates`, matching `ch_foen`/`lt_lhmt`/`fr_hubeau`'s own shape where
`fetch()`'s `stations` argument supplies that half of the address.
"""

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
from rivretrieve._internal.providers.de_pegelonline.series import QUANTITIES

# The canonical target Unit per quantity (source_series.py's admission() target
# units: discharge->m3/s, stage->m, temperature->degC). This is declarative only
# and distinct from each station's actual native `source_unit`/`normalized_unit`,
# which genuinely varies per station for `W`/`TRM` (cm / m+NN / m+PNP) and is
# established per station at response time via `series.py`'s `source_series()`,
# not here.
_PRODUCT_UNIT: dict[str, Unit] = {
    "W": Unit.M,
    "Q": Unit.M3_S,
    "WT": Unit.DEG_C,
    "TRM": Unit.M,
    "TRM_WT": Unit.DEG_C,
}


@dataclass(frozen=True, slots=True)
class PegelOnlineTimeseries:
    """One PEGELONLINE native timeseries route, addressed by its `shortname`."""

    shortname: str

    def __post_init__(self) -> None:
        if self.shortname not in QUANTITIES:
            raise FatalContractError(f"Unsupported de_pegelonline timeseries shortname: {self.shortname!r}")


def config() -> ProviderConfig:
    """Build the `de_pegelonline` `ProviderConfig` for REST API v2 acquisition.

    `zone` is the genuine IANA `Europe/Berlin` identifier, not a fixed offset.
    Every other provider's `ProviderConfig.zone` is a fixed value (`"+00:00"`,
    `"unknown"`, or a fixed non-UTC offset) because every other provider's own
    request offset is fixed or unknown; `de_pegelonline`'s REST API v2 request
    offset genuinely alternates `+01:00`/`+02:00` across the `Europe/Berlin` DST
    boundary, so `fetch.py` derives it directly from this zone at acquisition
    time rather than from a generic fixed-offset rendering.
    """
    return ProviderConfig(
        zone=ZoneValue("Europe/Berlin"),
        products={
            ProductId(shortname): ProductConfig(
                SourceCoordinates(PegelOnlineTimeseries(shortname)),
                _PRODUCT_UNIT[shortname],
                UnknownTemporalSupport(),
            )
            for shortname in QUANTITIES
        },
    )


def window_declarations() -> ProductWindowDeclarations:
    """Declare one explicit-instant, closed (inclusive-both-ends) window per product.

    Live-verified: a request for `?start=T1&end=T2` on `measurements.json`
    returns the row timestamped exactly `T2` (not excluded), so this uses
    `StopConvention.INCLUSIVE` — unlike `ch_foen`'s GraphQL `_lt` exclusive-stop
    comparison. No `timestamp_precision` is declared: it requires an exclusive
    stop convention, and `de_pegelonline` never subdivides a window (no
    documented row cap; `fetch()` always reports `WindowResponseMeaning.COMPLETE`).
    """
    declaration = WindowDeclaration(
        WindowGranularity("iso-instant"),
        WindowRenderingVocabulary.ISO_INSTANT,
        StopConvention.INCLUSIVE,
    )
    return ProductWindowDeclarations(dict.fromkeys(config().products, declaration))
